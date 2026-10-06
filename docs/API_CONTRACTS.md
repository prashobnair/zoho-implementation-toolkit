# API contracts

Verified external endpoints per `specs/01` §4.6 (STD-C1/C2). Status values: `verified` | `unverified` | `drifted`.

All rows below were `unverified` until the 2026-10-03 live run: request/response shapes are hand-written
from the official Zoho API docs with fake IDs and `example.invalid`
addresses (synthetic cassettes under `tests/contract/cassettes/`). No
request has ever left this repo toward a Zoho domain except the
owner-approved read-only verification run recorded under
`docs/evidence/2026-10-03/`. Code may call `verified` endpoints directly;
`unverified` endpoints sit behind `--experimental` with a warning (STD-C2).
The `Status` column is tested against `VERIFIED_ENDPOINTS` in
`src/zohokit/connectors/zoho/client.py` (see `tests/contract/test_live_replay.py`).

| Product | Endpoint | Method | Scope | Fields used | Pagination | Doc URL | Verified on | Verified by | Status | History |
|---|---|---|---|---|---|---|---|---|---|---|
| CRM | `/crm/v8/org` | GET | `ZohoCRM.org.READ` | `org[0].id`, `org[0].company_name` (envelope `{"org": [...]}`) | none | https://www.zoho.com/crm/developer/docs/api/v8/get-org-data.html | 2026-10-03 | owner-approved live run 37120123276 (lead-reviewed) | `verified` | live run 2026-10-02: org envelope drift found (real reply is `{"org": [...]}`; synthetic cassette was flat). Live run 3: doctor read org without a token (no `ensure_fresh`) and mapped the 401 error body to drift; doctor + smoke now share one `read_org` and one authenticated client builder |
| CRM | `/crm/v8/settings/modules` | GET | `ZohoCRM.settings.READ` | `modules[].api_name`, `modules[].plural_label` (envelope `{"modules": [...]}`) | none | https://www.zoho.com/crm/developer/docs/api/v8/modules-api.html | 2026-10-03 | owner-approved live run 37120123276 (lead-reviewed) | `verified` | — |
| CRM | `/crm/v8/settings/fields` (`?module=Leads\|Contacts\|Deals`) | GET | `ZohoCRM.settings.READ` | `fields[].api_name`, `fields[].data_type` (envelope `{"fields": [...]}`) | none | https://www.zoho.com/crm/developer/docs/api/v8/field-meta.html | 2026-10-03 | owner-approved live run 37120123276 (lead-reviewed) | `verified` | — |
| CRM | `/crm/v8/Leads` | GET | `ZohoCRM.modules.READ` | `id`, `Created_Time`, `Last_Name` (sent as the mandatory v8 `fields` param) | `page`/`per_page` via `info.more_records`; `page_token` past the offset; HTTP 204 with an empty body = valid empty page (0 records) | https://www.zoho.com/crm/developer/docs/api/v8/get-records.html | 2026-10-03 | owner-approved live run 37120123276 (lead-reviewed) | `verified` | live run 3 2026-10-02: reads without `fields` got `400 REQUIRED_PARAM_MISSING` error bodies (surfaced as `data: missing` drift); now sent always, error bodies map to `ConnectorError` with the Zoho code only |
| CRM | `/crm/v8/Contacts` | GET | `ZohoCRM.modules.READ` | `id`, `Created_Time`, `Last_Name` (sent as the mandatory v8 `fields` param) | `page`/`per_page` via `info.more_records`; `page_token` past the offset; HTTP 204 with an empty body = valid empty page (0 records) | https://www.zoho.com/crm/developer/docs/api/v8/get-records.html | 2026-10-03 | owner-approved live run 37120123276 (lead-reviewed) | `verified` | live run 3 2026-10-02: see Leads row |
| CRM | `/crm/v8/Deals` | GET | `ZohoCRM.modules.READ` | `id`, `Created_Time`, `Deal_Name` (sent as the mandatory v8 `fields` param) | `page`/`per_page` via `info.more_records`; `page_token` past the offset; HTTP 204 with an empty body = valid empty page (0 records) | https://www.zoho.com/crm/developer/docs/api/v8/get-records.html | 2026-10-03 | owner-approved live run 37120123276 (lead-reviewed) | `verified` | live run 3 2026-10-02: see Leads row |
| CRM | `/crm/v8/users` | GET | `ZohoCRM.users.READ` | `users[].id`, `users[].email`, `users[].status` (envelope `{"users": [...], "info": {...}}`) | `page`/`per_page` via `info.more_records` | https://www.zoho.com/crm/developer/docs/api/v8/get-users.html | 2026-10-03 | owner-approved live run 37120123276 (lead-reviewed) | `verified` | — |
| CRM | `/crm/v8/{module}/search` (`?criteria=(Email:equals:…)`) | GET | `ZohoCRM.modules.READ` | `data[].id` (envelope `{"data": [...], "info": {...}}`, v8 record shape) | `page`/`per_page` via `info.more_records` | https://www.zoho.com/crm/developer/docs/api/v8/search-records.html | — | — | `unverified` | migration target dedupe only; `--experimental` required; synthetic cassette `tests/contract/cassettes/crm_search_contacts.json` |
| Accounts | `https://accounts.zoho.<tld>/oauth/v2/token` | POST | Self Client grant exchange only (separate auth transport) | `refresh_token`, `access_token`, `api_domain`, `expires_in` | none | https://www.zoho.com/accounts/protocol/oauth.html | — | — | `unverified` |

Multi-DC table (accounts + API domains per region) follows the official
guide: https://www.zoho.com/crm/developer/docs/api/multi-dc.html
