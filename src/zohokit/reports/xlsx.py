"""XLSX workbook renderer for versioned reports (TK-CORE-8).

One workbook per report, three sheets: ``Summary`` (run banner plus
severity counts with a ``SUM`` totals formula), ``Findings`` (one row
per finding under a frozen header with auto-filters), and ``Sign-off``
(blank preparer/reviewer/date cells for the human review gate).
Binary output always goes to ``--out``; there is no stdout form.
"""

from __future__ import annotations

import io
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from zohokit.core.findings import Report
from zohokit.core.ids import canonical_json

#: Workbook sheets in order.
SHEET_NAMES = ("Summary", "Findings", "Sign-off")

#: Findings columns (frozen header + auto-filter).
FINDINGS_COLUMNS = (
    "Severity",
    "Entity",
    "Entity ID",
    "Code",
    "Message",
    "Remediation",
    "Evidence",
)

_BOLD = Font(bold=True)


#: Cell prefixes that make spreadsheet apps evaluate a value as a formula
#: (STD §4 safety). Any data-sourced text starting with one of these is
#: stored as a literal string (leading ``'``), never as a formula — only
#: the toolkit's own totals cells may carry formulas.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def safe_text(value: Any) -> Any:
    """Return *value* safe for a data cell: risky prefixes get a ``'`` guard.

    Non-strings pass through untouched. A string starting with ``=``,
    ``+``, ``-``, ``@``, tab or CR is prefixed with ``'`` so openpyxl
    stores it as text (``data_type`` stays a string, never ``"f"``) and
    spreadsheet apps show it literally instead of evaluating it.
    """
    if not isinstance(value, str):
        return value
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _text_cell(sheet: Worksheet, *, row: int, column: int, value: Any) -> None:
    """Write one data cell through :func:`safe_text` (never a formula)."""
    sheet.cell(row=row, column=column, value=safe_text(value))


def _summary_sheet(sheet: Worksheet, dumped: dict[str, Any]) -> None:
    """Banner rows plus severity counts with a formula total."""
    summary = dumped["summary"]
    sheet["A1"] = f"zohokit {dumped['module']} report"
    sheet["A1"].font = _BOLD
    sheet["A2"] = "Run"
    sheet["B2"] = dumped["run_id"]
    sheet["A3"] = "Mode"
    sheet["B3"] = dumped["mode"]
    sheet["A4"] = "Ready"
    sheet["B4"] = "READY" if dumped["ready"] else "NOT READY"
    sheet["A6"] = "Severity"
    sheet["B6"] = "Count"
    sheet["A6"].font = _BOLD
    sheet["B6"].font = _BOLD
    severities = ("error", "review", "warning", "info")
    for offset, severity in enumerate(severities):
        sheet.cell(row=7 + offset, column=1, value=severity)
        sheet.cell(row=7 + offset, column=2, value=int(summary[severity]))
    total_row = 7 + len(severities)
    sheet.cell(row=total_row, column=1, value="total").font = _BOLD
    # Formula total so finance can audit the arithmetic in Excel.
    sheet.cell(row=total_row, column=2, value=f"=SUM(B7:B{total_row - 1})")
    sheet.column_dimensions["A"].width = 16
    sheet.column_dimensions["B"].width = 40


def _findings_sheet(sheet: Worksheet, dumped: dict[str, Any]) -> None:
    """One row per finding; header frozen with auto-filters."""
    for column, title in enumerate(FINDINGS_COLUMNS, start=1):
        cell = sheet.cell(row=1, column=column, value=title)
        cell.font = _BOLD
    for number, finding in enumerate(dumped["findings"], start=2):
        _text_cell(sheet, row=number, column=1, value=str(finding["severity"]))
        _text_cell(sheet, row=number, column=2, value=str(finding["entity"]))
        _text_cell(sheet, row=number, column=3, value=str(finding["entity_id"]))
        _text_cell(sheet, row=number, column=4, value=str(finding["code"]))
        _text_cell(sheet, row=number, column=5, value=str(finding["message"]))
        _text_cell(sheet, row=number, column=6, value=str(finding.get("remediation") or ""))
        evidence = finding.get("evidence") or {}
        _text_cell(sheet, row=number, column=7, value=canonical_json(evidence))
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = f"A1:G{max(len(dumped['findings']) + 1, 1)}"
    for letter, col_width in zip("ABCDEFG", (10, 16, 16, 28, 60, 40, 50), strict=True):
        sheet.column_dimensions[letter].width = col_width


def _signoff_sheet(sheet: Worksheet) -> None:
    """Blank review gate: preparer, reviewer, date (all blank)."""
    sheet["A1"] = "Sign-off"
    sheet["A1"].font = _BOLD
    for number, label in enumerate(("Preparer", "Reviewer", "Date"), start=3):
        sheet.cell(row=number, column=1, value=label).font = _BOLD
        sheet.cell(row=number, column=2, value="")
    sheet.column_dimensions["A"].width = 16
    sheet.column_dimensions["B"].width = 40


def render_xlsx(report: Report) -> bytes:
    """Render *report* as an XLSX workbook (UTF-8 text throughout)."""
    dumped = report.model_dump(mode="json")
    book = Workbook()
    summary = book.worksheets[0]
    summary.title = "Summary"
    _summary_sheet(summary, dumped)
    findings = book.create_sheet("Findings")
    _findings_sheet(findings, dumped)
    signoff = book.create_sheet("Sign-off")
    _signoff_sheet(signoff)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


__all__: list[str] = ["FINDINGS_COLUMNS", "SHEET_NAMES", "render_xlsx", "safe_text"]
