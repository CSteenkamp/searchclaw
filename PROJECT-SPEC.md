# DataClaw — Unified Search + Scrape API for AI Agents

## Overview

Merge SearchClaw (web search) and ScrapeClaw (structured extraction) into a single, unified API. One API key, one billing system, one dashboard. The complete pipeline: **search → extract → crawl**.

**Companion products unified under one brand.** SearchClaw finds URLs, ScrapeClaw extracts structured data. DataClaw does both.

**Target customers:** AI agent builders, RAG pipelines, lead generation tools, price monitoring services, data enrichment platforms.

**Pricing:** $1/1,000 credits. Search = 1 credit, Extract = 1 credit, Crawl = 1 credit/page, Screenshot = 1 credit, Markdown = 1 credit.

---

## Architecture

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
│ 5-10x   │   │ (extract)  │   │              │
└────────┘   └───────────┘   └──────────────┘
    ↓
 Google / Bing / DDG / Brave / etc.
```

### PostgreSQL Schema

Unified user/key/usage model. Same tables serve all endpoints.

```sql
users (id, email, password_hash, name, plan, stripe_customer_id, created_at, updated_at, is_active)
api_keys (id, user_id, key_prefix, key_hash, name, is_active, created_at, last_used_at)
usage_records (id, api_key_id, endpoint, credits_used, cached, response_time_ms, created_at)
```

Plans:
- free: 1,000 credits/mo, 1 req/s
- starter: 15,000 credits/mo, 5 req/s — $10/mo
- pro: 100,000 credits/mo, 20 req/s — $50/mo
- scale: 500,000 credits/mo, 50 req/s — $200/mo
- enterprise: unlimited, 100 req/s — custom

API key prefix: `dc_live_` / `dc_test_`

---

## Unified Endpoints

### Search (from SearchClaw)
- `POST /v1/search` — web search (SearXNG)
- `POST /v1/search/news` — news search
- `POST /v1/search/images` — image search
- `GET /v1/suggest` — autocomplete suggestions

### Extract (from ScrapeClaw)
- `POST /v1/extract` — single page, schema-driven structured extraction
- `POST /v1/markdown` — URL → clean markdown
- `POST /v1/screenshot` — URL → screenshot (PNG/JPEG)

### Crawl (from ScrapeClaw)
- `POST /v1/crawl` — async bulk crawl + extraction
- `GET /v1/jobs/{id}` — poll async job status

### Account
- `POST /v1/auth/register` — create account
- `POST /v1/auth/login` — get JWT
- `POST /v1/auth/keys` — create API key
- `GET /v1/auth/keys` — list API keys
- `DELETE /v1/auth/keys/{id}` — revoke key
- `GET /v1/usage` — usage stats
- `GET /v1/usage/history` — detailed usage history

### Pipeline (NEW — the killer feature)
- `POST /v1/pipeline` — search + extract in one call:
  ```json
  {
    "query": "best restaurants in Cape Town",
    "schema": {"name": "str", "rating": "float", "address": "str", "phone": "str"},
    "max_results": 10,
    "extract_from": "top_5"
  }
  ```
  Internally: search → take top N URLs → extract structured data from each → return unified result.

### Health
- `GET /health` — API health
- `GET /health/ready` — readiness (DB + Redis + SearXNG + Browser pool)

---

## Source Integration Strategy

The unified codebase takes **SearchClaw as the base** (more mature auth, billing, Stripe, Prometheus metrics) and integrates ScrapeClaw's extraction/crawl capabilities:

### From SearchClaw (keep as-is, adapt naming):
- `api/config.py` — extend with browser/extraction settings
- `api/middleware/auth.py` — keep HMAC-SHA256 auth (more robust than ScrapeClaw's bcrypt approach)
- `api/middleware/rate_limit.py` — keep atomic credit reserve/release pattern
- `api/middleware/metrics.py` — extend with extraction metrics
- `api/models/user.py` — keep (already has Stripe, plans, usage records)
- `api/services/database.py` — keep
- `api/services/cache.py` — keep (more feature-complete)
- `api/services/searxng_client.py` — keep
- `api/services/query_normalizer.py` — keep
- `api/routers/search.py` — keep
- `api/routers/auth.py` — keep (has register, login, key CRUD)
- `api/routers/billing.py` — keep (Stripe integration)
- `api/routers/health.py` — extend
- `api/tasks/billing_sync.py` — keep
- `migrations/` — extend with new tables
- `sdk/python/` — extend client
- `scripts/` — keep provisioning/seed scripts

### From ScrapeClaw (integrate):
- `api/services/browser_pool.py` — bring in, adapt to shared config
- `api/services/extractor.py` — bring in (rule-based + LLM extraction pipeline)
- `api/services/html_cleaner.py` — bring in
- `api/services/llm_client.py` — bring in (GPT-4o-mini + Haiku fallback)
- `api/routers/extract.py` — bring in, adapt auth to SearchClaw's middleware
- `api/routers/markdown.py` — bring in, adapt auth
- `api/routers/screenshot.py` — bring in, adapt auth
- `api/routers/crawl.py` — bring in, adapt auth
- `api/routers/jobs.py` — bring in
- `api/workers/` — bring in Celery crawl workers
- `Dockerfile.worker` — bring in

### New:
- `api/routers/pipeline.py` — NEW search+extract combo endpoint
- `dashboard/` — unified dashboard (merge both landing pages)
- `k8s/` — unified K8s manifests (add SearXNG + browser pool + workers)

---

## K8s Deployment

Single namespace: `dataclaw`

Deployments:
- `api` — FastAPI gateway (2-3 replicas, HPA)
- `searxng` — SearXNG pool (5-10 replicas)
- `worker` — Celery workers (2-3 replicas, memory-constrained)
- `cloudflared` — Cloudflare tunnel

StatefulSets:
- `redis` — cache + job broker
- `postgres` — user/key/usage storage

---

## Docker Compose (local dev)

```yaml
services:
  api:
    build: .
    ports: ["8000:8000"]
    depends_on: [redis, postgres, searxng]
  worker:
    build:
      dockerfile: Dockerfile.worker
    depends_on: [redis, postgres]
  searxng:
    image: searxng/searxng:latest
    ports: ["8888:8080"]
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
  postgres:
    image: postgres:16-alpine
    ports: ["5432:5432"]
    environment:
      POSTGRES_DB: dataclaw
      POSTGRES_USER: dataclaw
      POSTGRES_PASSWORD: dataclaw
```

---

## Testing

All existing tests from both projects must pass. New tests for:
- Pipeline endpoint (search → extract combo)
- Unified auth across all endpoint types
- Credit accounting across search + extract + crawl
- Health endpoint checking all backends
- Dashboard pages

---

## Branding

- Name: **DataClaw**
- Domain: dataclaw.dev (or keep searchclaw.dev and add scrape routes)
- Tagline: "Search, Extract, Crawl — One API"
- API key prefix: `dc_live_` / `dc_test_`
