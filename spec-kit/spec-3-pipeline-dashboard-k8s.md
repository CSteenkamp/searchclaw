# Spec 3: Pipeline Endpoint + Dashboard + K8s + CI/CD

Read PROJECT-SPEC.md for full context. Specs 1-2 are built.

## What to Build

### 1. Pipeline Endpoint (NEW — the killer feature)
- `api/routers/pipeline.py` — `POST /v1/pipeline`
- Accepts:
  ```json
  {
    "query": "best restaurants in Cape Town",
    "schema": {"name": "str", "rating": "float", "address": "str", "phone": "str"},
    "max_results": 10,
    "extract_from": 5,
    "search_params": {
      "engines": ["google", "bing"],
      "language": "en",
      "region": "ZA"
    }
  }
  ```
- Flow:
  1. Execute search via SearXNG (same as /v1/search internally)
  2. Take top `extract_from` result URLs
  3. Extract structured data from each URL using browser pool + extractor
  4. Return unified result: `{ query, results: [{url, title, extracted_data}], meta: {search_credits, extract_credits, total_credits, response_time_ms} }`
- Cost: 1 credit for search + 1 credit per extraction
- Timeout: configurable, default 30s total
- Concurrency: extract URLs in parallel (asyncio.gather with semaphore)
- Auth + rate limit via existing middleware
- If extraction fails for a URL, include it with `extracted_data: null` and `error: "reason"`

### 2. Unified Dashboard
- `dashboard/index.html` — landing page
  - SearchClaw branding: "Search, Extract, Crawl — One API"
  - Feature sections: Search, Extract, Crawl, Pipeline
  - Pricing table (free/starter/pro/scale)
  - Code examples showing the pipeline flow
  - "Get Started" → register
  - Clean, modern design (Tailwind CSS via CDN)

- `dashboard/docs.html` — interactive API documentation
  - All endpoints documented with request/response examples
  - Try-it-out playground for each endpoint
  - Authentication guide
  - SDK installation

- `dashboard/dashboard.html` — usage dashboard (authenticated)
  - API key management (create, revoke, copy)
  - Usage charts (credits used by endpoint: search vs extract vs crawl)
  - Current plan + upgrade options
  - Recent API calls log

- `dashboard/playground.html` — interactive API playground
  - Tab for each endpoint type (Search, Extract, Crawl, Pipeline)
  - Enter params, execute, see results
  - Show credits used per request

- Serve static files from FastAPI: `app.mount("/", StaticFiles(directory="dashboard"), name="dashboard")`

### 3. Python SDK
- `sdk/python/searchclaw/__init__.py`
- `sdk/python/searchclaw/client.py`
- Unified client:
  ```python
  from searchclaw import SearchClaw
  
  sc = SearchClaw(api_key="sc_live_...")
  
  # Search
  results = sc.search("best restaurants Cape Town")
  
  # Extract
  data = sc.extract("https://example.com", schema={"name": "str", "price": "float"})
  
  # Crawl
  job = sc.crawl("https://example.com/listings", schema={...}, max_pages=5)
  result = sc.wait_for_job(job.id)
  
  # Pipeline (search + extract in one call)
  pipeline = sc.pipeline("best restaurants Cape Town", schema={"name": "str", "rating": "float"}, extract_from=5)
  ```
- Async support via `SearchClawAsync`

### 4. Kubernetes Manifests
- `k8s/base/` — Kustomize base
  - `namespace.yaml` — searchclaw namespace
  - `api-deployment.yaml` — FastAPI (2 replicas, HPA)
  - `api-service.yaml` — ClusterIP
  - `api-hpa.yaml` — autoscale on CPU
  - `worker-deployment.yaml` — Celery workers (2 replicas)
  - `searxng-deployment.yaml` — SearXNG pool (5 replicas)
  - `searxng-service.yaml` — ClusterIP
  - `redis-statefulset.yaml` — Redis with PVC
  - `redis-service.yaml`
  - `postgres-statefulset.yaml` — PostgreSQL with PVC
  - `postgres-service.yaml`
  - `cloudflared-deployment.yaml` — Cloudflare tunnel
  - `configmap.yaml` — shared config
  - `kustomization.yaml`

- `k8s/overlays/staging/` — staging overrides (1 replica each, smaller resources)
- `k8s/overlays/production/` — production overrides (higher replicas, anti-affinity, secrets)

### 5. ArgoCD
- `argocd/application.yaml` — auto-sync, self-heal, prune
- `argocd/project.yaml` — searchclaw project

### 6. CI/CD
- `.github/workflows/ci.yaml`:
  - Lint (ruff), test (pytest), build Docker images, push to GHCR
  - Auto version bump on main merge
- `.github/workflows/release.yaml`:
  - Triggered on v* tags
  - Build + push release images
- `.github/dependabot.yml` — weekly updates

### 7. README.md
- Project overview with architecture diagram
- Quick start (docker-compose)
- API documentation summary
- Self-hosting guide
- SDK usage examples

### 8. Tests
- All specs 1-2 tests must still pass
- New tests:
  - `api/tests/test_pipeline.py` — search+extract combo, partial failures, credit accounting
  - `api/tests/test_dashboard.py` — dashboard pages serve correctly
  - `api/tests/test_k8s_manifests.py` — YAML validity, required fields
- Verify end-to-end: pipeline uses search credits + extract credits correctly

### 9. Git
- Commit: `feat: spec 3 - pipeline endpoint, dashboard, SDK, K8s, CI/CD`
- Push to origin main

## Constraints
- Pipeline endpoint must handle partial failures gracefully (some URLs may fail to extract)
- Dashboard must work without JavaScript frameworks (vanilla JS + Tailwind CDN)
- K8s manifests must include resource limits for browser-heavy worker pods
- SDK must be installable via pip (include setup.py / pyproject.toml)
- All async, type hints, docstrings
