# Seeding the Developer Edition org (manual, UI only)

> Scope & safety: the toolkit never writes to Zoho. Seeding the demo org
> is a manual procedure through the Zoho UI only. Every value below is
> synthetic (Marigold Labs) and safe to share.

## What to create

1. **CRM modules** (Setup → Customization → Modules): confirm `Leads`,
   `Contacts`, `Accounts`, `Deals`, `Tasks`, `Calls`, `Notes` are visible.
   No custom modules are needed for the demo.
2. **One deal pipeline**: keep the standard `Stage` picklist values
   (`Qualification`, `Needs Analysis`, `Proposal`, `Negotiation`,
   `Closed Won`, `Closed Lost`).
3. **Two users**: an admin (yourself) plus one synthetic sales owner
   `sales.owner@example.invalid` with the Standard profile.
4. **Five sample records** per module below, imported through each
   module's **Import** wizard (CSV files in `docs/live/seed/`):
   - `accounts.csv` → Accounts
   - `contacts.csv` → Contacts (link each contact to its account)
   - `deals.csv` → Deals (link to account + contact, set `Stage`)
   - `leads.csv` → Leads (leave two `Lead_Status` values unset to demo
     the `owner_unmapped` finding)
5. **One duplicate pair on purpose**: `contacts.csv` contains two rows
   for the same mailbox with different casing, so duplicate detection
   has something to find.

## Steps (Zoho CRM UI)

1. Sign in to the Developer Edition org (`Setup → Developer Space`
   confirms the edition).
2. Open a module → **⋯ → Import** → upload the matching CSV →
   map columns to fields → **Import**.
3. Repeat for all four files, in this order: Accounts, Contacts,
   Deals, Leads.
4. Verify: Accounts shows 5 rows, Contacts shows 6 (incl. the duplicate
   pair), Deals shows 5, Leads shows 5.

## After seeding

- Run `zohokit auth login --profile dev-in --dc in --scopes
  ZohoCRM.modules.READ,ZohoCRM.settings.READ,ZohoCRM.users.READ,ZohoCRM.org.READ`
  with read-only scopes (see `live/SETUP.md`), then
  `zohokit doctor --live --profile dev-in --experimental`.
- Record cassettes locally: `make record MODULE=crm PROFILE=dev-in
  ENDPOINT=/crm/v8/org`, then `make scrub`.
- Never commit unredacted exports: the `cassette-scan` CI job fails on
  real mailboxes, phone numbers, or IDs listed in
  `cassettes/known_org_ids.txt`.
