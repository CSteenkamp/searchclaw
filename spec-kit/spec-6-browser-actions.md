# Spec 6 — Browser Actions Endpoint & Agent Endpoint

## Context
SearchClaw has an internal Playwright browser pool (`api/services/browser_pool.py`) used by extract, markdown, and screenshot endpoints. This spec exposes browser interaction as a first-class API and adds an autonomous agent endpoint.

---

## 6.1 — `/v1/browse` Endpoint (Interactive Browser Actions)

Let clients drive a headless browser session: navigate, click, type, scroll, wait, and extract. Essential for auth-gated pages, SPAs, and interactive content.

### API

```
POST /v1/browse
```

#### Request
```json
{
  "url": "https://example.com/login",
  "actions": [
    {"type": "wait", "selector": "#login-form", "timeout": 5000},
    {"type": "fill", "selector": "#email", "value": "user@example.com"},
    {"type": "fill", "selector": "#password", "value": "secret123"},
    {"type": "click", "selector": "#submit-btn"},
    {"type": "wait", "selector": ".dashboard", "timeout": 10000},
    {"type": "screenshot"},
    {"type": "extract", "selector": ".user-data", "format": "markdown"}
  ],
  "viewport": {"width": 1280, "height": 720},
  "user_agent": "optional custom UA",
  "proxy": false,
  "timeout": 30000
}
```

#### Action Types

| Action | Fields | Description |
|--------|--------|-------------|
| `navigate` | `url` | Navigate to URL |
| `wait` | `selector`, `timeout` | Wait for element to appear |
| `click` | `selector` | Click an element |
| `fill` | `selector`, `value` | Fill an input field |
| `type` | `selector`, `value`, `delay` | Type text with optional keystroke delay (ms) |
| `select` | `selector`, `value` | Select dropdown option |
| `scroll` | `direction` (up/down), `amount` (pixels) | Scroll the page |
| `press` | `key` | Press a keyboard key (Enter, Tab, Escape, etc.) |
| `screenshot` | `full_page` (bool), `selector` (optional) | Take screenshot (returns base64 PNG) |
| `extract` | `selector` (optional), `format` (markdown/html/text) | Extract content from page or element |
| `evaluate` | `expression` | Execute JavaScript expression, return result |

#### Response
```json
{
  "success": true,
  "url": "https://example.com/dashboard",
  "results": [
    {"action": "wait", "success": true},
    {"action": "fill", "success": true},
    {"action": "fill", "success": true},
    {"action": "click", "success": true},
    {"action": "wait", "success": true},
    {"action": "screenshot", "success": true, "data": "base64_png_data..."},
    {"action": "extract", "success": true, "content": "# User Dashboard\n\n- Name: John..."}
  ],
  "final_url": "https://example.com/dashboard",
  "credits_used": 2
}
```

#### Credit Cost
- Base: 1 credit per browse request
- With `proxy: true`: +1 credit (total 2)
- Each `extract` action within the request: +0 (included in base)
- Each `screenshot` action: +0 (included in base)
- Max 20 actions per request

### Implementation

#### `api/routers/browse.py` — NEW
- `POST /v1/browse` endpoint
- Auth + rate limit + credit reserve
- Validate actions list (max 20, valid types)
- Acquire browser from pool
- Execute actions sequentially
- Return results array
- Release browser back to pool

#### `api/services/browser_actions.py` — NEW
- `async def execute_actions(page: Page, actions: list[BrowseAction]) -> list[ActionResult]`
- Each action type maps to a Playwright method:
  - `navigate` → `page.goto(url)`
  - `wait` → `page.wait_for_selector(selector, timeout=timeout)`
  - `click` → `page.click(selector)`
  - `fill` → `page.fill(selector, value)`
  - `type` → `page.type(selector, value, delay=delay)`
  - `select` → `page.select_option(selector, value)`
  - `scroll` → `page.evaluate(f"window.scrollBy(0, {amount})")` or negative for up
  - `press` → `page.keyboard.press(key)`
  - `screenshot` → `page.screenshot(full_page=full_page)` or element screenshot
  - `extract` → get `page.content()`, clean with `html_cleaner`, convert to format
  - `evaluate` → `page.evaluate(expression)`
- If any action fails, include error in result but continue remaining actions (unless it's `wait` which blocks subsequent)
- Action-level timeout: 10s default per action

#### `api/models/browse.py` — NEW
- `BrowseAction` — discriminated union model for each action type
- `BrowseRequest` — url, actions list, viewport, user_agent, proxy, timeout
- `ActionResult` — action type, success, data/content/error
- `BrowseResponse` — success, url, results array, final_url, credits_used

### Tests — `api/tests/test_browse.py`
- Test action validation (max 20)
- Test each action type with mock page
- Test error handling (element not found)
- Test credit accounting with/without proxy
- Test screenshot returns base64 data

---

## 6.2 — `/v1/agent` Endpoint (Autonomous Data Gathering)

An autonomous endpoint that accepts a natural language prompt and optionally a schema, then searches, navigates, and extracts data without requiring URLs. Inspired by Firecrawl's `/agent`.

### API

```
POST /v1/agent
```

#### Request
```json
{
  "prompt": "Find the founding team of Stripe with their roles and LinkedIn profiles",
  "schema": {
    "type": "object",
    "properties": {
      "founders": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "name": {"type": "string"},
            "role": {"type": "string"},
            "linkedin": {"type": "string"}
          }
        }
      }
    }
  },
  "max_credits": 20,
  "max_sources": 5,
  "webhook_url": "https://myapp.com/webhook"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `prompt` | string | required | Natural language description of desired data |
| `schema` | object | null | JSON Schema for structured output |
| `urls` | list[str] | null | Optional seed URLs (if known) |
| `max_credits` | int | 10 | Maximum credits to spend (cap: 50) |
| `max_sources` | int | 5 | Max pages to extract from |
| `webhook_url` | string | null | Webhook for async delivery |
| `webhook_secret` | string | null | HMAC secret for webhook |

#### How it works (internal pipeline)
1. **Search phase**: Use the internal search service to find relevant URLs
   - Generate 1-3 search queries from the prompt using keyword extraction
   - Execute searches, collect top URLs
2. **Filter phase**: Score URLs by relevance to prompt (simple: title + snippet keyword matching)
3. **Extract phase**: For top `max_sources` URLs, run extraction
   - If `schema` provided: use LLM extraction with schema
   - If no schema: extract as markdown
4. **Merge phase**: Combine extractions into unified result
   - If schema: merge structured results, deduplicate
   - If no schema: concatenate markdown with source attribution
5. **Return** result with sources list

#### Response (sync if max_credits <= 10, async otherwise)
```json
{
  "success": true,
  "status": "completed",
  "data": {
    "founders": [
      {"name": "Patrick Collison", "role": "CEO", "linkedin": "..."},
      {"name": "John Collison", "role": "President", "linkedin": "..."}
    ]
  },
  "sources": [
    {"url": "https://stripe.com/about", "title": "About Stripe"},
    {"url": "https://en.wikipedia.org/wiki/Stripe,_Inc.", "title": "Stripe - Wikipedia"}
  ],
  "credits_used": 7,
  "steps": [
    {"phase": "search", "queries": ["Stripe founding team", "Stripe founders roles"], "results": 15},
    {"phase": "filter", "urls_selected": 3},
    {"phase": "extract", "pages_processed": 3, "pages_succeeded": 3},
    {"phase": "merge", "output_type": "structured"}
  ]
}
```

### Implementation

#### `api/routers/agent.py` — NEW
- `POST /v1/agent` endpoint
- Auth + rate limit
- If `max_credits <= 10` and no `webhook_url`: run synchronously
- Otherwise: create async job, return job ID, deliver via webhook

#### `api/services/agent_service.py` — NEW
- `async def run_agent(prompt, schema, urls, max_credits, max_sources) -> AgentResult`
- Orchestrates: search → filter → extract → merge
- Tracks credit usage, stops when `max_credits` reached
- Uses existing services: `searxng_client`, `extractor`, `llm_extractor`

#### `api/services/query_generator.py` — NEW
- `def generate_search_queries(prompt: str, max_queries: int = 3) -> list[str]`
- Simple keyword extraction + reformulation
- No LLM needed: use TF-IDF-style keyword extraction, generate variations
- Example: "Find Stripe founders" → ["Stripe founding team", "Stripe co-founders roles", "who founded Stripe"]

#### `api/models/agent.py` — NEW
- `AgentRequest`, `AgentStep`, `AgentSource`, `AgentResponse`

### Tests — `api/tests/test_agent.py`
- Test query generation from prompts
- Test URL filtering/scoring
- Test structured extraction merge
- Test credit cap enforcement
- Test async mode with webhook
- Test with and without schema

---

## Acceptance Criteria
- [ ] `POST /v1/browse` executes action sequences on headless browser
- [ ] All 11 action types work (navigate, wait, click, fill, type, select, scroll, press, screenshot, extract, evaluate)
- [ ] Browse actions are capped at 20 per request
- [ ] `POST /v1/agent` accepts natural language prompts and returns structured data
- [ ] Agent respects `max_credits` cap
- [ ] Agent supports both sync and async modes
- [ ] Agent includes step-by-step trace in response
- [ ] Webhook delivery works for async agent jobs
- [ ] All features have tests
