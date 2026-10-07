"""Finance sign-off workbook for Books month-end recon (TK-BK-F7).

Seven tabs: ``Matched`` / ``Mismatched`` / ``Missing invoice`` /
``Orphan invoice`` / ``Needs review`` / ``FX`` / ``Sign-off``. Amount
columns carry real ``=SUM(...)`` totals formulas (finance can audit the
arithmetic in Excel); every other cell is literal text through
:func:`safe_text`, so data-sourced values (deal names, customers,
reference numbers, messages) can never become formulas (STD §4 safety —
only the toolkit's own totals cells may be formulas).
"""

from __future__ import annotations

import io
import re
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.worksheet.worksheet import Worksheet

from zohokit.core.findings import Report
from zohokit.reports.xlsx import safe_text

#: Workbook tabs in order.
BOOKS_SHEETS = (
    "Matched",
    "Mismatched",
    "Missing invoice",
    "Orphan invoice",
    "Needs review",
    "FX",
    "Sign-off",
)

#: Row columns for the five finding tabs.
ROW_COLUMNS = (
    "Entity",
    "ID",
    "Customer",
    "Code",
    "Deal Net",
    "Invoiced Total",
    "Currency",
    "Converted Total",
    "Converted Currency",
    "Message",
)

#: Row columns for the FX tab (one row per conversion or missing rate).
FX_COLUMNS = (
    "Deal",
    "Invoice",
    "Original",
    "Original Currency",
    "Converted",
    "Converted Currency",
    "Rate",
    "Rate Source",
    "Note",
)

_MATCHED_CODES = frozenset({"within_tolerance"})
_MISMATCHED_CODES = frozenset({"outside_tolerance", "under_invoiced", "over_invoiced"})

_BOLD = Font(bold=True)


def _tab_for(code: str) -> str:
    """Finding tab for *code* (anything else needs review)."""
    if code in _MATCHED_CODES:
        return "Matched"
    if code in _MISMATCHED_CODES:
        return "Mismatched"
    if code == "missing_invoice":
        return "Missing invoice"
    if code == "orphan_invoice_reference":
        return "Orphan invoice"
    return "Needs review"


def _number(raw: Any) -> float | None:
    """Evidence amount as a float for Excel, else ``None`` (blank cell)."""
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw))
    except ValueError:
        return None


def _row_for(finding: dict[str, Any]) -> list[Any]:
    """One workbook row for a recon finding."""
    evidence = finding.get("evidence") or {}
    conversions = evidence.get("conversions") or []
    converted_total: Any = ""
    converted_ccy = ""
    if isinstance(conversions, list) and conversions:
        first = conversions[0] if isinstance(conversions[0], dict) else {}
        parsed = _number(first.get("converted"))
        converted_total = parsed if parsed is not None else ""
        converted_ccy = str(first.get("converted_currency", ""))
    return [
        str(finding.get("entity", "")),
        str(finding.get("entity_id", "")),
        str(evidence.get("customer_name", "")),
        str(finding.get("code", "")),
        _number(evidence.get("deal_net")),
        _number(evidence.get("invoiced_total")),
        str(evidence.get("currency", "")),
        converted_total,
        converted_ccy,
        str(finding.get("message", "")),
    ]


def _fx_rows(findings: list[dict[str, Any]]) -> list[list[Any]]:
    """FX tab rows: one per conversion plus one per missing rate."""
    rows: list[list[Any]] = []
    for finding in findings:
        evidence = finding.get("evidence") or {}
        conversions = evidence.get("conversions")
        if isinstance(conversions, list):
            for entry in conversions:
                if not isinstance(entry, dict):
                    continue
                rows.append(
                    [
                        str(finding.get("entity_id", "")),
                        str(entry.get("invoice_id", "")),
                        _number(entry.get("original")),
                        str(entry.get("original_currency", "")),
                        _number(entry.get("converted")),
                        str(entry.get("converted_currency", "")),
                        str(entry.get("rate", "")),
                        str(entry.get("source", entry.get("rate_source", ""))),
                        "",
                    ]
                )
        if finding.get("code") == "fx_rate_missing":
            rows.append(
                [
                    str(finding.get("entity_id", "")),
                    str(evidence.get("invoice_id", "")),
                    "",
                    str(evidence.get("from_currency", "")),
                    "",
                    str(evidence.get("to_currency", "")),
                    "",
                    "",
                    "no exact rate: comparison skipped, never guessed",
                ]
            )
    return rows


def _write_header(sheet: Worksheet, columns: tuple[str, ...]) -> None:
    for number, title in enumerate(columns, start=1):
        sheet.cell(row=1, column=number, value=title).font = _BOLD


def _write_rows(sheet: Worksheet, rows: list[list[Any]]) -> int:
    """Write data rows through :func:`safe_text`; return the totals row."""
    for line, values in enumerate(rows, start=2):
        for number, value in enumerate(values, start=1):
            if isinstance(value, (int, float)):
                sheet.cell(row=line, column=number, value=value)
            else:
                sheet.cell(row=line, column=number, value=safe_text(value))
    return max(len(rows) + 2, 3)


def _write_totals(
    sheet: Worksheet, total_row: int, amount_columns: tuple[int, ...], last_data: int
) -> None:
    """Real ``=SUM`` totals over each amount column (blank-safe ranges)."""
    sheet.cell(row=total_row, column=1, value="Total").font = _BOLD
    for column in amount_columns:
        letter = sheet.cell(row=1, column=column).column_letter
        sheet.cell(row=total_row, column=column, value=f"=SUM({letter}2:{letter}{last_data})")


def _finish_tab(sheet: Worksheet, columns: tuple[str, ...]) -> None:
    sheet.freeze_panes = "A2"
    last_col = sheet.cell(row=1, column=len(columns)).column_letter
    sheet.auto_filter.ref = f"A1:{last_col}{sheet.max_row}"


def render_books_workbook(report: Report) -> bytes:
    """Render a recon *report* as the finance sign-off workbook."""
    dumped = report.model_dump(mode="json")
    findings = dumped.get("findings", [])
    book = Workbook()
    book.worksheets[0].title = BOOKS_SHEETS[0]
    sheets = {
        name: (book.worksheets[0] if name == BOOKS_SHEETS[0] else book.create_sheet(name))
        for name in BOOKS_SHEETS
    }
    buckets: dict[str, list[dict[str, Any]]] = {
        "Matched": [],
        "Mismatched": [],
        "Missing invoice": [],
        "Orphan invoice": [],
        "Needs review": [],
    }
    for finding in findings:
        buckets[_tab_for(str(finding.get("code", "")))].append(finding)
    for name in ("Matched", "Mismatched", "Missing invoice", "Orphan invoice", "Needs review"):
        sheet = sheets[name]
        _write_header(sheet, ROW_COLUMNS)
        total_row = _write_rows(sheet, [_row_for(item) for item in buckets[name]])
        last_data = max(len(buckets[name]) + 1, 2)
        _write_totals(sheet, total_row, (5, 6), last_data)
        _finish_tab(sheet, ROW_COLUMNS)
    fx_sheet = sheets["FX"]
    _write_header(fx_sheet, FX_COLUMNS)
    fx_data = _fx_rows(findings)
    total_row = _write_rows(fx_sheet, fx_data)
    last_data = max(len(fx_data) + 1, 2)
    _write_totals(fx_sheet, total_row, (3, 5), last_data)
    _finish_tab(fx_sheet, FX_COLUMNS)
    signoff = sheets["Sign-off"]
    signoff["A1"] = "Sign-off"
    signoff["A1"].font = _BOLD
    for number, label in enumerate(("Preparer", "Reviewer", "Date"), start=3):
        signoff.cell(row=number, column=1, value=label).font = _BOLD
        signoff.cell(row=number, column=2, value="")
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def sum_range(formula: str, sheet: Worksheet) -> float:
    """Evaluate a ``=SUM(Xa:Xb)`` *formula* against *sheet* values (tests)."""
    match = re.fullmatch(r"=SUM\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)", formula.strip())
    if match is None:
        raise ValueError(f"not a SUM range formula: {formula!r}")
    col_a, row_a, col_b, row_b = (
        match.group(1),
        int(match.group(2)),
        match.group(3),
        int(match.group(4)),
    )
    if col_a != col_b:
        raise ValueError(f"not a single-column SUM: {formula!r}")
    total = 0.0
    for row in range(row_a, row_b + 1):
        value = sheet[f"{col_a}{row}"].value
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            total += float(value)
    return total


__all__: list[str] = [
    "BOOKS_SHEETS",
    "FX_COLUMNS",
    "ROW_COLUMNS",
    "render_books_workbook",
    "sum_range",
]
