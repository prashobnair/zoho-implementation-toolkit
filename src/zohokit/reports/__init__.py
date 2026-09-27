"""Report renderers: JSON, rich table, Markdown, HTML (TK-CORE-8).

SARIF, JUnit and XLSX renderers land with later work packages. The HTML
report is a single self-contained file: inline CSS/JS only, so it works
offline and from a file:// URL.
"""

from __future__ import annotations

from typing import Any

from jinja2 import Environment
from rich.console import Console
from rich.table import Table

from zohokit.core.findings import Report
from zohokit.core.ids import canonical_json

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>zohokit {{ module }} report</title>
<style>
:root { --bg: #ffffff; --fg: #1a1a1a; --muted: #5b5b5b; --line: #d8d8d8;
        --error: #b42318; --review: #935705; --warning: #6b5900; --info: #175cd3; }
[data-theme="dark"] { --bg: #161616; --fg: #e8e8e8; --muted: #a8a8a8; --line: #3d3d3d;
        --error: #f97066; --review: #fdb022; --warning: #eaaa08; --info: #84adff; }
@media (prefers-color-scheme: dark) { [data-theme="auto"] { --bg: #161616; --fg: #e8e8e8;
        --muted: #a8a8a8; --line: #3d3d3d; --error: #f97066; --review: #fdb022;
        --warning: #eaaa08; --info: #84adff; } }
body { background: var(--bg); color: var(--fg); font-family: system-ui, sans-serif;
       margin: 2rem auto; max-width: 72rem; padding: 0 1rem; }
table { border-collapse: collapse; width: 100%; }
th, td { border: 1px solid var(--line); padding: 0.4rem 0.6rem; text-align: left;
         vertical-align: top; }
.banner { border: 2px solid var(--line); padding: 0.8rem 1rem; margin-bottom: 1rem; }
.ready { border-color: var(--info); } .not-ready { border-color: var(--error); }
.severity-error { color: var(--error); font-weight: bold; }
.severity-review { color: var(--review); font-weight: bold; }
.severity-warning { color: var(--warning); } .severity-info { color: var(--info); }
.filters { margin: 1rem 0; display: flex; gap: 1rem; flex-wrap: wrap; }
pre { white-space: pre-wrap; word-break: break-word; }
@media print { .filters, #theme-toggle { display: none; } }
</style>
</head>
<body>
<h1>zohokit {{ module }} report</h1>
<div class="banner {{ 'ready' if ready else 'not-ready' }}">
  {{ 'READY' if ready else 'NOT READY' }} &mdash;
  {{ summary.error }} error, {{ summary.review }} review,
  {{ summary.warning }} warning, {{ summary.info }} info
  (run {{ run_id }}, schema {{ schema_version }})
</div>
<div class="filters">
  <label>Severity:
    <select id="severity-filter">
      <option value="">all</option>
      <option value="error">error</option>
      <option value="review">review</option>
      <option value="warning">warning</option>
      <option value="info">info</option>
    </select>
  </label>
  <label>Code:
    <select id="code-filter">
      <option value="">all</option>
      {% for code in codes %}<option value="{{ code }}">{{ code }}</option>{% endfor %}
    </select>
  </label>
  <button id="theme-toggle" type="button">toggle light/dark</button>
  <span id="visible-count"></span>
</div>
<table>
  <thead><tr><th>Severity</th><th>Entity</th><th>Code</th><th>Message</th><th>Remediation</th><th>Evidence</th></tr></thead>
  <tbody>
  {% for finding in findings %}
    <tr data-severity="{{ finding.severity }}" data-code="{{ finding.code }}">
      <td class="severity-{{ finding.severity }}">{{ finding.severity }}</td>
      <td>{{ finding.entity }}/{{ finding.entity_id }}</td>
      <td>{{ finding.code }}</td>
      <td>{{ finding.message }}</td>
      <td>{% if finding.remediation %}<em>{{ finding.remediation }}</em>{% endif %}</td>
      <td>
        {% if finding.evidence %}
        <details><summary>evidence</summary><pre>{{ finding.evidence_json }}</pre></details>
        {% else %}&mdash;{% endif %}
      </td>
    </tr>
  {% endfor %}
  </tbody>
</table>
<script>
(function () {
  var root = document.documentElement;
  try {
    var saved = localStorage.getItem("zohokit-theme");
    if (saved === "light" || saved === "dark") { root.setAttribute("data-theme", saved); }
  } catch (e) {}
  document.getElementById("theme-toggle").addEventListener("click", function () {
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("zohokit-theme", next); } catch (e) {}
  });
  var severity = document.getElementById("severity-filter");
  var code = document.getElementById("code-filter");
  var count = document.getElementById("visible-count");
  function apply() {
    var shown = 0;
    document.querySelectorAll("tbody tr").forEach(function (row) {
      var ok = (!severity.value || row.dataset.severity === severity.value)
        && (!code.value || row.dataset.code === code.value);
      row.style.display = ok ? "" : "none";
      if (ok) { shown += 1; }
    });
    count.textContent = shown + " of {{ findings | length }} findings shown";
  }
  severity.addEventListener("change", apply);
  code.addEventListener("change", apply);
  apply();
})();
</script>
</body>
</html>
"""


def render_json(report: Report) -> str:
    """Render the report envelope as indented JSON."""
    return report.model_dump_json(indent=2)


def _dump(report: Report) -> dict[str, Any]:
    """JSON-mode dump with findings in report order."""
    return report.model_dump(mode="json")


def render_table(report: Report) -> str:
    """Render findings as a rich text table."""
    table = Table(title=f"zohokit {report.module} report")
    table.add_column("Severity")
    table.add_column("Entity")
    table.add_column("Code")
    table.add_column("Message")
    for finding in _dump(report)["findings"]:
        table.add_row(
            str(finding["severity"]),
            f"{finding['entity']}/{finding['entity_id']}",
            str(finding["code"]),
            str(finding["message"]),
        )
    console = Console(record=True, width=100)
    console.print(table)
    return str(console.export_text())


def render_markdown(report: Report) -> str:
    """Render the report as Markdown."""
    dumped = _dump(report)
    summary = dumped["summary"]
    lines = [
        f"# zohokit {report.module} report",
        "",
        f"**{'READY' if dumped['ready'] else 'NOT READY'}** — "
        f"{summary['error']} error, {summary['review']} review, "
        f"{summary['warning']} warning, {summary['info']} info.",
        "",
        "| Severity | Entity | Code | Message |",
        "| --- | --- | --- | --- |",
    ]
    for finding in dumped["findings"]:
        lines.append(
            f"| {finding['severity']} | {finding['entity']}/{finding['entity_id']} "
            f"| `{finding['code']}` | {finding['message']} |"
        )
    return "\n".join(lines) + "\n"


def render_html(report: Report) -> str:
    """Render a single self-contained HTML report file."""
    dumped = _dump(report)
    findings = []
    for finding in dumped["findings"]:
        evidence = finding.get("evidence") or {}
        findings.append({**finding, "evidence_json": canonical_json(evidence)})
    codes = sorted({str(item["code"]) for item in findings})
    template = Environment(autoescape=True).from_string(HTML_TEMPLATE)
    return template.render(
        module=dumped["module"],
        run_id=dumped["run_id"],
        schema_version=dumped["schema_version"],
        ready=dumped["ready"],
        summary=dumped["summary"],
        findings=findings,
        codes=codes,
    )


__all__: list[str] = ["render_html", "render_json", "render_markdown", "render_table"]
