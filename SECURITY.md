# Security

## Reporting a vulnerability

Open a GitHub issue titled `[SECURITY]` with minimal details, or contact the
repository owner privately. Do not include credentials, tokens or customer data.

## What this tool will never do

- Write to any Zoho org (all side-effecting operations emit dry-run plan artifacts).
- Send email, Slack or WhatsApp messages from its code, except to allow-listed
  test sinks with an explicit `--send` flag.
- Auto-apply AI suggestions. AI output is always a labeled suggestion for human review.
- Store real personal, employer or customer data in fixtures, cassettes, logs or reports.
