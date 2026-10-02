# API contracts

Verified external endpoints per `specs/01` §4.6 (STD-C1/C2). Status values: `verified` | `unverified` | `drifted`.

All rows below are `unverified`: request/response shapes are hand-written
from the official Zoho API docs with fake IDs and `example.invalid`
addresses (synthetic cassettes under `tests/contract/cassettes/`). No
request has ever left this repo toward a Zoho domain. Code may call only
`verified` endpoints directly; `unverified` endpoints sit behind
`--experimental` with a warning (STD-C2).

| Product | Endpoint | Method | Scope | Fields used | Pagination | Doc URL | Verified on | Verified by | Status |
|---|---|---|---|---|---|---|---|---|---|
| CRM | `/crm/v8/org` | GET | `ZohoCRM.org.READ` | `id`, `company_name` | none | https://www.zoho.com/crm/developer/docs/api/v8/get-organization-details.html | — | — | `unverified` |
| CRM | `/crm/v8/settings/modules` | GET | `ZohoCRM.settings.READ` | `api_name`, `plural_label` | none | https://www.zoho.com/crm/developer/docs/api/v8/get-modules.html | — | — | `unverified` |
| CRM | `/crm/v8/settings/fields` (`?module=Leads\|Contacts\|Deals`) | GET | `ZohoCRM.settings.READ` | `api_name`, `data_type` | none | https://www.zoho.com/crm/developer/docs/api/v8/get-fields.html | — | — | `unverified` |
| CRM | `/crm/v8/Leads` | GET | `ZohoCRM.modules.READ` | `id`, `Email` | `page`/`per_page` via `info.more_records`; `page_token` past the offset | https://www.zoho.com/crm/developer/docs/api/v8/get-records.html | — | — | `unverified` |
| CRM | `/crm/v8/Contacts` | GET | `ZohoCRM.modules.READ` | `id`, `Email` | `page`/`per_page` via `info.more_records`; `page_token` past the offset | https://www.zoho.com/crm/developer/docs/api/v8/get-records.html | — | — | `unverified` |
| CRM | `/crm/v8/Deals` | GET | `ZohoCRM.modules.READ` | `id`, `Deal_Name` | `page`/`per_page` via `info.more_records`; `page_token` past the offset | https://www.zoho.com/crm/developer/docs/api/v8/get-records.html | — | — | `unverified` |
| CRM | `/crm/v8/users` | GET | `ZohoCRM.users.READ` | `id`, `email`, `status` | `page`/`per_page` via `info.more_records` | https://www.zoho.com/crm/developer/docs/api/v8/get-users.html | — | — | `unverified` |
| Accounts | `https://accounts.zoho.<tld>/oauth/v2/token` | POST | Self Client grant exchange only (separate auth transport) | `refresh_token`, `access_token`, `api_domain`, `expires_in` | none | https://www.zoho.com/accounts/protocol/oauth.html | — | — | `unverified` |

Multi-DC table (accounts + API domains per region) follows the official
guide: https://www.zoho.com/crm/developer/docs/api/multi-dc.html
