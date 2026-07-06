"""
08 Collective — Quotation Generator
====================================
Generates XLSX + PDF quotation following 08 Collective format.

Usage:
    python3 quotation_generator.py <json_data_file>

JSON format:
{
  "project": "Project Name",
  "client": "Client Name",
  "date": "2026-06-25",
  "ref_no": "Q-2026-001",
  "revision": "v1",
  "categories": [
    {
      "name": "Exhibition Structure",
      "items": [
        {"qty": 1, "unit": "set", "description": "Main structure", "rate": 50000},
        ...
      ]
    }
  ],
  "payment_terms": "50% deposit, 30% before delivery, 20% after installation",
  "validity": "30 days"
}

IMPORTANT: openpyxl on Python 3.14 — use fmt= keyword for format strings,
NEVER pass format string as 7th positional arg (causes Fill corruption).
"""

import json
import sys
import os
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill, numbers
from openpyxl.utils import get_column_letter

# ── Style definitions ──────────────────────────────────────────
FONT_TITLE = Font(name='Arial', size=16, bold=True, color='1a1a2e')
FONT_SUBTITLE = Font(name='Arial', size=10, color='555555')
FONT_HDR = Font(name='Arial', size=10, bold=True, color='ffffff')
FONT_NORMAL = Font(name='Arial', size=9)
FONT_BOLD = Font(name='Arial', size=9, bold=True)
FONT_TOTAL = Font(name='Arial', size=11, bold=True, color='1a1a2e')

FILL_HDR = PatternFill('solid', fgColor='1a1a2e')
FILL_CAT = PatternFill('solid', fgColor='e8edf2')
FILL_ALT = PatternFill('solid', fgColor='f8f9fa')
FILL_TOTAL = PatternFill('solid', fgColor='d4edda')

ALIGN_CENTER = Alignment(horizontal='center', vertical='center')
ALIGN_LEFT = Alignment(horizontal='left', vertical='center', wrap_text=True)
ALIGN_RIGHT = Alignment(horizontal='right', vertical='center')

THIN_BORDER = Border(
    left=Side(style='thin', color='cccccc'),
    right=Side(style='thin', color='cccccc'),
    top=Side(style='thin', color='cccccc'),
    bottom=Side(style='thin', color='cccccc'),
)


def sc(ws, row, col, value=None, font=None, fill=None, alignment=None,
       number_format=None, border=None):
    """Style-aware cell setter — compatible with 08 Collective's sc() pattern.

    All styling params are keyword-only for safety on Python 3.14.
    """
    cell = ws.cell(row=row, column=col, value=value)
    if font:
        cell.font = font
    if fill:
        cell.fill = fill
    if alignment:
        cell.alignment = alignment
    if number_format:
        cell.number_format = number_format
    if border:
        cell.border = border
    return cell


def generate_quotation(data, output_path):
    wb = Workbook()

    # ── Sheet 1: Cover ─────────────────────────────────────
    ws1 = wb.active
    ws1.title = "封面"
    ws1.sheet_properties.tabColor = '1a1a2e'

    for c in range(1, 6):
        ws1.column_dimensions[get_column_letter(c)].width = 18

    row = 1
    sc(ws1, row, 1, font=FONT_TITLE)
    row += 1
    sc(ws1, row, 1, "08 COLLECTIVE LIMITED", font=Font(name='Arial', size=22, bold=True, color='1a1a2e'))
    row += 1
    sc(ws1, row, 1, "RIBA Chartered Practice", font=Font(name='Arial', size=10, color='888888'))
    row += 2

    # Project info block
    info = [
        ("Project / 項目", data.get("project", "")),
        ("Client / 客戶", data.get("client", "")),
        ("Date / 日期", data.get("date", datetime.now().strftime("%Y-%m-%d"))),
        ("Ref No / 編號", data.get("ref_no", "")),
        ("Revision / 版本", data.get("revision", "v1")),
    ]
    for label, val in info:
        sc(ws1, row, 1, label, font=FONT_BOLD, fill=FILL_CAT, border=THIN_BORDER)
        sc(ws1, row, 2, val, font=FONT_NORMAL, border=THIN_BORDER)
        row += 1

    # ── Sheet 2: Quotation ────────────────────────────────
    ws2 = wb.create_sheet("報價單")
    ws2.sheet_properties.tabColor = '2d6a4f'

    col_widths = [8, 10, 10, 50, 18, 18]
    for i, w in enumerate(col_widths, 1):
        ws2.column_dimensions[get_column_letter(i)].width = w

    row = 1
    sc(ws2, row, 1, "QUOTATION / 報價單", font=Font(name='Arial', size=14, bold=True, color='1a1a2e'))
    row += 1
    sc(ws2, row, 1, f"{data.get('ref_no','')} | Rev: {data.get('revision','v1')} | {data.get('date','')}",
       font=FONT_SUBTITLE)
    row += 2

    # Header row
    headers = ["#", "QTY", "UNIT", "DESCRIPTION / 描述", "RATE / 單價", "AMOUNT / 金額"]
    for ci, h in enumerate(headers, 1):
        sc(ws2, row, ci, h, font=FONT_HDR, fill=FILL_HDR,
           alignment=ALIGN_CENTER, border=THIN_BORDER)
    row += 1

    total_amount = 0
    item_no = 0

    for cat in data.get("categories", []):
        # Category header
        sc(ws2, row, 1, font=FONT_BOLD, fill=FILL_CAT, border=THIN_BORDER)
        sc(ws2, row, 2, font=FONT_BOLD, fill=FILL_CAT, border=THIN_BORDER)
        sc(ws2, row, 3, font=FONT_BOLD, fill=FILL_CAT, border=THIN_BORDER)
        sc(ws2, row, 4, cat["name"], font=FONT_BOLD, fill=FILL_CAT,
           alignment=ALIGN_LEFT, border=THIN_BORDER)
        sc(ws2, row, 5, font=FONT_BOLD, fill=FILL_CAT, border=THIN_BORDER)
        sc(ws2, row, 6, font=FONT_BOLD, fill=FILL_CAT, border=THIN_BORDER)
        row += 1
        cat_subtotal = 0

        for item in cat.get("items", []):
            item_no += 1
            amt = item["qty"] * item["rate"]
            cat_subtotal += amt
            fill = FILL_ALT if item_no % 2 == 0 else None

            sc(ws2, row, 1, item_no, font=FONT_NORMAL, fill=fill, alignment=ALIGN_CENTER, border=THIN_BORDER)
            sc(ws2, row, 2, item["qty"], font=FONT_NORMAL, fill=fill, alignment=ALIGN_CENTER, border=THIN_BORDER)
            sc(ws2, row, 3, item["unit"], font=FONT_NORMAL, fill=fill, alignment=ALIGN_CENTER, border=THIN_BORDER)
            sc(ws2, row, 4, item["description"], font=FONT_NORMAL, fill=fill, alignment=ALIGN_LEFT, border=THIN_BORDER)
            sc(ws2, row, 5, item["rate"], font=FONT_NORMAL, fill=fill, alignment=ALIGN_RIGHT,
               number_format='#,##0', border=THIN_BORDER)
            sc(ws2, row, 6, amt, font=FONT_NORMAL, fill=fill, alignment=ALIGN_RIGHT,
               number_format='#,##0', border=THIN_BORDER)
            row += 1

        # Subtotal
        sc(ws2, row, 4, f"Subtotal: {cat['name']}", font=FONT_BOLD, fill=FILL_CAT,
           alignment=ALIGN_LEFT, border=THIN_BORDER)
        sc(ws2, row, 6, cat_subtotal, font=FONT_BOLD, fill=FILL_CAT,
           alignment=ALIGN_RIGHT, number_format='#,##0', border=THIN_BORDER)
        total_amount += cat_subtotal
        row += 1

    # Grand total
    row += 1
    sc(ws2, row, 4, "TOTAL / 總計", font=FONT_TOTAL, fill=FILL_TOTAL,
       alignment=ALIGN_LEFT, border=THIN_BORDER)
    sc(ws2, row, 6, total_amount, font=FONT_TOTAL, fill=FILL_TOTAL,
       alignment=ALIGN_RIGHT, number_format='#,##0', border=THIN_BORDER)
    row += 2

    # Payment terms
    sc(ws2, row, 1, "Payment Terms / 付款方式:", font=FONT_BOLD)
    row += 1
    for line in data.get("payment_terms", "").split("\n"):
        sc(ws2, row, 1, line, font=FONT_NORMAL)
        row += 1

    row += 1
    sc(ws2, row, 1, f"Validity / 有效期: {data.get('validity', '30 days')}", font=FONT_NORMAL)

    wb.save(output_path)
    return output_path


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            data = json.load(f)
    else:
        # Demo mode
        data = {
            "project": "Sample Exhibition",
            "client": "Sample Client",
            "date": "2026-06-25",
            "ref_no": "Q-2026-001",
            "revision": "v1",
            "categories": [
                {
                    "name": "Exhibition Structure",
                    "items": [
                        {"qty": 1, "unit": "set", "description": "Main structure fabrication", "rate": 80000},
                        {"qty": 2, "unit": "set", "description": "Display case 1200x600mm", "rate": 15000},
                    ]
                },
                {
                    "name": "Graphics",
                    "items": [
                        {"qty": 1, "unit": "lot", "description": "Backdrop printing + installation", "rate": 12000},
                    ]
                }
            ],
            "payment_terms": "50% deposit upon order\n30% before delivery\n20% after installation",
            "validity": "30 days"
        }

    out = f"/Users/aitree414/telegram-claude-bot/08_AI_Tools/quotation_{data['ref_no']}.xlsx"
    generate_quotation(data, out)
    print(f"✓ Quotation generated: {out}")
