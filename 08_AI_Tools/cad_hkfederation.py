"""
香港文聯 — Echoes of the Sui & Tang Exhibition CAD Drawing
===========================================================
Generates A3 production drawing matching 08 Collective's
fabrication standard. Based on quotation and reference drawings.

Exhibition: Hong Kong Central Library, Gallery 1-5
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from importlib import import_module
dc = import_module("08_AI_Tools.drawing_cad")
CADDrawing = dc.CADDrawing
View = dc.View
dim_horizontal = dc.dim_horizontal
dim_vertical = dc.dim_vertical
center_line = dc.center_line
material_callout = dc.material_callout

MATERIAL_NOTES = [
    "!所有尺寸以 mm 為單位 · 未標註公差: ±2mm",
    "展覽場地: Hong Kong Central Library · Gallery 1-5",
    "展牆結構: 輕鋼架 + 18mm 多層板面層 · 表面烤漆處理",
    "展示櫃: 木作結構 + 壓克力面板 + LED 燈條",
    "Truss: 200mm 鋁合金 Truss 系統 · 含連接件及吊掛點",
    "!電力配置: 所有插座需預留在展牆後方检修口",
    "紡織品: 法蘭絨 UV 輸出 · 含安裝框架",
    "展品台座: 木作烤漆 + 麻繩裝飾",
    "All dimensions in mm · Tolerances ±2mm unless noted",
    "Reference: CAD drawings scale A2 1:100 (see Drawing List)",
]

BOM = [
    ["1", "—", "sq.m", "展牆 Truss 框架", "200mm 鋁合金 Truss + 連接件"],
    ["2", "—", "sq.m", "輕鋼架結構", "含基礎固定 + 18mm 板面"],
    ["3", "—", "sq.m", "木作造型結構", "弧形/幾何造型木工"],
    ["4", "—", "sq.m", "烤漆處理", "木作表面烤漆"],
    ["5", "—", "sq.m", "木作面板", "平板木作貼面"],
    ["6", "—", "set", "LED 螢幕", "嵌入式 含安裝調試"],
    ["7", "—", "set", "燈光系統", "軌道燈/射燈/環境燈"],
    ["8", "—", "pc", "模特人台", "展覽用人台"],
    ["9", "—", "pc", "展示台座", "木作或壓克力"],
    ["10", "—", "sq.m", "法蘭絨印刷", "UV 輸出 + 安裝"],
    ["11", "—", "sq.m", "背板圖形", "木框 + 印刷圖形"],
    ["12", "—", "m", "麻繩裝飾", "裝飾麻繩"],
    ["13", "—", "lot", "電力工程", "配電佈線"],
    ["14", "—", "lot", "運輸安裝", "材料運輸 + 現場安裝"],
    ["15", "—", "lot", "拆卸清理", "展後拆除 + 場地清理"],
]


def generate_floor_plan():
    """Gallery floor plan layout."""
    svg = []
    gx, gy = 30, 30

    # Main gallery space
    gallery_w = 520
    gallery_h = 320
    svg.extend([
        f'<rect x="{gx}" y="{gy}" width="{gallery_w}" height="{gallery_h}" '
        f'class="geom" stroke-width="2"/>',
        f'<text x="{gx+4}" y="{gy+12}" font-size="6" fill="#666">Gallery 1-5</text>',
    ])

    # Exhibition wall sections (based on quotation data)
    walls = [
        # (x, y, w, h, label)
        (gx+20, gy+30, 180, 20, "Section A: 展牆 Rack + TV"),
        (gx+20, gy+70, 180, 20, "Section A (2): Rack + TV"),
        (gx+20, gy+130, 160, 20, "Section A (3): Platform"),
        (gx+20, gy+170, 240, 20, "Section A (4): Rack + TV (15.8m)"),
        (gx+20, gy+220, 80, 20, "A(5): Mannequin x13"),
        (gx+20, gy+250, 80, 20, "A(6): Socket Area"),
        (gx+220, gy+30, 200, 15, "Section B(1): Backdrop 9596L"),
        (gx+220, gy+55, 200, 15, "B(2): Rack+TV x11 2500L"),
        (gx+220, gy+80, 160, 15, "B(3): Platform+HEMP ROPE x6"),
        (gx+220, gy+110, 80, 15, "B(4): Mannequin x30"),
        (gx+220, gy+135, 80, 15, "B(5): Socket x6"),
        (gx+320, gy+170, 220, 40, "Section C: Projector+Truss 13600L"),
        (gx+320, gy+220, 220, 40, "Section C(2): Wooden Wall+Sticker"),
        (gx+320, gy+270, 100, 20, "C(3): Curtain Track"),
    ]

    for wx, wy, ww, wh, label in walls:
        svg.extend([
            f'<rect x="{wx}" y="{wy}" width="{ww}" height="{wh}" '
            f'class="geom-fill" stroke-width="0.8"/>',
            f'<text x="{wx+4}" y="{wy+wh//2+3}" font-size="5" fill="#444">{label}</text>',
        ])

    # Grid references
    for col in range(0, gallery_w+1, 100):
        x = gx + col
        svg.append(f'<text x="{x}" y="{gy+gallery_h+12}" text-anchor="middle" font-size="5" fill="#999">{col//100+1}</text>')
    for row in range(0, gallery_h+1, 100):
        y = gy + row
        svg.append(f'<text x="{gx-10}" y="{y+4}" text-anchor="end" font-size="5" fill="#999">{chr(65+row//100)}</text>')

    # Overall dimensions
    svg.extend(dim_horizontal(gy+gallery_h+30, gx, gx+gallery_w, "24,000 mm (Hall Width)"))
    svg.extend(dim_vertical(gx-20, gy, gy+gallery_h, "18,000 mm"))

    return svg


def generate_section_view():
    """Section A-A through gallery."""
    svg = []
    sx, sy = 600, 55

    # Ceiling
    svg.append(f'<rect x="{sx}" y="{sy}" width="400" height="8" fill="#ddd" stroke="#111" stroke-width="0.8"/>')
    svg.append(f'<text x="{sx+4}" y="{sy+6}" font-size="5" fill="#666">天花 Ceiling @ 4,500mm H</text>')

    # Wall Section A
    svg.append(f'<rect x="{sx+40}" y="{sy+30}" width="15" height="250" class="geom-fill" stroke-width="0.8"/>')
    svg.append(material_callout(sx+60, sy+50, "18mm 多层板 + 烤漆"))

    # Display rack with TV
    svg.append(f'<rect x="{sx+80}" y="{sy+60}" width="40" height="200" class="geom" stroke-width="1.2"/>')
    # TV
    svg.append(f'<rect x="{sx+85}" y="{sy+80}" width="30" height="50" class="geom-fill" stroke-width="0.8"/>')
    svg.append(f'<text x="{sx+100}" y="{sy+108}" text-anchor="middle" font-size="5" fill="#c00">42\"TV</text>')
    # Vinyle face
    svg.append(f'<line x1="{sx+80}" y1="{sy+60}" x2="{sx+120}" y2="{sy+60}" stroke="#111" stroke-width="0.8"/>')
    svg.append(f'<text x="{sx+100}" y="{sy+56}" text-anchor="middle" font-size="5" fill="#555">Vinyle 飾面</text>')

    # Platform
    svg.append(f'<rect x="{sx+80}" y="{sy+260}" width="80" height="15" fill="#ddd" stroke="#111" stroke-width="0.8"/>')
    svg.append(f'<text x="{sx+120}" y="{sy+271}" text-anchor="middle" font-size="5" fill="#555">Platform 300H</text>')

    # Dimensions
    svg.extend(dim_vertical(sx+25, sy+30, sy+280, "3500 mm (Wall H)"))
    svg.extend(dim_vertical(sx+165, sy+80, sy+265, "3000 mm (Rack+TV)"))
    svg.extend(dim_horizontal(sy+280, sx+80, sx+160, "10000 mm (Section width)"))

    # Section label
    svg.append(f'<text x="{sx+200}" y="{sy+15}" font-size="7" font-weight="700" fill="#333">剖面 A-A: Section A 展牆</text>')

    return svg


def generate_detail_display():
    """Display case detail."""
    svg = []
    dx, dy = 600, 340

    # Display pedestal
    svg.append(f'<rect x="{dx}" y="{dy+60}" width="120" height="80" class="geom" stroke-width="1.5"/>')
    # Pedestal top
    svg.append(f'<rect x="{dx-5}" y="{dy+55}" width="130" height="10" fill="#f0ead6" stroke="#111" stroke-width="0.8"/>')
    # Acrylic cover
    svg.append(f'<rect x="{dx+10}" y="{dy+10}" width="100" height="50" fill="none" stroke="#999" stroke-width="0.8" rx="2"/>')
    svg.append(f'<line x1="{dx+10}" y1="{dy+10}" x2="{dx+110}" y2="{dy+10}" class="hidden"/>')
    svg.append(f'<text x="{dx+60}" y="{dy+40}" text-anchor="middle" font-size="6" fill="#999">壓克力罩 Acrylic Cover</text>')

    # Interior item
    svg.append(f'<circle cx="{dx+60}" cy="{dy+100}" r="25" fill="none" stroke="#333" stroke-width="0.8"/>')
    svg.append(f'<text x="{dx+60}" y="{dy+103}" text-anchor="middle" font-size="5" fill="#555">展示品</text>')

    # Labels
    svg.append(material_callout(dx+140, dy+75, "木作烤漆底座"))
    svg.append(material_callout(dx+140, dy+90, "內置 LED 燈條"))

    # Dimensions
    svg.extend(dim_vertical(dx-12, dy+55, dy+140, "800 mm"))
    svg.extend(dim_horizontal(dy+145, dx, dx+120, "600 mm"))

    # Section label
    svg.append(f'<text x="{dx}" y="{dy-5}" font-size="7" font-weight="700" fill="#333">詳細: 展示台座 Display Pedestal</text>')
    svg.append(f'<text x="{dx}" y="{dy+175}" font-size="6" fill="#555">木作烤漆表面 · 可調整展示角度 · 含 LED 照明</text>')

    return svg


def generate_mannequin_detail():
    """Mannequin arrangement detail for Section B."""
    svg = []
    dx, dy = 600, 570

    # Mannequin row plan view
    svg.append(f'<text x="{dx}" y="{dy}" font-size="7" font-weight="700" fill="#333">詳細: Mannequin 配置 (Section B4 · x30)</text>')

    # Row of mannequins
    for i in range(5):
        mx = dx + 20 + i * 35
        # Human figure (simple oval)
        svg.append(f'<ellipse cx="{mx}" cy="{dy+30}" rx="10" ry="20" class="geom" stroke-width="0.8"/>')
        svg.append(f'<circle cx="{mx}" cy="{dy+14}" r="7" class="geom" stroke-width="0.8"/>')
        svg.append(f'<text x="{mx}" y="{dy+57}" text-anchor="middle" font-size="5" fill="#555">x6</text>')

    # Row dimension
    svg.extend(dim_horizontal(dy+65, dx+20, dx+160, "5 rows × 6 pcs = 30 人台"))

    # Notes
    svg.append(f'<text x="{dx}" y="{dy+85}" font-size="6" fill="#555">• Mannequin 底部配木製底座 Ø300mm</text>')
    svg.append(f'<text x="{dx}" y="{dy+98}" font-size="6" fill="#555">• 間距 ~1,500mm · 展品前置</text>')
    svg.append(f'<text x="{dx}" y="{dy+111}" font-size="6" fill="#555">• 含固定螺絲 + 保護圍欄 (如需要)</text>')

    return svg


def generate_truss_detail():
    """Truss + Projector detail for Section C."""
    svg = []
    dx, dy = 890, 55

    svg.append(f'<text x="{dx}" y="{dy}" font-size="7" font-weight="700" fill="#333">詳細: Truss + Projector (Section C)</text>')

    # Truss beam
    svg.append(f'<rect x="{dx}" y="{dy+20}" width="250" height="16" class="geom-fill" stroke-width="1.2" rx="3"/>')
    # Truss diagonal pattern
    for i in range(0, 250, 40):
        svg.append(f'<line x1="{dx+i}" y1="{dy+20}" x2="{dx+i+20}" y2="{dy+36}" stroke="#999" stroke-width="0.5"/>')
        svg.append(f'<line x1="{dx+i+20}" y1="{dy+20}" x2="{dx+i}" y2="{dy+36}" stroke="#999" stroke-width="0.5"/>')

    svg.append(material_callout(dx+260, dy+28, "200mm Truss"))
    svg.append(material_callout(dx+260, dy+40, "鋁合金 Truss 系統"))

    # Hanging rods
    svg.append(f'<line x1="{dx+30}" y1="{dy+36}" x2="{dx+30}" y2="{dy+100}" stroke="#555" stroke-width="0.8" stroke-dasharray="4,2"/>')
    svg.append(f'<line x1="{dx+220}" y1="{dy+36}" x2="{dx+220}" y2="{dy+100}" stroke="#555" stroke-width="0.8" stroke-dasharray="4,2"/>')

    # Projector
    svg.append(f'<rect x="{dx+90}" y="{dy+60}" width="70" height="30" class="geom" stroke-width="1.2" rx="2"/>')
    svg.append(f'<text x="{dx+125}" y="{dy+78}" text-anchor="middle" font-size="6" fill="#333">Projector</text>')
    # Lens
    svg.append(f'<circle cx="{dx+125}" cy="{dy+90}" r="6" fill="none" stroke="#333" stroke-width="0.8"/>')

    # Curtain
    svg.append(f'<path d="M{dx+40},{dy+100} Q{dx+60},{dy+130} {dx+80},{dy+100}" fill="none" stroke="#888" stroke-width="0.8" stroke-dasharray="3,2"/>')
    svg.append(f'<text x="{dx+60}" y="{dy+115}" text-anchor="middle" font-size="5" fill="#888">Curtain</text>')

    # Dimensions
    svg.extend(dim_horizontal(dy+36+12, dx, dx+250, "13600 mm (Truss span)"))
    svg.extend(dim_vertical(dx-8, dy+20, dy+90, "6500 mm"))

    svg.append(f'<text x="{dx}" y="{dy+135}" font-size="6" fill="#555">Truss 13600L × 200D × 200Hmm · 含吊掛投影機及窗簾軌道</text>')

    return svg


def generate(output_dir):
    dwg = CADDrawing(
        title="EXHIBITION PRODUCTION DRAWING",
        subtitle="Echoes of the Sui &amp; Tang Exhibition — 香港文聯 · Hong Kong Central Library",
        dwg_no="HKF-SUItang-001",
        revision="v1",
        scale="1:100 (plan), NTS (details)",
        date="2026.06.25",
        client="香港文聯 (HKF)",
        project="Echoes of the Sui & Tang Exhibition",
        designer="TREE",
        checker="",
        approved="",
    )

    dwg.add_bom(BOM)
    dwg.add_notes(MATERIAL_NOTES)
    dwg.add_revision("v1", "2026.06.25", "初版 — CAD 標準格式 · 配合廠內生產圖標準")

    # ── Floor Plan ──
    fp_svg = generate_floor_plan()
    fp_view = View("FLOOR PLAN / 平面配置圖", 30, 55, 550, 400,
                   scale="1:100", svg_content=fp_svg)
    dwg.add_view(fp_view)

    # ── Section A-A ──
    sec_svg = generate_section_view()
    sec_view = View("SECTION A-A / 剖面 A-A", 580, 55, 280, 310,
                    scale="1:50", svg_content=sec_svg)
    dwg.add_view(sec_view)

    # ── Display Detail ──
    disp_svg = generate_detail_display()
    disp_view = View("DETAIL: DISPLAY PEDESTAL / 展示台座詳圖", 580, 340, 280, 210,
                     scale="1:10", svg_content=disp_svg)
    dwg.add_view(disp_view)

    # ── Mannequin Detail ──
    man_svg = generate_mannequin_detail()
    man_view = View("DETAIL: MANNEQUIN LAYOUT / 人台配置", 580, 560, 280, 140,
                    scale="NTS", svg_content=man_svg)
    dwg.add_view(man_view)

    # ── Truss Detail ──
    truss_svg = generate_truss_detail()
    truss_view = View("DETAIL: TRUSS + PROJECTOR / Truss 投影機詳圖", 870, 55, 290, 160,
                      scale="1:50", svg_content=truss_svg)
    dwg.add_view(truss_view)

    # ── Generate SVG ──
    svg = dwg.generate()

    svg_path = os.path.join(output_dir, "HKF_SuiTang_Production_Drawing_v1.svg")
    html_path = os.path.join(output_dir, "HKF_SuiTang_製作圖_v1.html")

    with open(svg_path, 'w', encoding='utf-8') as f:
        f.write(svg)

    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>香港文聯 — Echoes of the Sui & Tang 製作圖 (CAD 標準)</title>
<style>
  @page {{ margin: 3mm; size: A3 landscape; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #555; font-family: 'Arial', 'Microsoft JhengHei', sans-serif; }}
  .page {{ width: 1190px; margin: 10px auto; background: #fff; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }}
  .page svg {{ display: block; width: 1190px; height: 841px; }}
  @media print {{ body {{ background: #fff; }} .page {{ box-shadow: none; margin: 0; }} }}
</style>
</head>
<body>
<div class="page">
{svg}
</div>
</body>
</html>"""
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f"✓ SVG: {svg_path}")
    print(f"✓ HTML: {html_path}")
    return svg_path, html_path


if __name__ == "__main__":
    output = "/Volumes/Apollo Sync Folder/08collective/香港文聯/"
    os.makedirs(output, exist_ok=True)
    generate(output)
