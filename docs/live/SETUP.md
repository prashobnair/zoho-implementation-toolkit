# Live setup: connect your Developer Edition org

> Scope & safety: live mode only ever **reads** through `GET` requests
> (anything else is rejected inside the tool before it leaves your
> machine). It never writes to your org, never sends messages, and never
> stores personal data in this repo. Secrets live in two places only: your
> own terminal while you type them, and the `zoho-dev` environment on
> GitHub. Never paste them anywhere else — not in issues, chat, docs, or
> code.

## What you need

- A Zoho **Developer Edition** org in the **IN data centre**. (Sign up at
  zoho.com; confirm the edition under Setup → Developer Space.)
- A terminal on your own machine with this repo checked out.

## 1. Create a Self Client

1. Open the Zoho API Console and create a **Self Client** (choose the IN
   data centre).
2. Tick **only** these read-only scopes — nothing broader:
   - `ZohoCRM.modules.READ`
   - `ZohoCRM.settings.READ`
   - `ZohoCRM.users.READ`
   - `ZohoCRM.org.READ`
3. The console shows a **grant code**. It expires quickly, so keep this
   page open and move to the next step right away.

## 2. Exchange the grant code (your terminal only)

Run these in your own terminal — never on a shared machine, and never
paste the values anywhere else:

```sh
export ZOHO_CLIENT_ID="<client id from the console>"
export ZOHO_CLIENT_SECRET="<client secret from the console>"
uv run zohokit auth login --profile dev-in --dc in \
  --scopes ZohoCRM.modules.READ,ZohoCRM.settings.READ,ZohoCRM.users.READ,ZohoCRM.org.READ
```

When asked, paste the grant code and press Enter. The tool exchanges it
for a refresh token and stores that token in your OS keyring (nothing is
written to the repo). Then check the connection:

```sh
uv run zohokit auth status --profile dev-in
uv run zohokit doctor --live --profile dev-in --experimental
```

`doctor` prints a checklist (`dc_reachability`, `token_refresh`,
`org_identity`, `scope_sufficiency`, `budget`, `environment_type`). Your
org appears only as a `sha256:` fingerprint, never as a raw ID. Any line
marked fail exits the command with code 3 and tells you what to fix
(usually a missing scope or an expired grant code — generate a fresh one
and repeat this step).

When you are done, clear the terminal exports (`unset ZOHO_CLIENT_ID
ZOHO_CLIENT_SECRET`).

## Books scopes (needed later; not granted yet)

Month-end reconciliation reads Zoho Books through these read-only
scopes (see `docs/API_CONTRACTS.md`; the readers are unverified, so
every Books call additionally needs `--experimental`):

- `ZohoBooks.invoices.READ`
- `ZohoBooks.contacts.READ`
- `ZohoBooks.creditnotes.READ`
- `ZohoBooks.settings.READ` (currencies, taxes, organizations)

Do not tick them on the Self Client yet: there is no Books org to verify
against, and the committed `profiles/dev-in.json` stays CRM-only until
the owner approves a Books verification run. Raw Books organization IDs
live only in the local (uncommitted) profile copy under `books_orgs`;
reports and logs carry fingerprints only.

## 3. Save the three secrets for scheduled runs

The weekly verification runs on GitHub, not on your machine, so it
needs its own copy of the credentials:

1. Open the repo on GitHub → Settings → Environments → `zoho-dev`.
2. Add three environment secrets (values from step 2 — type them, do not
   paste them anywhere else first):
   - `ZOHO_CLIENT_ID`
   - `ZOHO_CLIENT_SECRET`
   - `ZOHO_REFRESH_TOKEN` (shown once by the console; if you no longer
     have it, run step 2 again with a fresh grant code)
3. That is the only place these values exist outside your keyring. The
   committed `profiles/dev-in.json` holds the profile name, data centre
   and scopes only — no secrets.

## 4. Approve a live run

Every live run waits for your approval — nothing runs unattended:

1. Open the repo on GitHub → Actions → **live**.
2. Pick **Run workflow** (tick `record` only when you want fresh redacted
   cassettes recorded), or wait for the weekly schedule (Mondays 21:00
   UTC == Tuesdays 02:30 IST).
3. GitHub asks for review because the job uses the `zoho-dev`
   environment. Open the pending run and choose **Approve**.
4. When the run finishes, download the **live-evidence** artifact
   (`doctor.json`, `doctor.md`, `smoke.json`; plus **live-cassettes** when
   recording). Artifacts are kept for 14 days.

The job fails loudly on contract drift (the org's shape changed versus
the documented contracts) or if the redaction scan finds anything
suspicious — treat either as a stop-and-investigate signal, not as noise.

## 5. After the run

A maintainer reviews the downloaded artifact and commits the redacted
evidence through a normal pull request. The workflow itself never commits
anything. To refresh the demo data the checks read, see
`live/SEED_DEV_ORG.md` (manual import through the Zoho UI — the tool
itself cannot seed anything, by design).
