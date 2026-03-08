# SearchClaw

**Search, Extract, Crawl — One API for AI Agents**

Unified API that combines web search, structured data extraction, and crawling. One API key, one billing system, one dashboard.

```
Internet → Cloudflare Tunnel (SSL, CDN, DDoS)
                    ↓
         ┌──────────────────────────────────┐
         │  Unified API Gateway (FastAPI)    │
         │  - Single auth system (API keys)  │
         │  - Unified rate limiting          │
         │  - Unified usage/billing          │
         │  - All endpoints under /v1/       │
         └──────────┬───────────────────────┘
                    ↓
         ┌──────────────────────────────────┐
         │  Redis                            │
         │  - Cache (search + extraction)    │
         │  - Job queue (Celery broker)      │
         │  - Rate limit counters            │
         └──────────┬───────────────────────┘
                    ↓
    ┌───────────────┼───────────────────┐
    ↓               ↓                   ↓
┌────────┐   ┌───────────┐   ┌──────────────┐
│ SearXNG │   │ Playwright │   │ Celery       │
│ Pool    │   │ Browser    │   │ Workers      │
│ (search)│   │ Pool       │   │ (async crawl)│
└────────┘   └───────────┘   └──────────────┘
```

## Quick Start

```bash
# Clone and start services
git clone https://github.com/searchclaw/searchclaw.git
cd searchclaw
docker-compose up -d

# API is available at http://localhost:8000
# Dashboard at http://localhost:8000/
```

## API Endpoints

### Search
- `GET /v1/search` — Web search
- `GET /v1/news` — News search
- `GET /v1/images` — Image search
- `GET /v1/suggest` — Autocomplete
- `GET /v1/search/ai` — LLM-optimized search (2 credits)

### Extract
- `POST /v1/extract` — Structured data extraction
- `POST /v1/markdown` — URL to clean markdown
- `POST /v1/screenshot` — URL to screenshot

### Crawl
- `POST /v1/crawl` — Async bulk crawl + extraction
- `GET /v1/jobs/{id}` — Poll job status

### Pipeline (search + extract in one call)
- `POST /v1/pipeline` — Search the web, then extract structured data from top results

### Account
- `POST /v1/auth/register` — Create account
- `POST /v1/auth/login` — Get JWT
- `POST /v1/auth/keys` — Create/list/revoke API keys
- `GET /v1/usage` — Usage stats

## SDK Usage

### Python

```bash
pip install searchclaw
```

```python
from searchclaw import SearchClaw

sc = SearchClaw(api_key="sc_live_...")

# Search
results = sc.search("best restaurants Cape Town")

# Extract structured data
data = sc.extract("https://example.com", schema={"name": "str", "price": "float"})

# Crawl
job = sc.crawl("https://example.com/listings", schema={"name": "str"}, max_pages=5)
result = sc.wait_for_job(job["id"])

# Pipeline — search + extract in one call
pipeline = sc.pipeline(
    "best restaurants Cape Town",
    schema={"name": "str", "rating": "float", "address": "str"},
    extract_from=5,
)
for item in pipeline["results"]:
    print(item["extracted_data"])
```

### Async

```python
from searchclaw import AsyncSearchClaw

async with AsyncSearchClaw(api_key="sc_live_...") as sc:
    results = await sc.pipeline(
        "AI startups San Francisco",
        schema={"name": "str", "funding": "str"},
        extract_from=3,
    )
```

## Pricing

| Plan | Price | Credits/mo | Rate Limit |
|------|-------|-----------|------------|
| Free | $0 | 1,000 | 1 req/s |
| Starter | $10/mo | 15,000 | 5 req/s |
| Pro | $50/mo | 100,000 | 20 req/s |
| Scale | $200/mo | 500,000 | 50 req/s |
| Enterprise | Custom | Unlimited | 100 req/s |

**$1 per 1,000 credits.** Search = 1 credit, Extract = 1 credit, Crawl = 1 credit/page.

## Self-Hosting

### Docker Compose (Development)

```bash
cp .env.example .env
# Edit .env with your settings
docker-compose up -d
```

### Kubernetes (Production)

```bash
# Apply base manifests
kubectl apply -k k8s/base/

# Or use overlays
kubectl apply -k k8s/overlays/staging/
kubectl apply -k k8s/overlays/production/
```

### ArgoCD

```bash
kubectl apply -f argocd/project.yaml
kubectl apply -f argocd/application.yaml
```

## Development

```bash
# Install dependencies
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run tests
pytest api/tests/ -v

# Run API locally
uvicorn api.main:app --reload
```

## License

MIT
