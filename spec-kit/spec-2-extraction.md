# Spec 2: Extraction — Browser Pool + Extract + Crawl + Markdown + Screenshot

Read PROJECT-SPEC.md for full context. Spec 1 is built (unified foundation with search + auth).

## Source Code Locations
- ScrapeClaw extraction code: `/tmp/scrapeclaw/`
- Current DataClaw (spec 1 built): `/tmp/dataclaw/`

## What to Build

Integrate ScrapeClaw's extraction capabilities into the unified DataClaw gateway.

### 1. Browser Pool Service
- Bring in from ScrapeClaw: `api/services/browser_pool.py`
- Adapt to use DataClaw's `Settings` (browser_pool_size, browser_timeout)
- Initialize in `api/main.py` lifespan (startup: launch browsers, shutdown: close)
- Expose pool status via health endpoint

### 2. Extraction Services
- Bring in from ScrapeClaw:
  - `api/services/extractor.py` — rule-based + LLM extraction pipeline
  - `api/services/html_cleaner.py` — HTML cleaning, readability
  - `api/services/llm_client.py` — GPT-4o-mini + Haiku fallback
- Adapt LLM client to use DataClaw's config (openai_api_key, anthropic_api_key, llm_model, llm_fallback_model)
- Wire cache through SearchClaw's existing `api/services/cache.py` (don't duplicate)

### 3. Extract Endpoint
- `api/routers/extract.py` — `POST /v1/extract`
- Accepts: `{ url, schema, prompt, cache }` 
- Uses SearchClaw's `get_api_key_user` for auth
- Uses SearchClaw's `check_rate_limit` + `reserve_credits` + `record_usage_to_db`
- Returns: structured JSON matching schema + meta (cached, credits_used, response_time_ms)
- Cost: 1 credit (+ LLM surcharge if applicable)

### 4. Markdown Endpoint
- `api/routers/markdown.py` — `POST /v1/markdown`
- Accepts: `{ url, include_images, include_links, main_content_only }`
- Render with Playwright, convert HTML → Markdown
- Auth + rate limit via SearchClaw middleware
- Cost: 1 credit

### 5. Screenshot Endpoint
- `api/routers/screenshot.py` — `POST /v1/screenshot`
- Accepts: `{ url, format, width, height, full_page, quality }`
- Render with Playwright, return base64 or binary
- Auth + rate limit via SearchClaw middleware
- Cost: 1 credit

### 6. Crawl Endpoint + Async Jobs
- `api/routers/crawl.py` — `POST /v1/crawl`
- Accepts: `{ url, schema, list_selector, pagination, max_items, timeout_ms }`
- Creates Celery task, returns job_id immediately
- Auth + rate limit via SearchClaw middleware

- `api/routers/jobs.py` — `GET /v1/jobs/{job_id}`
- Returns job status + results
- Statuses: queued, processing, completed, failed, partial

- `api/workers/__init__.py` — Celery app config (broker=Redis, backend=Redis)
- `api/workers/crawl_worker.py` — Celery task for async crawl + extraction
- `Dockerfile.worker` — runs Celery worker

### 7. Wire into Main App
- Update `api/main.py`:
  - Add browser pool to lifespan
  - Register extract, markdown, screenshot, crawl, jobs routers
  - Update health endpoint to check browser pool

### 8. Update docker-compose.yml
- Add `worker` service
- Ensure browser pool works in Docker (Playwright Chromium)

### 9. Tests
- All spec 1 tests must still pass
- New tests:
  - `api/tests/test_extract.py` — schema extraction, LLM fallback, caching
  - `api/tests/test_markdown.py` — HTML → Markdown conversion
  - `api/tests/test_screenshot.py` — screenshot generation
  - `api/tests/test_crawl.py` — job creation, status polling
  - `api/tests/test_jobs.py` — job lifecycle
- Verify unified auth works across search AND extract endpoints (same API key)

### 10. Git
- Commit: `feat: spec 2 - extraction, crawl, markdown, screenshot (from ScrapeClaw)`

## Constraints
- Use SearchClaw's auth/rate-limit/cache everywhere — do NOT duplicate middleware
- Browser pool is memory-heavy (~500MB per Chromium context) — respect pool_size
- Celery worker concurrency limited to 3 (browser memory)
- All async, type hints, docstrings
