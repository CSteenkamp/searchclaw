# Spec 4 — Quick Wins: MCP Publish, llms.txt, OpenAPI, Webhooks

## Context
SearchClaw is a unified search + extract + crawl API at `api.searchclaw.dev`. The codebase is FastAPI with Redis, PostgreSQL, SearXNG, Playwright browser pool, and Celery workers. Repo: `/tmp/dataclaw`. All existing code uses the SearchClaw brand.

This spec covers four high-impact, low-effort features that unblock adoption in the AI agent ecosystem.

---

## 4.1 — Expose OpenAPI Spec

FastAPI auto-generates OpenAPI. Ensure it's accessible and well-structured.

### Requirements
- `GET /openapi.json` returns the full OpenAPI 3.1 spec (FastAPI default, just verify it's not disabled)
- `GET /docs` serves Swagger UI (FastAPI default)
- `GET /redoc` serves ReDoc (FastAPI default)
- Add proper metadata to `api/main.py`:
  ```python
  app = FastAPI(
      title="SearchClaw API",
      description="Search, Extract, Crawl — One API. The complete web data pipeline for AI agents.",
      version="1.0.0",
      terms_of_service="https://searchclaw.dev/terms",
      contact={"name": "SearchClaw Support", "email": "support@searchclaw.dev"},
      license_info={"name": "Proprietary"},
      servers=[
          {"url": "https://api.searchclaw.dev", "description": "Production"},
          {"url": "http://localhost:8000", "description": "Local development"},
      ],
  )
  ```
- All endpoints must have proper docstrings, request/response models with `Field(description=...)`, and example values
- Add `tags_metadata` for logical grouping: Search, Extract, Crawl, Pipeline, Auth, Billing, Health

### Files to modify
- `api/main.py` — add metadata, tags
- `api/routers/*.py` — verify all endpoints have proper docstrings and typed models

---

## 4.2 — llms.txt for AI Agent Discovery

`llms.txt` is a convention for AI agents to discover API documentation. Serve it at the root.

### Requirements
- Create `dashboard/llms.txt` with this structure:
  ```
  # SearchClaw API
  > Search, Extract, Crawl — One API for AI agents.
  
  ## Docs
  - [API Reference](https://api.searchclaw.dev/docs): Interactive API documentation
  - [OpenAPI Spec](https://api.searchclaw.dev/openapi.json): Machine-readable API spec
  
  ## Endpoints
  - POST /v1/search: Web search via SearXNG (1 credit)
  - POST /v1/search/news: News search (1 credit)
  - POST /v1/search/images: Image search (1 credit)
  - GET /v1/suggest: Autocomplete suggestions (1 credit)
  - POST /v1/extract: Schema-driven structured extraction from URL (1 credit)
  - POST /v1/markdown: Convert URL to clean markdown (1 credit)
  - POST /v1/screenshot: Capture URL screenshot (1 credit)
  - POST /v1/crawl: Async bulk crawl + extraction (1 credit/page)
  - GET /v1/jobs/{id}: Poll async job status
  - POST /v1/pipeline: Search + extract in one call (1 + 1/page credits)
  - POST /v1/map: Discover all URLs on a domain (1 credit)
  
  ## Auth
  - API key in header: `X-API-Key: sc_live_...`
  - Register: POST /v1/auth/register
  - Get key: POST /v1/auth/keys
  
  ## Pricing
  - Free: 1,000 credits/mo
  - Starter: $10/mo — 15,000 credits
  - Pro: $50/mo — 100,000 credits
  - Scale: $200/mo — 500,000 credits
  - All endpoints: 1 credit each (crawl: 1/page)
  ```
- Also create `dashboard/llms-full.txt` with expanded endpoint details (request/response schemas)
- Serve `GET /llms.txt` via a FastAPI route that returns the file with `text/plain` content type
- Serve `GET /llms-full.txt` similarly

### Files to create/modify
- `dashboard/llms.txt` — standard discovery file
- `dashboard/llms-full.txt` — expanded version
- `api/main.py` or `api/routers/health.py` — add routes to serve them

---

## 4.3 — Webhook Callbacks for Async Jobs

Currently `/v1/crawl` returns a job ID and clients must poll `/v1/jobs/{id}`. Add webhook support so results are POSTed to a client-specified URL on completion.

### Requirements

#### API Changes
- Add `webhook_url` (optional string, valid HTTPS URL) to the crawl request model
- Add `webhook_secret` (optional string) to the crawl request model — used for HMAC signature verification
- Store `webhook_url` and `webhook_secret` in the job record (Redis hash or PostgreSQL)

#### Webhook Delivery
- When a crawl job completes (success or failure), POST the result to `webhook_url`
- Request body: same as what `GET /v1/jobs/{id}` returns (full job status + results)
- Headers:
  ```
  Content-Type: application/json
  X-SearchClaw-Signature: sha256=<HMAC-SHA256 of body using webhook_secret>
  X-SearchClaw-Event: job.completed | job.failed
  X-SearchClaw-Job-Id: <job_id>
  User-Agent: SearchClaw-Webhook/1.0
  ```
- Retry policy: 3 attempts with exponential backoff (1s, 5s, 25s)
- Timeout: 10 seconds per attempt
- Log delivery status in the job record (`webhook_delivered`, `webhook_attempts`, `webhook_last_error`)

#### Implementation
- Create `api/services/webhook.py`:
  - `async def deliver_webhook(job_id: str, payload: dict, webhook_url: str, webhook_secret: str | None)`
  - Uses `httpx.AsyncClient` for delivery
  - HMAC signing with `hmac.new(secret, body, hashlib.sha256)`
  - Retry with backoff
- Modify `api/workers/crawl_worker.py`:
  - After job completion, check for webhook_url and call `deliver_webhook`
- Modify `api/routers/crawl.py`:
  - Accept `webhook_url` and `webhook_secret` in request
  - Pass through to job creation

#### Also add webhooks to pipeline endpoint
- `POST /v1/pipeline` should also accept `webhook_url` for async mode
- If `webhook_url` is provided and `extract_from > 3`, run asynchronously (return job ID, deliver via webhook)
- If no webhook and extract_from <= 3, run synchronously as before

### Files to create/modify
- `api/services/webhook.py` — NEW
- `api/workers/crawl_worker.py` — add webhook delivery after completion
- `api/routers/crawl.py` — accept webhook params
- `api/routers/pipeline.py` — accept webhook params, async mode
- `api/models/job.py` — add webhook fields

### Tests
- `api/tests/test_webhook.py` — test HMAC signing, retry logic, delivery
- Update `api/tests/test_crawl.py` — test webhook_url parameter acceptance
- Update `api/tests/test_pipeline.py` — test async pipeline mode

---

## 4.4 — Publish MCP Server to npm

The MCP server exists at `github.com/CSteenkamp/searchclaw-mcp`. It needs updating for the unified API (add extract/crawl/pipeline tools) and publishing to npm.

### Requirements
- Update the MCP server repo to include ALL SearchClaw endpoints as tools:
  - `search` — web search
  - `search_news` — news search
  - `search_images` — image search
  - `suggest` — autocomplete
  - `extract` — structured extraction from URL
  - `markdown` — URL to markdown
  - `screenshot` — URL to screenshot
  - `crawl` — async bulk crawl
  - `job_status` — check crawl job status
  - `pipeline` — search + extract combo
  - `map` — URL discovery (spec 5)
  - `usage` — check credit usage
- Package name: `searchclaw-mcp` on npm
- Executable: `npx searchclaw-mcp`
- Environment variable: `SEARCHCLAW_API_KEY`
- Default base URL: `https://api.searchclaw.dev`
- Override base URL: `SEARCHCLAW_BASE_URL`
- Add to the SearchClaw README: MCP server installation instructions
- Add `llms.txt` reference to MCP server

### Files
- This is in the separate `searchclaw-mcp` repo
- Update `src/index.ts` with new tools
- Update `package.json` with correct metadata
- `npm publish`

---

## Acceptance Criteria
- [ ] `GET /openapi.json` returns valid OpenAPI 3.1 with all endpoints documented
- [ ] `GET /llms.txt` returns plain text discovery file
- [ ] Crawl jobs with `webhook_url` deliver results via POST on completion
- [ ] Webhook includes HMAC signature when `webhook_secret` provided
- [ ] Webhook retries 3 times on failure
- [ ] MCP server updated with all tools and published to npm
- [ ] All new code has tests
