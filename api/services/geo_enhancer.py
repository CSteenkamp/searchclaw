"""Geographic query enhancement for better local/regional search results."""

import re
import json
from typing import Optional, List, Tuple
from pathlib import Path

# Geographic context database
GEO_DATABASE = {
    "south_africa": {
        "provinces": {
            "western_cape": {
                "cities": ["cape_town", "stellenbosch", "paarl", "worcester", "ceres", "tulbagh", "hermanus", "knysna", "george", "mossel_bay"],
                "terms": ["witzenberg", "hex_river", "overberg", "garden_route", "klein_karoo"],
                "domain_suffix": "co.za"
            },
            "gauteng": {
                "cities": ["johannesburg", "pretoria", "sandton", "soweto", "germiston", "benoni"],
                "terms": ["witwatersrand", "vaal", "east_rand", "west_rand"],
                "domain_suffix": "co.za"
            },
            "kwazulu_natal": {
                "cities": ["durban", "pietermaritzburg", "newcastle", "ladysmith", "port_shepstone"],
                "terms": ["drakensberg", "midlands", "south_coast", "north_coast"],
                "domain_suffix": "co.za"
            },
            "mpumalanga": {
                "cities": ["nelspruit", "witbank", "secunda", "emalahleni", "barberton"],
                "terms": ["lowveld", "highveld", "escarpment", "kruger"],
                "domain_suffix": "co.za"
            },
            "limpopo": {
                "cities": ["polokwane", "tzaneen", "phalaborwa", "louis_trichardt", "thohoyandou"],
                "terms": ["bushveld", "waterberg", "soutpansberg"],
                "domain_suffix": "co.za"
            }
        },
        "currency": "rand|zar|r[0-9]",
        "phone_pattern": r"0[0-9]{2}[\s\-]?[0-9]{3}[\s\-]?[0-9]{4}",
        "business_types": {
            "accommodation": ["guest_house", "bed_and_breakfast", "b&b", "lodge", "resort", "hotel"],
            "camping": ["caravan_park", "camping_site", "kampong", "plaaskamp", "game_lodge"],
            "activities": ["wine_farm", "game_reserve", "hiking_trail", "4x4_route"]
        }
    },
    "namibia": {
        "cities": ["windhoek", "swakopmund", "walvis_bay", "oshakati", "rundu"],
        "domain_suffix": "com.na"
    },
    "botswana": {
        "cities": ["gaborone", "francistown", "maun", "kasane"],
        "domain_suffix": "co.bw"
    }
}

# City/location mappings for disambiguation
LOCATION_MAPPINGS = {
    "ceres": {"country": "south_africa", "province": "western_cape", "nearby": ["worcester", "tulbagh", "wellington"]},
    "worcester": {"country": "south_africa", "province": "western_cape", "nearby": ["ceres", "tulbagh", "robertson"]},
    "hermanus": {"country": "south_africa", "province": "western_cape", "nearby": ["stanford", "gansbaai", "kleinmond"]},
    "knysna": {"country": "south_africa", "province": "western_cape", "nearby": ["plettenberg_bay", "george", "sedgefield"]},
    "stellenbosch": {"country": "south_africa", "province": "western_cape", "nearby": ["franschhoek", "paarl", "somerset_west"]},
}

# Common search term enhancements by category
CATEGORY_ENHANCEMENTS = {
    "accommodation": ["guest house", "bed breakfast", "lodge", "resort", "hotel", "accommodation"],
    "camping": ["caravan park", "camping site", "camp ground", "kampong", "plaaskamp"],
    "tourism": ["tourism", "tourist info", "activities", "attractions"],
    "restaurants": ["restaurant", "dining", "food", "cuisine", "eatery"],
    "activities": ["activities", "tours", "excursions", "adventures", "attractions"]
}

def detect_location_context(query: str) -> Optional[dict]:
    """Detect if query contains location context that needs geographic enhancement."""
    query_lower = query.lower()
    
    # Check for exact location matches
    for location, context in LOCATION_MAPPINGS.items():
        if location in query_lower:
            return context
    
    # Check for province mentions
    for country, data in GEO_DATABASE.items():
        if "provinces" in data:
            for province, province_data in data["provinces"].items():
                province_clean = province.replace("_", " ")
                if province_clean in query_lower:
                    return {"country": country, "province": province}
                
                # Check cities in province
                for city in province_data.get("cities", []):
                    city_clean = city.replace("_", " ")
                    if city_clean in query_lower:
                        return {"country": country, "province": province, "city": city}
    
    return None

def detect_search_category(query: str) -> Optional[str]:
    """Detect what category of search this is (accommodation, camping, etc.)."""
    query_lower = query.lower()
    
    for category, terms in CATEGORY_ENHANCEMENTS.items():
        if any(term in query_lower for term in terms):
            return category
    
    # Additional camping-specific detection
    camping_terms = ["camp", "caravan", "rv", "tent", "camping", "campsite"]
    if any(term in query_lower for term in camping_terms):
        return "camping"
        
    return None

def enhance_query_geographically(query: str, force_country: Optional[str] = None) -> List[str]:
    """
    Enhance a query with geographic context for better local results.
    Returns multiple query variations to try.
    """
    enhanced_queries = []
    original_query = query.strip()
    
    # Detect location and category context
    location_context = detect_location_context(original_query)
    search_category = detect_search_category(original_query)
    
    # Use forced country if provided
    if force_country and force_country in GEO_DATABASE:
        location_context = location_context or {}
        location_context["country"] = force_country
    
    # If no location context detected, return original
    if not location_context:
        enhanced_queries.append(original_query)
        return enhanced_queries
    
    country = location_context.get("country")
    province = location_context.get("province")
    city = location_context.get("city")
    
    # Get country data
    country_data = GEO_DATABASE.get(country, {})
    domain_suffix = country_data.get("domain_suffix", "co.za" if country == "south_africa" else "com")
    
    # Build enhanced queries with increasing specificity
    
    # 1. Original query with domain restriction
    enhanced_queries.append(f"{original_query} site:*.{domain_suffix}")
    
    # 2. Add country context if not already present
    if country == "south_africa" and "south africa" not in original_query.lower():
        enhanced_queries.append(f"{original_query} South Africa site:*.{domain_suffix}")
    
    # 3. Add province context if detected
    if province and province not in original_query.lower():
        province_clean = province.replace("_", " ").title()
        enhanced_queries.append(f"{original_query} {province_clean} site:*.{domain_suffix}")
    
    # 4. Add specific location terms if available
    if province in country_data.get("provinces", {}):
        province_data = country_data["provinces"][province]
        
        # Add regional terms
        regional_terms = province_data.get("terms", [])
        if regional_terms:
            term = regional_terms[0].replace("_", " ")
            enhanced_queries.append(f"{original_query} {term} site:*.{domain_suffix}")
    
    # 5. Add category-specific enhancements
    if search_category and search_category in CATEGORY_ENHANCEMENTS:
        category_terms = CATEGORY_ENHANCEMENTS[search_category]
        # Add the most relevant category term if not already present
        for term in category_terms:
            if term.lower() not in original_query.lower():
                enhanced_queries.append(f"{original_query} {term} site:*.{domain_suffix}")
                break
    
    # 6. Add nearby locations for broader results
    if "nearby" in location_context:
        nearby_places = location_context["nearby"][:2]  # Max 2 nearby places
        for place in nearby_places:
            place_clean = place.replace("_", " ")
            enhanced_queries.append(f"{original_query} {place_clean} site:*.{domain_suffix}")
    
    # 7. Add specific South African business directories
    if country == "south_africa":
        enhanced_queries.append(f"{original_query} site:sa-venues.com OR site:sacampsites.co.za")
        enhanced_queries.append(f"{original_query} site:places.co.za OR site:ananzi.co.za")
    
    # Limit to top 5 enhanced queries to avoid overwhelming
    return enhanced_queries[:5]

def add_pricing_context(query: str, country: str = "south_africa") -> str:
    """Add currency/pricing context to queries that seem to be asking for prices."""
    query_lower = query.lower()
    pricing_terms = ["price", "cost", "rate", "fee", "tariff", "charge"]
    
    if any(term in query_lower for term in pricing_terms):
        if country == "south_africa":
            return f"{query} rand ZAR"
    
    return query

def clean_query_for_cache(enhanced_query: str) -> str:
    """Clean enhanced query for cache key generation."""
    # Remove site: restrictions for cache key consistency
    clean = re.sub(r'\s+site:[^\s]+', '', enhanced_query)
    # Remove OR operators
    clean = re.sub(r'\s+OR\s+site:[^\s]+', '', clean)
    # Normalize whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean

def get_fallback_directories(location_context: dict, search_category: Optional[str] = None) -> List[str]:
    """Get fallback directory searches if main search fails."""
    country = location_context.get("country")
    directories = []
    
    if country == "south_africa":
        if search_category == "camping":
            directories = [
                "site:sa-venues.com caravan camping",
                "site:sacampsites.co.za", 
                "site:wheretostay.co.za caravan"
            ]
        elif search_category == "accommodation":
            directories = [
                "site:sa-venues.com accommodation",
                "site:safarinow.com",
                "site:places.co.za accommodation"
            ]
        else:
            directories = [
                "site:sa-venues.com",
                "site:places.co.za",
                "site:ananzi.co.za"
            ]
    
    return directories