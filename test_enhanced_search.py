"""Test script for enhanced geographic search functionality."""

import asyncio
import sys
sys.path.append('/tmp/searchclaw')

from api.services.geo_enhancer import (
    detect_location_context,
    enhance_query_geographically,
    detect_search_category,
    add_pricing_context
)

async def test_geo_enhancement():
    """Test geographic query enhancement functionality."""
    
    print("🧪 Testing Geographic Query Enhancement")
    print("=" * 50)
    
    # Test queries that should be enhanced
    test_queries = [
        "camping sites near Ceres Western Cape prices",
        "caravan parks Worcester accommodation",
        "best restaurants Hermanus",
        "activities Knysna Garden Route",
        "guest houses Stellenbosch",
        "camping chairs south africa prices",  # Commercial query
        "hotels cape town waterfront",
    ]
    
    for query in test_queries:
        print(f"\n📝 Original Query: '{query}'")
        
        # Detect context
        location_context = detect_location_context(query)
        search_category = detect_search_category(query)
        
        print(f"📍 Location Context: {location_context}")
        print(f"🔍 Search Category: {search_category}")
        
        # Enhance query
        enhanced_queries = enhance_query_geographically(query, force_country="south_africa")
        
        print(f"🚀 Enhanced Queries ({len(enhanced_queries)}):")
        for i, enhanced in enumerate(enhanced_queries, 1):
            print(f"  {i}. {enhanced}")
        
        # Test pricing context
        with_pricing = add_pricing_context(query, "south_africa")
        if with_pricing != query:
            print(f"💰 With Pricing Context: '{with_pricing}'")
        
        print("-" * 40)

async def test_location_detection():
    """Test location detection accuracy."""
    
    print("\n🌍 Testing Location Detection")
    print("=" * 50)
    
    location_tests = [
        ("Ceres accommodation", {"country": "south_africa", "province": "western_cape"}),
        ("Worcester caravan park", {"country": "south_africa", "province": "western_cape"}),
        ("Hermanus whale watching", {"country": "south_africa", "province": "western_cape"}),
        ("camping chairs", None),  # Should not detect location
        ("Johannesburg hotels", {"country": "south_africa", "province": "gauteng"}),
    ]
    
    for query, expected in location_tests:
        detected = detect_location_context(query)
        status = "✅ PASS" if detected == expected else "❌ FAIL"
        print(f"{status} '{query}' -> {detected}")
        if detected != expected:
            print(f"    Expected: {expected}")

async def test_category_detection():
    """Test search category detection."""
    
    print("\n🏷️ Testing Category Detection")
    print("=" * 50)
    
    category_tests = [
        ("camping sites near Ceres", "camping"),
        ("caravan parks Worcester", "camping"),
        ("guest house Stellenbosch", "accommodation"), 
        ("restaurants Hermanus", None),  # Should map to general
        ("activities Knysna", "activities"),
        ("camp chairs prices", "camping"),
    ]
    
    for query, expected in category_tests:
        detected = detect_search_category(query)
        status = "✅ PASS" if detected == expected else "❌ FAIL"
        print(f"{status} '{query}' -> '{detected}'")
        if detected != expected:
            print(f"    Expected: '{expected}'")

if __name__ == "__main__":
    asyncio.run(test_geo_enhancement())
    asyncio.run(test_location_detection())
    asyncio.run(test_category_detection())