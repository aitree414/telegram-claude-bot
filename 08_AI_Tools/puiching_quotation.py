#!/usr/bin/env python3
"""
Pui Ching Middle School — Entrance Display Shelving System Quotation
=====================================================================
Generates a professional quotation Excel file based on the 27-page
technical drawing set (裘槎科學周 / Chow Tai Fook Science Week).
"""

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
from openpyxl.utils import get_column_letter
from copy import copy

OUTPUT_DIR = "/Volumes/Apollo Sync Folder/08collective/PuiChing_ScienceWeek"
OUTPUT_FILE = f"{OUTPUT_DIR}/PuiChing_EntranceDisplay_Quotation.xlsx"

# 15% markup on all unit rates
MARKUP = 1.15

# ─── Styles ──────────────────────────────────────────────
FONT_TITLE = Font(name="Arial", size=22, bold=True)
FONT_SUBTITLE = Font(name="Arial", size=10, color="555555")
FONT_SECTION = Font(name="Arial", size=10, bold=True, color="1a1a2e")
FONT_ITEM = Font(name="Arial", size=9)
FONT_HEADER = Font(name="Arial", size=10, bold=True, color="FFFFFF")
FONT_SUBTOTAL = Font(name="Arial", size=9, bold=True, color="1a1a2e")
FONT_TOTAL = Font(name="Arial", size=11, bold=True, color="1a1a2e")

FILL_HEADER = PatternFill(start_color="1a1a2e", end_color="1a1a2e", fill_type="solid")
FILL_SECTION = PatternFill(start_color="e8edf2", end_color="e8edf2", fill_type="solid")
FILL_ROW_EVEN = PatternFill(start_color="f8f9fa", end_color="f8f9fa", fill_type="solid")
FILL_TOTAL = PatternFill(start_color="d4edda", end_color="d4edda", fill_type="solid")
FILL_WHITE = PatternFill(start_color="ffffff", end_color="ffffff", fill_type="solid")

ALIGN_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")
ALIGN_AMOUNT = Alignment(horizontal="right", vertical="center", wrap_text=True)

THIN_BORDER = Border(
    left=Side(style="thin", color="d0d0d0"),
    right=Side(style="thin", color="d0d0d0"),
    top=Side(style="thin", color="d0d0d0"),
    bottom=Side(style="thin", color="d0d0d0"),
)

def sc(ws, row, col, value, font=FONT_ITEM, fill=None, alignment=ALIGN_LEFT, number_format=None):
    """Set cell value and formatting."""
    cell = ws.cell(row=row, column=col, value=value)
    cell.font = font
    if fill:
        cell.fill = fill
    cell.alignment = alignment
    if number_format:
        cell.number_format = number_format
    cell.border = THIN_BORDER
    return cell

def write_category(ws, row, col, text):
    """Write a category header row."""
    for c in range(1, 7):
        sc(ws, row, c, None, FONT_ITEM, FILL_SECTION)
    sc(ws, row, 4, text, FONT_SECTION, FILL_SECTION, ALIGN_LEFT)

def write_subtotal(ws, row, label, amount):
    """Write a subtotal row."""
    for c in range(1, 7):
        sc(ws, row, c, None, FONT_SUBTOTAL, FILL_SECTION)
    sc(ws, row, 4, label, FONT_SUBTOTAL, FILL_SECTION, ALIGN_LEFT)
    sc(ws, row, 6, amount, FONT_SUBTOTAL, FILL_SECTION, ALIGN_AMOUNT, '#,##0')

def m(v):
    """Apply 15% markup using integer arithmetic."""
    return (v * 115 + 50) // 100  # round to nearest integer

def write_item(ws, row, num, qty, unit, desc, rate, amount, even=False):
    """Write an item row."""
    fill = FILL_ROW_EVEN if even else FILL_WHITE
    sc(ws, row, 1, num, FONT_ITEM, fill, ALIGN_CENTER)
    sc(ws, row, 2, qty, FONT_ITEM, fill, ALIGN_CENTER)
    sc(ws, row, 3, unit, FONT_ITEM, fill, ALIGN_CENTER)
    sc(ws, row, 4, desc, FONT_ITEM, fill, ALIGN_LEFT)
    sc(ws, row, 5, rate, FONT_ITEM, fill, ALIGN_AMOUNT, '#,##0')
    sc(ws, row, 6, amount, FONT_ITEM, fill, ALIGN_AMOUNT, '#,##0')

def generate():
    wb = openpyxl.Workbook()

    # ════════════════════════════════════════════════════════
    # Sheet 1: 封面 (Cover)
    # ════════════════════════════════════════════════════════
    ws_cover = wb.active
    ws_cover.title = "封面"
    ws_cover.sheet_properties.tabColor = "1a1a2e"

    # Column widths
    ws_cover.column_dimensions["A"].width = 22
    ws_cover.column_dimensions["B"].width = 55

    cover_labels = [
        "08 COLLECTIVE LIMITED",
        "RIBA Chartered Practice",
    ]
    cover_fields = [
        ("Project / 項目", "Pui Ching Middle School — Entrance Display Shelving System"),
        ("Client / 客戶", "Pui Ching Secondary School (培正中學)"),
        ("Event / 活動", "裘槎科學周 / Chow Tai Fook Science Week"),
        ("Date / 日期", "2026.06.29"),
        ("Ref No / 編號", "PC-ED-2026-001"),
        ("Revision / 版本", "v1"),
    ]

    ws_cover.cell(row=1, column=1, value=cover_labels[0]).font = FONT_TITLE
    ws_cover.cell(row=2, column=1, value=cover_labels[1]).font = FONT_SUBTITLE

    for i, (label, value) in enumerate(cover_fields, start=4):
        cell_a = ws_cover.cell(row=i, column=1, value=label)
        cell_a.font = Font(name="Arial", size=9, bold=True)
        cell_a.fill = PatternFill(start_color="e8edf2", end_color="e8edf2", fill_type="solid")
        cell_a.alignment = ALIGN_LEFT

        cell_b = ws_cover.cell(row=i, column=2, value=value)
        cell_b.font = Font(name="Arial", size=9)
        cell_b.alignment = ALIGN_LEFT

    ws_cover.row_dimensions[1].height = 36
    ws_cover.row_dimensions[2].height = 18

    # ════════════════════════════════════════════════════════
    # Sheet 2: 報價單 (Quotation)
    # ════════════════════════════════════════════════════════
    ws = wb.create_sheet(title="報價單")
    ws.sheet_properties.tabColor = "2d6a4f"

    # Column widths
    col_widths = {"A": 8, "B": 10, "C": 10, "D": 55, "E": 18, "F": 18}
    for col, w in col_widths.items():
        ws.column_dimensions[col].width = w

    r = 1
    # Title
    ws.merge_cells(f"A{r}:F{r}")
    sc(ws, r, 1, "QUOTATION / 報價單", Font(name="Arial", size=14, bold=True), None, ALIGN_LEFT)
    r += 1
    # Reference
    ws.merge_cells(f"A{r}:F{r}")
    sc(ws, r, 1, "PC-ED-2026-001 | Rev: v1 | 2026.06.29", Font(name="Arial", size=10, color="555555"), None, ALIGN_LEFT)
    r += 1
    # Blank row
    r += 1

    # Header row
    headers = ["#", "QTY", "UNIT", "DESCRIPTION / 描述", "RATE / 單價", "AMOUNT / 金額"]
    for c, h in enumerate(headers, 1):
        sc(ws, r, c, h, FONT_HEADER, FILL_HEADER, ALIGN_CENTER)
    r += 1

    # ─── Item counter ───
    item_no = [0]  # mutable counter

    # ─── A. Shelf Module System ───
    write_category(ws, r, 4, "A. 層架模組系統 / Shelf Module System")
    r += 1

    items_a = [
        (8, "SET", "Shelf Module 層架模組 — 2120×1280×2770mm, 10mm plywood w/ cherry veneer, clear matte coat", m(18500), m(148000)),
        (1, "LOT", "Shelf Reinforcement 層架補強 — 12mm aluminium extrusion, shelf re-enforcement bar", m(8500), m(8500)),
        (15, "PCS", "Shelf (Individual) 單片層板 — 678×320mm, 10mm cherry veneer plywood, clear matte finish", m(3200), m(48000)),
        (8, "SET", "Back Panel Add-on Module 背板模組 — aluminium 2mm, natural-colour oxidation treatment", m(4200), m(33600)),
        (8, "SET", "Light Track Add-on Module 燈軌模組 — aluminium 2mm, natural-colour oxidation treatment", m(3800), m(30400)),
        (8, "SET", "Display Panel Add-on Module 展板模組 — aluminium 2mm, silk screen print text", m(4500), m(36000)),
    ]
    for i, (qty, unit, desc, rate, amt) in enumerate(items_a):
        item_no[0] += 1
        write_item(ws, r, item_no[0], qty, unit, desc, rate, amt, even=(i % 2 == 1))
        r += 1
    write_subtotal(ws, r, "Subtotal: A. 層架模組系統", m(304500))
    r += 1

    # ─── B. Aluminium Pole System ───
    write_category(ws, r, 4, "B. 鋁合金立柱系統 / Aluminium Pole System")
    r += 1

    items_b = [
        (30, "PCS", "Pole 1 立柱 — 6mm aluminium, 2100mm, natural-colour oxidation treatment, CNC precision", m(2800), m(84000)),
        (15, "PCS", "Pole Extension Top 頂部延伸 — 6mm aluminium, 670mm, natural-colour oxidation treatment", m(1800), m(27000)),
        (60, "PCS", "Connector 1 連接件 — stainless steel 6mm, mirror finish, precision CNC", m(650), m(39000)),
    ]
    for i, (qty, unit, desc, rate, amt) in enumerate(items_b):
        item_no[0] += 1
        write_item(ws, r, item_no[0], qty, unit, desc, rate, amt, even=(i % 2 == 1))
        r += 1
    write_subtotal(ws, r, "Subtotal: B. 鋁合金立柱系統", m(150000))
    r += 1

    # ─── C. Hardware & Fixings ───
    write_category(ws, r, 4, "C. 五金配件 / Hardware & Fixings")
    r += 1

    items_c = [
        (15, "PCS", "Ceiling Fixing 天花板固定件 — aluminium CNC, threaded for expansion bolt, natural-colour oxidation", m(2200), m(33000)),
        (15, "PCS", "Foot 底座 — aluminium CNC, natural-colour oxidation treatment, 115×62.5×35mm", m(1800), m(27000)),
        (200, "PCS", "M4 Hex Socket Screw M4 內六角螺絲 — SUS304 stainless steel", m(8), m(1600)),
        (200, "PCS", "M5 Hex Socket Screw M5 內六角螺絲 — SUS304 stainless steel", m(10), m(2000)),
        (500, "PCS", "Stainless Steel Washer 不鏽鋼墊圈 Ø5 — SUS304", m(3), m(1500)),
        (100, "PCS", "Expansion Bolt 膨脹螺絲 (ceiling mount) — M8×80mm galvanized steel", m(25), m(2500)),
    ]
    for i, (qty, unit, desc, rate, amt) in enumerate(items_c):
        item_no[0] += 1
        write_item(ws, r, item_no[0], qty, unit, desc, rate, amt, even=(i % 2 == 1))
        r += 1
    write_subtotal(ws, r, "Subtotal: C. 五金配件", m(67600))
    r += 1

    # ─── D. Smart Glass / Acrylic Panels ───
    write_category(ws, r, 4, "D. 智能玻璃面板 / Smart Glass & Acrylic Panels")
    r += 1

    items_d = [
        (8, "SET", "Smart Glass Front Panel 智能玻璃前面板 — acrylic + smart glass sticker, motion detection (opaque/clear)", m(8500), m(68000)),
        (8, "SET", "Acrylic Display Panel 壓克力展示面板 — 4mm clear acrylic, laser cut, polished edge", m(3200), m(25600)),
        (1, "LOT", "Motion Sensor System 感應器系統 — PIR motion detector + controller, wiring", m(18000), m(18000)),
    ]
    for i, (qty, unit, desc, rate, amt) in enumerate(items_d):
        item_no[0] += 1
        write_item(ws, r, item_no[0], qty, unit, desc, rate, amt, even=(i % 2 == 1))
        r += 1
    write_subtotal(ws, r, "Subtotal: D. 智能玻璃面板", m(111600))
    r += 1

    # ─── E. Graphics & Finishing ───
    write_category(ws, r, 4, "E. 圖像及表面處理 / Graphics & Finishing")
    r += 1

    items_e = [
        (1, "LOT", "Vinyl Die-cut Graphic 割字貼圖 — full set, high-grade outdoor vinyl, installation included", m(28000), m(28000)),
        (1, "LOT", "Display Trophy Mockup 獎盃展示模型 — trophy display arrangement design + fabrication", m(35000), m(35000)),
        (1, "LOT", "Surface Finish — Aluminium natural-colour oxidation treatment (all aluminium components)", m(45000), m(45000)),
        (1, "LOT", "Wood Veneer Finish — Cherry veneer clear matte coat (all shelf modules)", m(32000), m(32000)),
    ]
    for i, (qty, unit, desc, rate, amt) in enumerate(items_e):
        item_no[0] += 1
        write_item(ws, r, item_no[0], qty, unit, desc, rate, amt, even=(i % 2 == 1))
        r += 1
    write_subtotal(ws, r, "Subtotal: E. 圖像及表面處理", m(140000))
    r += 1

    # ─── F. Fabrication & Assembly ───
    write_category(ws, r, 4, "F. 加工製作 / Fabrication & Assembly")
    r += 1

    items_f = [
        (1, "LOT", "CNC Machining — all aluminium pole, connector, fixing components CNC precision cutting/drilling", m(68000), m(68000)),
        (1, "LOT", "Woodwork Fabrication — shelf modules: cutting, edge-banding, veneering, assembly", m(55000), m(55000)),
        (1, "LOT", "Acrylic Laser Cutting — all acrylic display panels + smart glass frames", m(18000), m(18000)),
        (1, "LOT", "Silk Screen Printing — display panel text/graphics, aluminium panels", m(12000), m(12000)),
        (1, "LOT", "Welding & Metal Joinery — stainless steel connectors, pole assembly jig", m(15000), m(15000)),
        (1, "LOT", "Quality Control Inspection — full assembly test, dimensional check, finish inspection", m(12000), m(12000)),
    ]
    for i, (qty, unit, desc, rate, amt) in enumerate(items_f):
        item_no[0] += 1
        write_item(ws, r, item_no[0], qty, unit, desc, rate, amt, even=(i % 2 == 1))
        r += 1
    write_subtotal(ws, r, "Subtotal: F. 加工製作", m(180000))
    r += 1

    # ─── G. Installation ───
    write_category(ws, r, 4, "G. 現場安裝 / Site Installation")
    r += 1

    items_g = [
        (12, "MAN-DAY", "On-site Installation 現場安裝 — 4 persons × 3 days (load-in, assembly, alignment, testing)", m(8000), m(96000)),
        (1, "LOT", "Ceiling Mounting Rigging 天花板吊掛安裝 — fixing installation, load test, safety check", m(25000), m(25000)),
        (1, "LOT", "Electrical Wiring 電線配置 — motion sensor system, LED light track wiring, connection", m(15000), m(15000)),
        (1, "LOT", "Site Management & Supervision 現場管理及技術監督", m(20000), m(20000)),
    ]
    for i, (qty, unit, desc, rate, amt) in enumerate(items_g):
        item_no[0] += 1
        write_item(ws, r, item_no[0], qty, unit, desc, rate, amt, even=(i % 2 == 1))
        r += 1
    write_subtotal(ws, r, "Subtotal: G. 現場安裝", m(156000))
    r += 1

    # ─── H. Transport & Logistics ───
    write_category(ws, r, 4, "H. 運輸物流 / Transport & Logistics")
    r += 1

    items_h = [
        (1, "LOT", "Material Transport 材料運輸 (workshop → site, 1 truckload)", m(12000), m(12000)),
        (1, "LOT", "Packaging & Protection 包裝保護 — EPE foam + plywood crates for all components", m(15000), m(15000)),
    ]
    for i, (qty, unit, desc, rate, amt) in enumerate(items_h):
        item_no[0] += 1
        write_item(ws, r, item_no[0], qty, unit, desc, rate, amt, even=(i % 2 == 1))
        r += 1
    write_subtotal(ws, r, "Subtotal: H. 運輸物流", m(27000))
    r += 1

    # ─── I. Design & Management ───
    write_category(ws, r, 4, "I. 設計及管理 / Design & Management")
    r += 1

    items_i = [
        (1, "LOT", "Design Fee 設計費 — technical drawing, structural calculation, installation plan", m(35000), m(35000)),
        (1, "LOT", "Project Management 項目管理費", m(25000), m(25000)),
        (1, "LOT", "Insurance 保險 — construction + public liability", m(15000), m(15000)),
        (1, "LOT", "Miscellaneous & Contingency 雜項及不可預見費", m(20000), m(20000)),
    ]
    for i, (qty, unit, desc, rate, amt) in enumerate(items_i):
        item_no[0] += 1
        write_item(ws, r, item_no[0], qty, unit, desc, rate, amt, even=(i % 2 == 1))
        r += 1
    write_subtotal(ws, r, "Subtotal: I. 設計及管理", m(95000))
    r += 1

    # Blank row
    r += 1

    # ─── GRAND TOTAL ───
    grand_total = m(304500 + 150000 + 67600 + 111600 + 140000 + 180000 + 156000 + 27000 + 95000)

    for c in range(1, 7):
        sc(ws, r, c, None, FONT_TOTAL, FILL_TOTAL)
    sc(ws, r, 4, "TOTAL / 總計", Font(name="Arial", size=11, bold=True), FILL_TOTAL, ALIGN_LEFT)
    sc(ws, r, 6, grand_total, Font(name="Arial", size=11, bold=True, color="1a1a2e"), FILL_TOTAL, ALIGN_AMOUNT, '#,##0')
    r += 2

    # ─── Payment Terms ───
    sc(ws, r, 1, "Payment Terms / 付款方式:", Font(name="Arial", size=9, bold=True), None, ALIGN_LEFT)
    r += 1
    terms = [
        "50% 訂金 (Deposit upon order)",
        "30% 交貨前 (Before delivery)",
        "20% 安裝驗收後 (After installation & acceptance)",
    ]
    for t in terms:
        ws.merge_cells(f"A{r}:F{r}")
        sc(ws, r, 1, f"  {t}", Font(name="Arial", size=9), None, ALIGN_LEFT)
        r += 1
    r += 1
    ws.merge_cells(f"A{r}:F{r}")
    sc(ws, r, 1, "Validity / 有效期: 30 days / 30 天", Font(name="Arial", size=9, color="555555"), None, ALIGN_LEFT)
    r += 1
    ws.merge_cells(f"A{r}:F{r}")
    sc(ws, r, 1, "Delivery / 交貨期: 4-6 weeks after order confirmation / 確認訂單後 4-6 週", Font(name="Arial", size=9, color="555555"), None, ALIGN_LEFT)

    # ─── Save ───
    wb.save(OUTPUT_FILE)
    print(f"✅ Quotation saved: {OUTPUT_FILE}")
    print(f"   Total: HKD ${grand_total:,}")

    # ─── Summary ───
    print(f"\n{'='*60}")
    print(f"  Pui Ching — Entrance Display Shelving System Quotation")
    print(f"{'='*60}")
    sections = [
        ("A. 層架模組系統 / Shelf Module System", m(304500)),
        ("B. 鋁合金立柱系統 / Aluminium Pole System", m(150000)),
        ("C. 五金配件 / Hardware & Fixings", m(67600)),
        ("D. 智能玻璃面板 / Smart Glass & Acrylic Panels", m(111600)),
        ("E. 圖像及表面處理 / Graphics & Finishing", m(140000)),
        ("F. 加工製作 / Fabrication & Assembly", m(180000)),
        ("G. 現場安裝 / Site Installation", m(156000)),
        ("H. 運輸物流 / Transport & Logistics", m(27000)),
        ("I. 設計及管理 / Design & Management", m(95000)),
    ]
    for name, amt in sections:
        pct = amt / grand_total * 100
        print(f"  {name:50s}  HKD ${amt:>8,}  ({pct:5.1f}%)")
    print(f"  {'─'*50}")
    print(f"  {'TOTAL':50s}  HKD ${grand_total:>8,}")

if __name__ == "__main__":
    generate()
