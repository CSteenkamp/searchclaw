# Spec 5 — Map Endpoint, Search Depth Modes, Content Chunking

## Context
SearchClaw API at `api.searchclaw.dev`. FastAPI + Redis + PostgreSQL + SearXNG + Playwright. Repo: `/tmp/dataclaw`.

This spec adds three features that match competitor parity (Tavily, Firecrawl, Exa) and improve output quality for RAG pipelines.

---

## 5.1 — `/v1/map` Endpoint (URL Discovery)

Discover all URLs on a domain without extracting content. Useful for agents doing reconnaissance before targeted crawling.

### How it works
1. Client sends a base URL (e.g., `https://docs.example.com`)
2. SearchClaw fetches the page, discovers links (same-domain), follows them breadth-first
3. Optionally checks `/sitemap.xml` and `/robots.txt` for additional URLs
4. Returns a deduplicated list of discovered URLs with metadata

### API

```
POST /v1/map
```

#### Request
```json
{
  "url": "https://docs.example.com",
  "max_pages": 100,
  "include_subdomains": false,
  "search": "optional filter query",
  "ignore_sitemap": false,
  "limit": 50
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | required | Base URL to map |
| `max_pages` | int | 100 | Max pages to discover (cap at 500) |
| `include_subdomains` | bool | false | Include subdomains in crawl |
| `search` | string | null | Filter URLs by keyword match |
| `ignore_sitemap` | bool | false | Skip sitemap.xml discovery |
| `limit` | int | 50 | Max URLs to return in response |

#### Response
```json
{
  "success": true,
  "url": "https://docs.example.com",
  "total_discovered": 156,
  "urls": [
    {
      "url": "https://docs.example.com/getting-started",
      "title": "Getting Started — Example Docs",
      "source": "crawl"
    },
    {
      "url": "https://docs.example.com/api-reference",
      "title": "API Reference",
      "source": "sitemap"
    }
  ],
  "credits_used": 1
}
```

### Implementation

#### `api/routers/map.py` — NEW
- Create new router with `POST /v1/map`
- Auth + rate limit + credit reserve (1 credit per map request)
- Call `map_service.discover_urls()`

#### `api/services/map_service.py` — NEW
- `async def discover_urls(url, max_pages, include_subdomains, search, ignore_sitemap, limit) -> dict`
- Step 1: Fetch `/robots.txt` to check crawl permissions and find sitemap references
- Step 2: Fetch `/sitemap.xml` (and nested sitemaps) — parse URLs
- Step 3: BFS crawl from base URL:
  - Fetch page HTML
  - Extract all `<a href>` links
  - Filter to same domain (+ subdomains if enabled)
  - Deduplicate
  - Extract `<title>` for each discovered page
  - Respect `max_pages` limit
- Step 4: Merge sitemap + crawl URLs, deduplicate
- Step 5: If `search` provided, filter URLs where URL path or title contains the search term
- Step 6: Return up to `limit` URLs
- Use `httpx.AsyncClient` with connection pooling
- Timeout: 5s per page fetch
- Cache results in Redis for 1 hour (key: `map:{url_hash}`)

#### `api/models/map.py` — NEW
- Pydantic models: `MapRequest`, `MapURL`, `MapResponse`

### Register
- Add router in `api/main.py`: `app.include_router(map_router)`

### Tests — `api/tests/test_map.py`
- Test sitemap parsing
- Test BFS discovery with mock HTML
- Test URL deduplication
- Test search filtering
- Test credit accounting
- Test max_pages cap

---

## 5.2 — Search Depth Modes

Add quality/latency tradeoff options to the search endpoint, matching Tavily's `search_depth` and Exa's latency profiles.

### API Changes

Add `depth` parameter to `POST /v1/search`:

```json
{
  "query": "best restaurants in Cape Town",
  "depth": "fast",
  "max_results": 10
}
```

| Depth | Credits | Behaviour | Use case |
|-------|---------|-----------|----------|
| `fast` | 1 | Single SearXNG query, first results, no re-ranking. Timeout: 3s. | Real-time agent tool calls |
| `basic` | 1 | Current behaviour (default). Standard SearXNG query. Timeout: 10s. | General purpose |
| `deep` | 2 | Query SearXNG twice with reformulated queries, merge + deduplicate + re-rank by relevance. Fetch snippets from top results if SearXNG didn't return them. Timeout: 20s. | Research, comprehensive results |

### Implementation

#### Modify `api/routers/search.py`
- Add `depth: Literal["fast", "basic", "deep"] = "basic"` to search request model
- `fast`: set `searxng_timeout=3`, take first `max_results`, skip re-ranking
- `basic`: current behaviour (no changes)
- `deep`: 
  1. Send original query to SearXNG
  2. Generate a reformulated query (simple: add "site:reddit.com OR site:hackernews" or rephrase using keyword extraction)
  3. Send reformulated query to SearXNG
  4. Merge results, deduplicate by URL
  5. Re-rank using a simple TF-IDF relevance score against original query
  6. Return top `max_results`
  7. Charge 2 credits instead of 1

#### Modify `api/services/searxng_client.py`
- Add `timeout` parameter support
- Add method `search_multi(queries: list[str], timeout: float) -> list[results]`

#### Modify `api/services/query_normalizer.py`
- Add `reformulate_query(query: str) -> str` — simple query expansion (add synonyms, split compound queries)

### Tests
- `api/tests/test_search.py` — add tests for each depth mode
- Test that `deep` charges 2 credits
- Test that `fast` has shorter timeout
- Test result deduplication in `deep` mode

---

## 5.3 — Content Chunking for RAG

Add chunking options to extract and markdown endpoints so output is RAG-ready without client-side processing.

### API Changes

Add chunking parameters to `POST /v1/extract`, `POST /v1/markdown`, and `POST /v1/pipeline`:

```json
{
  "url": "https://example.com/article",
  "chunking": {
    "enabled": true,
    "max_chunk_size": 500,
    "overlap": 50,
    "strategy": "semantic"
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `chunking.enabled` | bool | false | Enable chunked output |
| `chunking.max_chunk_size` | int | 500 | Max characters per chunk |
| `chunking.overlap` | int | 50 | Character overlap between chunks |
| `chunking.strategy` | string | "fixed" | `fixed` (character-based), `sentence` (sentence boundaries), `semantic` (paragraph/section boundaries) |

### Response with chunking enabled
```json
{
  "success": true,
  "url": "https://example.com/article",
  "markdown": "# Full Article...",
  "chunks": [
    {
      "index": 0,
      "text": "First chunk of content...",
      "char_count": 487,
      "metadata": {
        "heading": "Introduction",
        "position": "start"
      }
    },
    {
      "index": 1,
      "text": "Second chunk of content...",
      "char_count": 492,
      "metadata": {
        "heading": "Methods",
        "position": "middle"
      }
    }
  ],
  "total_chunks": 12,
  "credits_used": 1
}
```

### Implementation

#### `api/services/chunker.py` — NEW
- `def chunk_text(text: str, max_size: int, overlap: int, strategy: str) -> list[Chunk]`
- **fixed strategy**: Split at `max_size` characters, with `overlap` char overlap. Break at word boundaries.
- **sentence strategy**: Use regex sentence splitting (`[.!?]\s+`). Accumulate sentences until `max_size` reached, then start new chunk with `overlap` chars from end of previous.
- **semantic strategy**: Split on markdown headings (`#`, `##`, etc.) and double newlines (paragraphs). If a section exceeds `max_size`, fall back to sentence splitting within that section.
- Each chunk includes metadata: `index`, `char_count`, `heading` (nearest parent heading if detectable), `position` (start/middle/end)

#### `api/models/extraction.py`
- Add `ChunkingConfig` model: `enabled`, `max_chunk_size`, `overlap`, `strategy`
- Add `Chunk` model: `index`, `text`, `char_count`, `metadata`
- Add `chunking` field to extract/markdown request models
- Add `chunks` and `total_chunks` to response models

#### Modify `api/routers/extract.py`, `api/routers/markdown.py`, `api/routers/pipeline.py`
- After extraction/markdown conversion, if `chunking.enabled`, run `chunk_text()` on the result
- Include `chunks` array in response alongside full content
- No extra credit cost for chunking (it's post-processing)

### Tests — `api/tests/test_chunker.py`
- Test fixed chunking with overlap
- Test sentence boundary detection
- Test semantic chunking with markdown headings
- Test edge cases: empty text, text shorter than max_size, single sentence
- Test chunk metadata (heading detection)

---

## Acceptance Criteria
- [ ] `POST /v1/map` discovers URLs from sitemap + BFS crawl
- [ ] Map results are cached in Redis for 1 hour
- [ ] Search supports `depth` parameter: fast (3s, 1 credit), basic (10s, 1 credit), deep (20s, 2 credits)
- [ ] Deep search merges and deduplicates results from multiple queries
- [ ] Extract, markdown, and pipeline support `chunking` config
- [ ] Three chunking strategies work: fixed, sentence, semantic
- [ ] Chunks include metadata (index, heading, position)
- [ ] No extra credit cost for chunking
- [ ] All features have tests
