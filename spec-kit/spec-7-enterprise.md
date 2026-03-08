# Spec 7 — Enterprise Features: Proxy Rotation, Teams, Security & Polish

## Context
SearchClaw API at `api.searchclaw.dev`. This spec covers features that enterprise buyers require for procurement approval and production deployments.

---

## 7.1 — Proxy Rotation for Anti-Bot Bypass

Many target websites block datacenter IPs. Add proxy support to the browser pool and HTTP fetching layer.

### Architecture

```
SearchClaw API
    ├── Direct fetch (default, free)
    ├── Datacenter proxy (included in paid plans)
    └── Residential proxy (premium, +1 credit)
```

### Implementation

#### `api/services/proxy_manager.py` — NEW
- `ProxyManager` class that manages a pool of proxy configurations
- Proxy sources (configurable via env vars):
  ```
  PROXY_DATACENTER_URL=socks5://user:pass@dc-proxy.example.com:1080
  PROXY_RESIDENTIAL_URL=http://user:pass@res-proxy.example.com:8080
  PROXY_RESIDENTIAL_ROTATE=true
  ```
- Methods:
  - `get_proxy(tier: str = "datacenter") -> ProxyConfig | None`
  - `report_failure(proxy: ProxyConfig)` — track failure rate, rotate on threshold
  - `get_stats() -> dict` — proxy health metrics
- Tier selection:
  - `"none"` — direct connection (default for free plan)
  - `"datacenter"` — datacenter proxy (default for paid plans)
  - `"residential"` — residential rotating proxy (explicit opt-in, +1 credit)

#### Modify `api/services/browser_pool.py`
- Accept `proxy` parameter when launching browser contexts
- `await browser.new_context(proxy={"server": proxy_url})` 
- Pass proxy through from endpoint handlers

#### Modify `api/services/searxng_client.py`
- Add proxy support for outbound SearXNG requests (optional, for when SearXNG is self-hosted but needs external access via proxy)

#### Add `proxy` parameter to endpoints
- `POST /v1/extract` — `proxy: "none" | "datacenter" | "residential"` (default: auto based on plan)
- `POST /v1/markdown` — same
- `POST /v1/screenshot` — same
- `POST /v1/browse` — same (already has `proxy: bool`, change to tier string)
- `POST /v1/crawl` — same
- Credit adjustment: `residential` adds 1 credit per request/page

#### Auto-retry with proxy escalation
- If a direct fetch gets blocked (403, Cloudflare challenge detected), automatically retry with datacenter proxy
- If datacenter proxy fails, offer residential in error response: `"hint": "Try with proxy: residential for better coverage"`
- Track success rates per domain in Redis for smart routing

### Config
Add to `api/config.py`:
```python
proxy_datacenter_url: str = ""
proxy_residential_url: str = ""
proxy_auto_escalate: bool = True  # Auto-retry with proxy on 403
```

### Tests — `api/tests/test_proxy.py`
- Test proxy selection by tier
- Test auto-escalation on 403
- Test credit adjustment for residential
- Test failure tracking and rotation

---

## 7.2 — Team / Organisation Accounts

Enterprises need multiple users under one billing account with separate API keys for dev/staging/prod.

### Database Changes

#### New tables
```sql
CREATE TABLE organisations (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(100) UNIQUE NOT NULL,
    plan VARCHAR(50) DEFAULT 'free',
    stripe_customer_id VARCHAR(255) DEFAULT '',
    monthly_credits INTEGER DEFAULT 1000,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE org_members (
    id SERIAL PRIMARY KEY,
    org_id INTEGER REFERENCES organisations(id) ON DELETE CASCADE,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    role VARCHAR(50) DEFAULT 'member',  -- owner, admin, member
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(org_id, user_id)
);
```

#### Modify `api_keys` table
```sql
ALTER TABLE api_keys ADD COLUMN org_id INTEGER REFERENCES organisations(id);
ALTER TABLE api_keys ADD COLUMN environment VARCHAR(20) DEFAULT 'production';
-- environment: 'production', 'staging', 'development', 'test'
ALTER TABLE api_keys ADD COLUMN description TEXT DEFAULT '';
```

### API Endpoints

#### `POST /v1/orgs` — Create organisation
```json
{"name": "Acme Corp", "slug": "acme"}
```
- Creator becomes `owner`

#### `GET /v1/orgs/{slug}` — Get org details
- Members list, plan, usage summary

#### `POST /v1/orgs/{slug}/members` — Invite member
```json
{"email": "dev@acme.com", "role": "member"}
```

#### `DELETE /v1/orgs/{slug}/members/{user_id}` — Remove member

#### `POST /v1/orgs/{slug}/keys` — Create org API key
```json
{"name": "Production API", "environment": "production"}
```

#### `GET /v1/orgs/{slug}/keys` — List org API keys

#### `GET /v1/orgs/{slug}/usage` — Org usage dashboard
- Breakdown by API key, by endpoint, by day
- Exportable as CSV: `GET /v1/orgs/{slug}/usage?format=csv`

### Auth Changes
- When authenticating with an org API key, credit limits and rate limits come from the org's plan, not the individual user's plan
- Usage records are tagged with both `api_key_id` and `org_id`
- Billing goes to the org's Stripe customer

### Implementation

#### `api/models/org.py` — NEW
- `Organisation`, `OrgMember` SQLAlchemy models
- Modify `APIKey` model to include `org_id` and `environment`

#### `api/routers/orgs.py` — NEW
- All org management endpoints
- Permission checks: only owner/admin can manage members and keys

#### Modify `api/middleware/auth.py`
- When resolving API key, check if it has `org_id`
- If org key: load plan/limits from organisation, not user
- Include `org_id` in `user_info` dict

#### Modify `api/middleware/rate_limit.py`
- Org keys share rate limits at the org level (not per-key)
- Credit pool is shared across all org keys

#### Migration
- `migrations/versions/003_organisations.py` — new tables + api_keys changes

### Tests — `api/tests/test_orgs.py`
- Test org creation and member management
- Test org API key creation with environment tags
- Test shared credit pool across org keys
- Test permission checks (owner vs member)
- Test usage export CSV

---

## 7.3 — Security & Compliance Page

Not a code feature — this is content for the dashboard/landing page and API behaviour.

### Zero Data Retention Mode

#### API Changes
- Add `X-Data-Retention: none` request header support
- When set, SearchClaw:
  - Does NOT cache the request/response in Redis
  - Does NOT log the query content in usage records (only logs endpoint + credits + timestamp)
  - Returns `X-Data-Retention: none` in response headers
- Document in API docs and llms.txt

#### Implementation
- Modify `api/middleware/auth.py` to detect header and pass `data_retention=False` in context
- Modify `api/services/cache.py` to skip caching when `data_retention=False`
- Modify `api/middleware/rate_limit.py` `record_usage_to_db` to omit query content

### Security Page — `dashboard/security.html`
Create a security page covering:
- **Infrastructure**: Cloudflare Tunnel (no exposed ports), encrypted at rest (PostgreSQL), encrypted in transit (TLS everywhere)
- **Authentication**: HMAC-SHA256 API key verification, bcrypt password hashing
- **Data handling**: Optional zero data retention, no query logging by default, Redis cache auto-expires
- **Compliance**: GDPR-ready (data deletion on account closure), no third-party data sharing
- **Responsible disclosure**: security@searchclaw.dev
- **SOC 2**: "In progress" (or "Planned" — even the statement shows maturity)

### Privacy Policy — `dashboard/privacy.html`
Basic privacy policy covering:
- What data is collected (email, usage metrics)
- How it's used (billing, service improvement)
- Data retention periods
- User rights (deletion, export)
- Third-party services (Stripe for billing)

### Terms of Service — `dashboard/terms.html`
Basic ToS covering:
- Acceptable use (no illegal scraping, rate limit compliance)
- Service availability (best-effort SLA)
- Liability limitations
- Account termination conditions

---

## 7.4 — Usage Dashboard with Export

Enhance the existing usage endpoint for enterprise reporting needs.

### API Enhancements

#### `GET /v1/usage/history` — Enhanced
Add query parameters:
```
GET /v1/usage/history?from=2026-03-01&to=2026-03-08&group_by=day&endpoint=search&format=json
```

| Param | Type | Description |
|-------|------|-------------|
| `from` | date | Start date (ISO 8601) |
| `to` | date | End date (ISO 8601) |
| `group_by` | string | `hour`, `day`, `week`, `month` |
| `endpoint` | string | Filter by endpoint (search, extract, crawl, etc.) |
| `api_key_id` | int | Filter by specific API key (org accounts) |
| `format` | string | `json` (default) or `csv` |

#### Response (grouped)
```json
{
  "usage": [
    {
      "period": "2026-03-07",
      "total_credits": 1523,
      "requests": 1490,
      "by_endpoint": {
        "search": {"credits": 800, "requests": 800, "cached_pct": 23.5},
        "extract": {"credits": 500, "requests": 500, "cached_pct": 12.0},
        "crawl": {"credits": 200, "requests": 45, "cached_pct": 0},
        "pipeline": {"credits": 23, "requests": 5, "cached_pct": 0}
      },
      "avg_response_ms": 342
    }
  ],
  "total_credits": 1523,
  "total_requests": 1490,
  "period": {"from": "2026-03-07", "to": "2026-03-07"}
}
```

#### CSV Export
When `format=csv`:
```csv
date,endpoint,credits,requests,cached_pct,avg_response_ms
2026-03-07,search,800,800,23.5,210
2026-03-07,extract,500,500,12.0,580
```

### Implementation

#### Modify `api/routers/auth.py` or create `api/routers/usage.py`
- Enhanced usage history with grouping and filtering
- CSV response using `StreamingResponse` with `text/csv` content type

### Tests
- Test date range filtering
- Test group_by aggregation
- Test CSV export format
- Test endpoint filtering

---

## Acceptance Criteria
- [ ] Proxy rotation works with datacenter and residential tiers
- [ ] Auto-escalation retries with proxy on 403/bot-block
- [ ] Residential proxy adds 1 credit per request
- [ ] Organisation accounts with shared billing and credit pools
- [ ] Org members have role-based permissions (owner/admin/member)
- [ ] Org API keys can be tagged by environment
- [ ] Usage export works in JSON and CSV formats
- [ ] `X-Data-Retention: none` header skips caching and query logging
- [ ] Security, privacy, and terms pages exist in dashboard
- [ ] Database migration for organisations table
- [ ] All features have tests
