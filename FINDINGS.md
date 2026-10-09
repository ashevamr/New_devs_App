# Findings & Fixes

| # | Symptom | Root cause | Fix |
|---|---------|-----------|-----|
| 1 | **Ocean Rentals sees another company's revenue on refresh** | `services/cache.py` cached under `revenue:{property_id}`. `prop-001` exists for both tenants, so whoever populated the cache first leaked their totals to the other tenant for 5 min. | Cache key is now `revenue:{tenant_id}:{property_id}`. |
| 2 | **Sunset's totals don't match their records** | `DatabasePool` read non-existent `supabase_db_*` settings and passed `QueuePool` to an async engine, so init always failed; `get_session` was `async` but used as a context manager. The exception was swallowed and `calculate_total_revenue` returned **hardcoded mock totals** (identical for every tenant). `sqlalchemy[asyncio]`/`greenlet` was also missing from requirements. | Engine built from `DATABASE_URL`, default async pool, sync `get_session`, shared pool. Mock fallback removed: failures now return HTTP 503 instead of fake numbers. |
| 3 | **March totals off** (timezones) | Monthly revenue used naive UTC month boundaries, ignored `tenant_id`, and returned a placeholder `0`. `res-tz-1` checks in `2024-02-29 23:30 UTC` = **`2024-03-01 00:30` Paris** → belongs to March. | Real query, filtered by tenant, month boundaries computed in the **property's timezone** (`pytz`) and compared to the `TIMESTAMPTZ` column. Exposed via `?month=&year=` on `/dashboard/summary` and a month picker in the UI. |
| 4 | **Totals off by a few cents** | Amounts are `NUMERIC(10,3)`; the sum was converted to `float` and rounded on the client. | Rounded server-side with `Decimal.quantize(0.01, ROUND_HALF_UP)` before serialisation. |
| 5 | **Other clients' property names visible** | `Dashboard.tsx` hardcoded all 5 properties for every user. | New tenant-scoped `GET /api/v1/dashboard/properties`; dropdown is loaded from it. |
| 6 | **Unknown users silently get tenant-a data** | `TenantResolver.resolve_tenant_id` defaulted to `"tenant-a"` and ignored the tenant in the signed JWT. | Tenant taken from verified token claims first; no default tenant; endpoint returns 403 without a tenant. |

Also removed: the client-sent `X-Simulated-Tenant: candidate` header (tenant must come from the token only) and a hardcoded "+12%" trend badge that displayed a fabricated figure to clients.

## Verification (seed data)

| User | Property | Total | March 2024 | Feb 2024 |
|------|----------|-------|------------|----------|
| Sunset | prop-001 Beach House Alpha | 2,250.00 (4) | 2,250.00 | 0.00 (res-tz-1 counted in March) |
| Sunset | prop-002 / prop-003 | 4,975.50 / 6,100.50 | same | – |
| Ocean | prop-001 Mountain Lodge Beta | 0.00 — even right after Sunset warmed the cache | 0.00 | – |
| Ocean | prop-004 / prop-005 | 1,776.50 / 3,256.00 | same | – |
| Sunset | requests Ocean's prop-004 | 0.00 (no access to other tenant's rows) | | |
