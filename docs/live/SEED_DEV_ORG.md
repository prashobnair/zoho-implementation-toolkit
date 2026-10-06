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

## Workflow rules with 4 seeded issues (manual, UI only)

Seed these six Deals rules through **Setup → Automation → Workflow
Rules** (create each rule, its field-update action, then activate).
They mirror the synthetic cassette set at
`tests/contract/cassettes/crm_workflow_seeded.json`, so
`zohokit workflow lint --live --profile dev-in --experimental --module Deals`
must report exactly one `potential_loop`, one
`conflicting_field_updates`, one `stale_field_reference` and one
`empty_rule`. The live lint needs the read-only
`ZohoCRM.settings.workflow_rules.READ` and
`ZohoCRM.settings.automation_actions.READ` scopes on the profile.

1. **Seed loop A** — trigger: field update on `Owner`; instant action:
   field update `Stage` → `Negotiation`.
2. **Seed loop B** — trigger: field update on `Stage`; instant action:
   field update `Owner` → the sales owner. (A writes what B listens
   to and back: one `potential_loop` with the two-rule path.)
3. **Seed conflict A / B** — two rules, both trigger on record
   creation; instant actions set `Stage` → `Negotiation` vs
   `Proposal`. (One `conflicting_field_updates` on `Deals.Stage`.)
4. **Seed stale field** — trigger on creation with a condition on a
   field you then delete (or rename) in Setup → Customization; the
   rule keeps referencing it. (One `stale_field_reference`.)
5. **Seed empty rule** — trigger on creation with a condition on
   `Stage`, but attach no actions. (One `empty_rule`.)
6. Use only synthetic values (Marigold Labs) and leave every other
   Deals rule inactive while verifying, so the linter reports exactly
   the 4 seeded findings.

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
