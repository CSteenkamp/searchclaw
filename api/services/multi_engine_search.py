"""Multi-engine search with geographic enhancement and result fusion."""

import asyncio
import httpx
import json
from typing import List, Dict, Optional, Any, Tuple
from urllib.parse import quote_plus, urlencode
import re
import time

from api.services.geo_enhancer import (
    enhance_query_geographically, 
    detect_location_context, 
    detect_search_category,
    get_fallback_directories,
    add_pricing_context
)

class MultiEngineSearcher:
    """Multi-engine search with result fusion and geographic enhancement."""
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            limits=httpx.Limits(max_connections=50)
        )
        self.engines = {
            "brave": self._search_brave,
            "bing": self._search_bing, 
            "duckduckgo": self._search_duckduckgo,
            "searxng": self._search_searxng_fallback
        }
    
    async def enhanced_search(
        self, 
        query: str, 
        engines: List[str] = None,
        force_country: str = "south_africa",
        max_results: int = 10
    ) -> Dict[str, Any]:
        """
        Perform enhanced geographic search across multiple engines.
        """
        start_time = time.time()
        
        # Default engines in priority order
        if engines is None:
            engines = ["brave", "bing", "duckduckgo"]
        
        # Detect context
        location_context = detect_location_context(query)
        search_category = detect_search_category(query)
        
        # Force South African context if no location detected
        if not location_context and force_country:
            location_context = {"country": force_country}
        
        # Enhance query with pricing context
        enhanced_base_query = add_pricing_context(query, force_country)
        
        # Generate multiple enhanced queries
        enhanced_queries = enhance_query_geographically(enhanced_base_query, force_country)
        
        # Prepare search tasks
        all_results = []
        search_tasks = []
        
        # Search with enhanced queries on multiple engines
        for i, enhanced_query in enumerate(enhanced_queries[:3]):  # Limit to top 3 enhanced queries
            for engine in engines:
                if engine in self.engines:
                    task = asyncio.create_task(
                        self._safe_search(engine, enhanced_query, max_results // len(engines))
                    )
                    search_tasks.append((task, engine, enhanced_query, i))
        
        # Execute searches concurrently
        completed_tasks = []
        try:
            # Wait for all searches with timeout
            results = await asyncio.wait_for(
                asyncio.gather(*[task for task, _, _, _ in search_tasks], return_exceptions=True),
                timeout=12.0
            )
            
            for (task, engine, enhanced_query, priority), result in zip(search_tasks, results):
                if not isinstance(result, Exception) and result:
                    for item in result.get("results", []):
                        item["_engine"] = engine
                        item["_enhanced_query"] = enhanced_query
                        item["_priority"] = priority
                    all_results.extend(result.get("results", []))
                    completed_tasks.append((engine, len(result.get("results", []))))
                else:
                    completed_tasks.append((engine, 0))
                    
        except asyncio.TimeoutError:
            # Some searches timed out, proceed with what we have
            pass
        
        # If we got very few results, try fallback directories
        if len(all_results) < 3 and location_context:
            fallback_directories = get_fallback_directories(location_context, search_category)
            
            for directory_query in fallback_directories[:2]:  # Max 2 fallback searches
                try:
                    fallback_result = await self._search_brave(directory_query, 5)
                    if fallback_result and fallback_result.get("results"):
                        for item in fallback_result["results"]:
                            item["_engine"] = "brave_fallback"
                            item["_enhanced_query"] = directory_query
                            item["_priority"] = 99  # Low priority
                        all_results.extend(fallback_result["results"])
                except:
                    pass
        
        # Deduplicate and rank results
        final_results = self._deduplicate_and_rank(all_results, query)
        
        # Limit to requested number
        final_results = final_results[:max_results]
        
        # Build response
        response_time_ms = int((time.time() - start_time) * 1000)
        
        return {
            "query": query,
            "enhanced_queries": enhanced_queries[:3],
            "location_context": location_context,
            "search_category": search_category,
            "results": final_results,
            "meta": {
                "total_results": len(final_results),
                "engines_used": list(set([engine for engine, _ in completed_tasks if _ > 0])),
                "response_time_ms": response_time_ms,
                "cached": False
            }
        }
    
    async def _safe_search(self, engine: str, query: str, max_results: int) -> Optional[Dict]:
        """Safely execute search with error handling."""
        try:
            return await self.engines[engine](query, max_results)
        except Exception as e:
            # Log error but don't fail the whole search
            print(f"Search error on {engine}: {e}")
            return None
    
    async def _search_brave(self, query: str, max_results: int = 10) -> Dict[str, Any]:
        """Search using Brave Search API."""
        # Note: This would require Brave Search API credentials
        # For now, return mock structure - implement with real API
        return {
            "results": [],
            "suggestions": []
        }
    
    async def _search_bing(self, query: str, max_results: int = 10) -> Dict[str, Any]:
        """Search using Bing Web Search API."""
        # Note: This would require Bing API credentials
        # For now, return mock structure - implement with real API
        return {
            "results": [],
            "suggestions": []
        }
    
    async def _search_duckduckgo(self, query: str, max_results: int = 10) -> Dict[str, Any]:
        """Search using DuckDuckGo (via unofficial API or scraping)."""
        try:
            # Simple DuckDuckGo instant answers API (limited but free)
            url = "https://api.duckduckgo.com/"
            params = {
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1"
            }
            
            response = await self.client.get(url, params=params)
            data = response.json()
            
            results = []
            
            # Extract results from various DDG response fields
            if data.get("AbstractText"):
                results.append({
                    "title": data.get("Heading", query),
                    "snippet": data.get("AbstractText"),
                    "url": data.get("AbstractURL", ""),
                    "source": "duckduckgo"
                })
            
            # Related topics
            for topic in data.get("RelatedTopics", [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({
                        "title": topic.get("FirstURL", {}).get("text", "Related"),
                        "snippet": topic.get("Text"),
                        "url": topic.get("FirstURL", {}).get("Result", ""),
                        "source": "duckduckgo"
                    })
            
            return {"results": results}
            
        except Exception:
            return {"results": []}
    
    async def _search_searxng_fallback(self, query: str, max_results: int = 10) -> Dict[str, Any]:
        """Fallback to existing SearXNG implementation."""
        from api.services.searxng_client import execute_search
        
        try:
            # Use existing SearXNG client
            result = await execute_search(
                q=query,
                categories="general",
                engines="",
                safesearch=0,
                format="json",
                lang="auto"
            )
            return result
        except Exception:
            return {"results": []}
    
    def _deduplicate_and_rank(self, results: List[Dict], original_query: str) -> List[Dict]:
        """Deduplicate results by URL and rank by relevance."""
        seen_urls = set()
        deduped = []
        
        for result in results:
            url = result.get("url", "")
            if not url or url in seen_urls:
                continue
                
            seen_urls.add(url)
            deduped.append(result)
        
        # Rank by multiple factors
        def rank_score(result: Dict) -> float:
            score = 0.0
            
            # Domain scoring (.co.za domains get boost)
            url = result.get("url", "")
            if ".co.za" in url:
                score += 20
            elif ".com.na" in url or ".co.bw" in url:
                score += 15
            elif "sa-venues.com" in url or "sacampsites.co.za" in url:
                score += 25
            
            # Query priority (earlier enhanced queries score higher)
            priority = result.get("_priority", 0)
            score += max(0, 10 - priority)
            
            # Engine reliability
            engine = result.get("_engine", "")
            if engine == "brave":
                score += 5
            elif engine == "bing":
                score += 3
            elif engine.endswith("_fallback"):
                score += 15  # Fallback directories are high quality
            
            # Title/snippet relevance (simple keyword matching)
            text_content = f"{result.get('title', '')} {result.get('snippet', '')}".lower()
            query_words = original_query.lower().split()
            
            matching_words = sum(1 for word in query_words if word in text_content)
            score += matching_words * 2
            
            # Length penalty for very short snippets (might be low quality)
            snippet_len = len(result.get("snippet", ""))
            if snippet_len < 20:
                score -= 5
            
            return score
        
        # Sort by score (descending)
        ranked = sorted(deduped, key=rank_score, reverse=True)
        
        return ranked
    
    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


# Global instance
_multi_searcher: Optional[MultiEngineSearcher] = None

def get_multi_searcher() -> MultiEngineSearcher:
    """Get or create global multi-engine searcher instance."""
    global _multi_searcher
    if _multi_searcher is None:
        _multi_searcher = MultiEngineSearcher()
    return _multi_searcher

async def enhanced_multi_search(
    query: str,
    engines: List[str] = None,
    force_country: str = "south_africa",
    max_results: int = 10
) -> Dict[str, Any]:
    """Convenience function for enhanced multi-engine search."""
    searcher = get_multi_searcher()
    return await searcher.enhanced_search(query, engines, force_country, max_results)