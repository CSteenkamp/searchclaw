# SearchClaw Python SDK

Python client for the [SearchClaw](https://searchclaw.dev) search API — cheap, fast web search for AI agents.

## Installation

```bash
pip install searchclaw
```

## Quick Start

```python
from searchclaw import SearchClaw

client = SearchClaw(api_key="sc_live_xxx")

# Web search
results = client.search("kubernetes pod restart policy")
for r in results["results"]:
    print(r["title"], r["url"])

# News search
news = client.news("openai", freshness="week")

# Image search
images = client.images("cute cats", count=5)

# Autocomplete suggestions
suggestions = client.suggest("kube")

# AI-optimized search (2 credits, returns RAG-ready context)
ai = client.ai_search("what is kubernetes")
print(ai["context"])

# Check usage
usage = client.usage()
print(f"Credits remaining: {usage['credits_remaining']}")
```

## Async Usage

```python
import asyncio
from searchclaw import AsyncSearchClaw

async def main():
    async with AsyncSearchClaw(api_key="sc_live_xxx") as client:
        results = await client.search("python async tutorial")
        print(results)

asyncio.run(main())
```

## Error Handling

```python
from searchclaw import SearchClaw, AuthError, RateLimitError, SearchClawError

client = SearchClaw(api_key="sc_live_xxx")

try:
    results = client.search("test")
except AuthError:
    print("Invalid API key")
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after}s")
except SearchClawError as e:
    print(f"API error {e.status_code}: {e}")
```

## Configuration

```python
client = SearchClaw(
    api_key="sc_live_xxx",
    base_url="https://api.searchclaw.dev/v1",  # default
    timeout=30.0,                                # default, in seconds
)
```

## License

MIT
