# Spec 1: Foundation — Unified Gateway + Search + Auth

Read PROJECT-SPEC.md for full context. This is a merge of two existing codebases.

## Source Code Locations
- SearchClaw: `/tmp/searchclaw/` (base — more mature auth, billing, metrics)
- ScrapeClaw: `/tmp/scrapeclaw/` (extraction capabilities to integrate)

## What to Build

Take SearchClaw as the foundation and create the unified SearchClaw project.

### 1. Project Skeleton
- Copy SearchClaw's full project structure as the starting point
- Rename all references from "SearchClaw" to "SearchClaw"
- Update API key prefix from `sc_` to `dc_` in auth middleware and key generation
- Update `api/config.py`:
  - Rename app_name to "SearchClaw"
  - Add browser pool settings: `browser_pool_size: int = 3`, `browser_timeout: int = 30000`
  - Add LLM settings: `openai_api_key: str = ""`, `anthropic_api_key: str = ""`, `llm_model: str = "gpt-4o-mini"`, `llm_fallback_model: str = "claude-3-haiku-20240307"`
  - Add extraction cache TTL: `cache_ttl_extract: int = 3600`
  - Update CORS origins to include searchclaw.dev
- Update `requirements.txt`: merge both projects' dependencies (keep SearchClaw's + add playwright, html2text, beautifulsoup4, lxml, openai, anthropic, celery[redis])
- Create `Dockerfile` — multi-stage build for API
- Create `Dockerfile.worker` — same base, runs Celery
- Create unified `docker-compose.yml` with: api, worker, searxng, redis, postgres

### 2. Search Endpoints (from SearchClaw)
- Keep all existing search routers and services as-is:
  - `api/routers/search.py` — `/v1/search`, `/v1/search/news`, `/v1/search/images`, `/v1/suggest`
  - `api/services/searxng_client.py`
  - `api/services/query_normalizer.py`
  - `api/services/cache.py`

### 3. Auth + Billing (from SearchClaw)
- Keep SearchClaw's auth system (HMAC-SHA256, more robust):
  - `api/middleware/auth.py`
  - `api/middleware/rate_limit.py`
  - `api/middleware/metrics.py`
  - `api/routers/auth.py` (register, login, key CRUD)
  - `api/routers/billing.py` (Stripe)
  - `api/models/user.py` (User, APIKey, UsageRecord, PLAN_LIMITS)
- Update key prefix to `sc_live_` / `sc_test_`
- Keep all existing migrations, update naming

### 4. Health Endpoint
- Extend `api/routers/health.py` to check:
  - Redis connectivity
  - PostgreSQL connectivity
  - SearXNG availability
  - Browser pool status (placeholder for now — will be wired in spec 2)

### 5. Main App
- Update `api/main.py`:
  - Include all search routers
  - Lifespan: init DB, Redis, SearXNG client
  - CORS, error handlers
  - Placeholder for browser pool init (spec 2)
  - Placeholder for worker registration (spec 2)

### 6. Tests
- All SearchClaw tests must pass with the renamed project
- Test API key prefix change (dc_ instead of sc_)
- Test health endpoint
- Test search endpoints still work

### 7. Git
- Initialize repo, add .gitignore
- Commit: `feat: spec 1 - unified foundation, search, auth (from SearchClaw base)`
- Add remote: `git remote add origin https://github.com/CSteenkamp/searchclaw.git` (create if needed, or just commit locally)

## Constraints
- Do NOT bring in ScrapeClaw code yet (that's spec 2)
- SearchClaw's auth/billing/metrics are the source of truth
- All async, type hints, docstrings
- Python 3.12+
