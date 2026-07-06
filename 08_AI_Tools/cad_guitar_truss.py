"""
Zoe/Taiwan — Guitar Truss CAD-style Production Drawing
========================================================
Generates A3 production drawing matching 08 Collective's
fabrication standard: white bg, black linework, title block,
multi-view projections, material callouts, grid refs.

Output: SVG + HTML wrapper for browser/print.
"""

import sys
import os

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from importlib import import_module
# Can't use "from 08_AI_Tools..." due to module name starting with digit
drawing_cad = import_module("08_AI_Tools.drawing_cad")
CADDrawing = drawing_cad.CADDrawing
View = drawing_cad.View
dim_horizontal = drawing_cad.dim_horizontal
dim_vertical = drawing_cad.dim_vertical
center_line = drawing_cad.center_line
material_callout = drawing_cad.material_callout

# ── Specification from GUITAR (UPDATED).pdf analysis ──

# Guitar Truss dimensions (mm)
HEAD_W = 1000     # Headstock width
HEAD_H = 800      # Headstock height
NECK_W = 800      # Neck width
NECK_L = 3400     # Neck length
BODY_UPPER_W = 2800  # Upper bout max width
BODY_LOWER_W = 3000  # Lower bout max width
WAIST_W = 1100    # Waist width
BODY_L = 3420     # Body total length
TOTAL_H = 8100    # Total height
THICKNESS = 600   # Truss structure depth

# Scale factors
SF_FRONT = 3.8   # px per mm for front view
SF_SIDE = 3.8    # px per mm for side view

# Hanging points (Y-position relative to top of drawing)
HP_Y = [82, 250, 350, 470, 660, 810]
HP_LABELS = ["HP-1", "HP-2", "HP-3", "HP-4", "HP-5", "HP-6"]

# Material specs
MATERIAL_NOTES = [
    "!所有尺寸以 mm 為單位 · 未標註公差: ±2mm",
    "主結構: 鋁合金 6061-T6 · 主桿 Ø50×3mm · 斜撐 Ø12×2mm",
    "焊接: TIG 焊接 · 焊條 ER4043 · 焊道 Class B 檢驗",
    "表面處理: 黑色靜電粉體塗裝 · 膜厚 60-80μm · ASTM B117 鹽霧測試 72hr",
    "!吊掛點 HP-1~HP-6 各點 SWL 250kg · 安全係數 ≥5:1",
    "鋼索: Ø6mm 7×19 鍍鋅鋼索含 PVC 保護套 · 破斷強度 ~1,800kg",
    "現場安裝前需進行 1.5 倍載重測試 · 維持 30 分鐘",
    "連接件必須使用同廠牌原廠接頭 · 不可混用",
    "All dimensions in mm · Tolerances ±2mm unless noted",
    "Material: Aluminum Alloy 6061-T6 per ASTM B221",
]

BOM = [
    ["1", "~42 m", "M", "Truss 主桿", "Ø50×3mm 6061-T6 鋁合金圓管"],
    ["2", "~65 m", "M", "Truss 斜撐", "Ø12×2mm 6061-T6 鋁合金圓管"],
    ["3", "30", "PCS", "T 型接頭", "鋁合金壓鑄 配 M8 螺絲孔"],
    ["4", "16", "PCS", "L 型接頭", "鋁合金壓鑄 配 M8 螺絲孔"],
    ["5", "8", "PCS", "X 型十字接頭", "鋁合金壓鑄 四向連接"],
    ["6", "200", "PCS", "連接螺絲", "M8×25 SUS304 不鏽鋼"],
    ["7", "120", "PCS", "彈簧墊圈", "M8 SUS304"],
    ["8", "6", "PCS", "電動葫蘆", "250kg 110V 含限位開關"],
    ["9", "6", "PCS", "鍍鋅鋼索", "Ø6mm×5m 7×19 含保護套 + 鋁壓頭"],
    ["10", "6", "PCS", "馬達吊掛板", "10mm 鋼板 熱浸鍍鋅"],
    ["11", "2", "PCS", "補強板 (琴頭)", "3mm 鋁板 6061-T6"],
    ["12", "4", "PCS", "補強斜撐 (琴頸接琴身)", "3mm 鋁板 6061-T6 折彎"],
    ["13", "1", "LOT", "粉體塗裝 (黑色)", "膜厚 60-80μm 砂面"],
    ["14", "1", "LOT", "現場安裝", "含 4 人 × 3 天"],
]


def generate_guitar_front_view():
    """Generate SVG content for guitar truss front view."""
    svg = []
    cx = 460  # center X of guitar

    # ── Headstock ──
    svg.append(
        f'<path d="M{cx-50},105 Q{cx-50},95 {cx-40},90 L{cx-20},82 '
        f'Q{cx-10},79 {cx},78 Q{cx+10},79 {cx+20},82 L{cx+40},90 '
        f'Q{cx+50},95 {cx+50},105 L{cx+50},165 Q{cx+50},175 {cx+40},180 '
        f'L{cx+20},185 Q{cx+10},187 {cx},188 Q{cx-10},187 {cx-20},185 '
        f'L{cx-40},180 Q{cx-50},175 {cx-50},165 Z" class="geom-fill"/>'
    )

    # Tuning pegs (left 3)
    for i, py in enumerate([115, 135, 155]):
        px = cx - 52
        svg.append(f'<circle cx="{px}" cy="{py}" r="4" fill="none" stroke="#333" stroke-width="0.8"/>')
        svg.append(f'<line x1="{px}" y1="{py}" x2="{px-13}" y2="{py}" stroke="#333" stroke-width="0.5"/>')

    # Tuning pegs (right 3)
    for i, py in enumerate([115, 135, 155]):
        px = cx + 52
        svg.append(f'<circle cx="{px}" cy="{py}" r="4" fill="none" stroke="#333" stroke-width="0.8"/>')
        svg.append(f'<line x1="{px}" y1="{py}" x2="{px+13}" y2="{py}" stroke="#333" stroke-width="0.5"/>')

    # ── Neck ──
    n_left = cx - 40
    n_right = cx + 40
    n_top = 188
    n_bot = n_top + NECK_L // int(SF_FRONT)  # ~895

    svg.append(f'<rect x="{n_left}" y="{n_top}" width="80" height="{n_bot-n_top}" class="geom-fill"/>')

    # Neck truss grid (diagonal bracing)
    for gy in range(n_top + 30, n_bot - 20, 60):
        svg.append(f'<line x1="{n_left}" y1="{gy}" x2="{n_right}" y2="{gy+30}" class="hidden"/>')
        svg.append(f'<line x1="{n_left}" y1="{gy+30}" x2="{n_right}" y2="{gy}" class="hidden"/>')

    # Horizontal battens
    for gy in range(n_top + 15, n_bot - 10, 40):
        svg.append(f'<line x1="{n_left}" y1="{gy}" x2="{n_right}" y2="{gy}" class="geom-thin" stroke-dasharray="4,2"/>')

    # ── Body (Upper Bout) ──
    body_top = n_bot
    ub_top = body_top
    ub_left = cx - 140
    ub_right = cx + 140

    svg.append(
        f'<path d="M{cx-40},{body_top} Q{cx-50},{body_top+2} {cx-80},{body_top+12} '
        f'Q{cx-120},{body_top+27} {cx-140},{body_top+47} '
        f'Q{cx-165},{body_top+72} {cx-170},{body_top+102} '
        f'Q{cx-175},{body_top+132} {cx-155},{body_top+157} '
        f'Q{cx-135},{body_top+177} {cx-105},{body_top+182} '
        f'Q{cx-80},{body_top+184} {cx-60},{body_top+182} '
        f'L{cx+60},{body_top+182} '
        f'Q{cx+80},{body_top+184} {cx+105},{body_top+182} '
        f'Q{cx+135},{body_top+177} {cx+155},{body_top+157} '
        f'Q{cx+175},{body_top+132} {cx+170},{body_top+102} '
        f'Q{cx+165},{body_top+72} {cx+140},{body_top+47} '
        f'Q{cx+120},{body_top+27} {cx+80},{body_top+12} '
        f'Q{cx+50},{body_top+2} {cx+40},{body_top} Z" class="geom-fill"/>'
    )

    # Waist
    waist_y = body_top + 182
    svg.append(
        f'<path d="M{cx-60},{waist_y} Q{cx-50},{waist_y+20} {cx-30},{waist_y+30} '
        f'Q{cx-10},{waist_y+38} {cx},{waist_y+40} '
        f'Q{cx+10},{waist_y+38} {cx+30},{waist_y+30} '
        f'Q{cx+50},{waist_y+20} {cx+60},{waist_y}" class="geom-fill"/>'
    )

    # Lower Bout
    lb_y = waist_y + 40
    svg.append(
        f'<path d="M{cx-60},{lb_y} Q{cx-80},{lb_y+5} {cx-110},{lb_y+15} '
        f'Q{cx-150},{lb_y+30} {cx-170},{lb_y+55} '
        f'Q{cx-190},{lb_y+85} {cx-180},{lb_y+115} '
        f'Q{cx-170},{lb_y+140} {cx-140},{lb_y+150} '
        f'Q{cx-110},{lb_y+158} {cx-80},{lb_y+160} '
        f'L{cx+80},{lb_y+160} '
        f'Q{cx+110},{lb_y+158} {cx+140},{lb_y+150} '
        f'Q{cx+170},{lb_y+140} {cx+180},{lb_y+115} '
        f'Q{cx+190},{lb_y+85} {cx+170},{lb_y+55} '
        f'Q{cx+150},{lb_y+30} {cx+110},{lb_y+15} '
        f'Q{cx+80},{lb_y+5} {cx+60},{lb_y} Z" class="geom-fill"/>'
    )

    # Body truss grid
    upper_bout_end = body_top + 182
    lower_bout_end = lb_y + 160

    # Upper bout diagonals
    for gy in range(body_top + 30, upper_bout_end - 20, 35):
        offset = int((gy - body_top) * 0.15)
        l = cx - 130 + offset
        r = cx + 130 - offset
        if l < n_left:
            l = n_left
        if r > n_right:
            r = n_right
        svg.append(f'<line x1="{l}" y1="{gy}" x2="{r}" y2="{gy+20}" class="hidden"/>')
        svg.append(f'<line x1="{l}" y1="{gy+20}" x2="{r}" y2="{gy}" class="hidden"/>')

    # Lower bout diagonals
    for gy in range(lb_y + 30, lower_bout_end - 20, 40):
        offset = int((gy - lb_y) * 0.12)
        l = cx - 140 + offset
        r = cx + 140 - offset
        svg.append(f'<line x1="{l}" y1="{gy}" x2="{r}" y2="{gy+25}" class="hidden"/>')
        svg.append(f'<line x1="{l}" y1="{gy+25}" x2="{r}" y2="{gy}" class="hidden"/>')

    # Horizontal battens body
    for gy in range(body_top + 20, upper_bout_end, 40):
        svg.append(f'<line x1="{cx-120}" y1="{gy}" x2="{cx+120}" y2="{gy}" class="geom-thin" stroke-dasharray="4,2"/>')
    for gy in range(lb_y + 20, lower_bout_end, 40):
        svg.append(f'<line x1="{cx-140}" y1="{gy}" x2="{cx+140}" y2="{gy}" class="geom-thin" stroke-dasharray="4,2"/>')

    # ── Hanging Points ──
    hp_positions = [
        (cx, 82, "HP-1"),     # Top of headstock
        (cx, 250, "HP-2"),    # Neck 1/3
        (cx, 350, "HP-3"),    # Neck 2/3
        (cx, 470, "HP-4"),    # Neck bottom
        (cx, 660, "HP-5"),    # Body center
        (cx, 810, "HP-6"),    # Body bottom
    ]
    for hx, hy, hlabel in hp_positions:
        svg.append(f'<circle cx="{hx}" cy="{hy}" r="9" fill="#e74c3c" stroke="#fff" stroke-width="2.5"/>')
        svg.append(f'<circle cx="{hx}" cy="{hy}" r="3" fill="#fff"/>')
        svg.append(f'<text x="{hx}" y="{hy-12}" text-anchor="middle" font-size="7" fill="#c00" font-weight="700">{hlabel}</text>')

    # ── Center line ──
    svg.append(center_line(cx, 55, cx, 880))

    # ── Dimensions ──
    # Total height
    svg.extend(dim_vertical(cx + 150, 78, 870, "總高 8100 mm"))
    # Headstock width
    svg.extend(dim_horizontal(70, cx - 50, cx + 50, "1000 mm"))
    # Neck width
    svg.extend(dim_horizontal(195, n_left, n_right, "800 mm"))
    # Upper bout width
    svg.extend(dim_horizontal(body_top + 102, cx - 170, cx + 170, "2800 mm"))
    # Lower bout width
    svg.extend(dim_horizontal(lb_y + 80, cx - 180, cx + 180, "3000 mm"))
    # Waist width
    svg.extend(dim_horizontal(upper_bout_end + 22, cx - 60, cx + 60, "1100 mm"))
    # Neck length
    svg.extend(dim_vertical(cx + 200, n_top, body_top, "琴頸 3400 mm"))
    # Body length
    svg.extend(dim_vertical(cx + 200, body_top, lower_bout_end + 5, "琴身 3420 mm"))

    # ── Material callouts ──
    svg.append(material_callout(cx + 100, 110, "鋁合金 Truss Ø50×3mm"))
    svg.append(material_callout(cx + 130, 300, "斜撐 Ø12×2mm 6061-T6"))
    svg.append(material_callout(cx + 120, 720, "鋁合金 Truss 網格結構"))

    # ── Load annotation ──
    svg.append(f'<text x="30" y="525" font-size="7" fill="#333" font-weight="700">吊掛系統:</text>')
    svg.append(f'<text x="30" y="538" font-size="6.5" fill="#555">各點工作荷重 ~58 kg (總重 350kg ÷ 6 點) · 安全係數 5:1</text>')
    svg.append(f'<text x="30" y="551" font-size="6.5" fill="#555">Ø6mm 7×19 鍍鋅鋼索破斷強度 ≈ 1,800 kg &gt; 290 kg ✓</text>')

    return svg


def generate_guitar_side_view():
    """Generate SVG content for side/right view."""
    svg = []
    vx = 780  # left edge of side view

    # Main profile rect
    svg.append(f'<rect x="{vx}" y="82" width="60" height="788" fill="none" stroke="#111" stroke-width="1.5" rx="3"/>')

    # Headstock side
    svg.append(f'<rect x="{vx}" y="82" width="60" height="110" fill="#f7f5f0" stroke="#111" stroke-width="1.5" rx="3"/>')

    # Neck side
    svg.append(f'<rect x="{vx}" y="192" width="60" height="340" fill="#f7f5f0" stroke="#111" stroke-width="1.5"/>')

    # Upper bout side
    svg.append(
        f'<path d="M{vx},532 Q{vx-5},540 {vx-8},555 Q{vx-12},575 {vx-12},595 '
        f'Q{vx-12},620 {vx-5},640 Q{vx},650 {vx+5},655 '
        f'L{vx+55},655 Q{vx+60},650 {vx+65},640 '
        f'Q{vx+72},620 {vx+72},595 Q{vx+72},575 {vx+68},555 '
        f'Q{vx+65},540 {vx+60},532 Z" fill="#f7f5f0" stroke="#111" stroke-width="1.5"/>'
    )

    # Waist side
    svg.append(
        f'<path d="M{vx+5},655 Q{vx+10},680 {vx+20},695 Q{vx+30},705 {vx+40},710 '
        f'L{vx+60},710 Q{vx+70},705 {vx+75},695 '
        f'Q{vx+80},680 {vx+80},655" fill="#f7f5f0" stroke="#111" stroke-width="1.5"/>'
    )

    # Lower bout side
    svg.append(
        f'<path d="M{vx+40},710 Q{vx+30},715 {vx+15},730 Q{vx-2},755 {vx-5},785 '
        f'Q{vx-8},815 {vx},840 Q{vx+8},860 {vx+30},868 '
        f'L{vx+70},868 Q{vx+92},860 {vx+100},840 '
        f'Q{vx+108},815 {vx+105},785 Q{vx+102},755 {vx+85},730 '
        f'Q{vx+70},715 {vx+60},710 Z" fill="#f7f5f0" stroke="#111" stroke-width="1.5"/>'
    )

    # Side truss diagonals
    for gy in [230, 260, 320, 350, 410, 440]:
        svg.append(f'<line x1="{vx}" y1="{gy}" x2="{vx+60}" y2="{gy+30}" class="hidden"/>')

    # Depth dimensions
    svg.extend(dim_horizontal(870, vx, vx + 60, "600 mm 深"))

    # Truss section callout
    svg.append(material_callout(vx + 65, 150, "Truss 結構深度 500mm"))

    # HP through-annotation
    svg.append(
        f'<text x="{vx+65}" y="95" font-size="6.5" fill="#c00">'
        f'▲ 吊掛點 HP-1~HP-6 貫穿 Truss 中心</text>'
    )

    return svg


def generate_section_aa():
    """Generate A-A section view of truss cross-section."""
    svg = []
    sx, sy = 760, 215

    # Outer frame 500x500
    svg.append(f'<rect x="{sx}" y="{sy}" width="120" height="120" fill="none" stroke="#111" stroke-width="1.5" rx="2"/>')

    # Four corner chords Ø50
    corners = [(sx+15, sy+15), (sx+105, sy+15), (sx+15, sy+105), (sx+105, sy+105)]
    for cx_, cy_ in corners:
        svg.append(f'<circle cx="{cx_}" cy="{cy_}" r="18" fill="#f7f5f0" stroke="#111" stroke-width="1.2"/>')
        svg.append(f'<circle cx="{cx_}" cy="{cy_}" r="12" fill="none" stroke="#999" stroke-width="0.5"/>')
        svg.append(f'<text x="{cx_}" y="{cy_+3}" text-anchor="middle" font-size="6" fill="#333">Ø50</text>')

    # Diagonals
    svg.append(f'<line x1="{sx+15}" y1="{sy+33}" x2="{sx+105}" y2="{sy+87}" stroke="#555" stroke-width="0.8"/>')
    svg.append(f'<line x1="{sx+105}" y1="{sy+33}" x2="{sx+15}" y2="{sy+87}" stroke="#555" stroke-width="0.8"/>')

    # Weld symbols
    svg.append(f'<path d="M{sx+20},{sy+33} L{sx+30},{sy+33}" class="weld"/>')
    svg.append(f'<path d="M{sx+100},{sy+87} L{sx+90},{sy+87}" class="weld"/>')
    svg.append(f'<path d="M{sx+100},{sy+33} L{sx+90},{sy+33}" class="weld"/>')
    svg.append(f'<path d="M{sx+20},{sy+87} L{sx+30},{sy+87}" class="weld"/>')

    # Dimensions
    svg.extend(dim_horizontal(sy - 5, sx, sx + 120, "500 mm"))
    svg.extend(dim_vertical(sx - 10, sy, sy + 120, "500 mm"))

    # Material annotation
    svg.append(material_callout(sx + 130, sy + 20, "主桿 Ø50×3mm 6061-T6"))
    svg.append(material_callout(sx + 130, sy + 40, "斜撐 Ø12×2mm 6061-T6"))
    svg.append(material_callout(sx + 130, sy + 60, "TIG 焊接 ER4043"))

    # Hatch fill on frame
    svg.append(f'<path d="M{sx+33},{sy+15} L{sx+87},{sy+15} L{sx+87},{sy+105} L{sx+33},{sy+105} Z" class="hatch"/>')

    return svg


def generate_detail_b():
    """Detail B: Headstock-to-neck joint."""
    svg = []
    dx, dy = 750, 392

    svg.append(
        f'<path d="M{dx+50},{dy+18} L{dx+100},{dy+18} '
        f'Q{dx+110},{dy+18} {dx+115},{dy+28} L{dx+115},{dy+48} L{dx+50},{dy+48} Z" '
        f'fill="#f7f5f0" stroke="#111" stroke-width="1.2"/>'
    )
    svg.append(
        f'<path d="M{dx+50},{dy+48} L{dx+115},{dy+48} L{dx+115},{dy+68} '
        f'Q{dx+115},{dy+78} {dx+105},{dy+83} L{dx+50},{dy+83} Z" '
        f'fill="#f7f5f0" stroke="#111" stroke-width="1.2"/>'
    )

    # Stiffener plate
    svg.append(
        f'<rect x="{dx+60}" y="{dy+38}" width="30" height="30" '
        f'fill="none" stroke="#c00" stroke-width="0.8" stroke-dasharray="3,2"/>'
    )
    svg.append(material_callout(dx + 95, dy + 52, "3mm 補強板 6061-T6"))

    # T-joint connector
    svg.append(
        f'<rect x="{dx+100}" y="{dy+33}" width="10" height="20" '
        f'fill="#e8ddd0" stroke="#333" stroke-width="0.8"/>'
    )
    svg.append(material_callout(dx + 115, dy + 42, "T 型鋁接頭"))

    # Notes
    notes_y = dy + 100
    notes = [
        "1. 琴頭與琴頸 Truss 使用 T 型鋁合金接頭連接，M8×25 螺絲鎖固",
        "2. 內側加 3mm 鋁板補強（焊接 + 螺絲固定）",
        "3. 焊接後打磨平整，表面黑色粉體塗裝 60-80μm",
    ]
    for i, n in enumerate(notes):
        svg.append(f'<text x="{dx+10}" y="{notes_y+i*13}" font-size="6" fill="#555">{n}</text>')

    return svg


def generate_detail_c():
    """Detail C: Neck-to-body joint."""
    svg = []
    dx, dy = 750, 555

    svg.append(
        f'<path d="M{dx+30},{dy+30} L{dx+80},{dy+30} '
        f'Q{dx+90},{dy+30} {dx+95},{dy+40} L{dx+95},{dy+95} L{dx+30},{dy+95} Z" '
        f'fill="#f7f5f0" stroke="#111" stroke-width="1.2"/>'
    )
    svg.append(
        f'<path d="M{dx+95},{dy+40} L{dx+150},{dy+40} '
        f'Q{dx+160},{dy+40} {dx+165},{dy+50} L{dx+165},{dy+95} L{dx+95},{dy+95} Z" '
        f'fill="#f7f5f0" stroke="#111" stroke-width="1.2"/>'
    )

    # Joint face
    svg.append(f'<line x1="{dx+95}" y1="{dy+30}" x2="{dx+95}" y2="{dy+95}" stroke="#c00" stroke-width="0.8" stroke-dasharray="4,2"/>')

    # Diagonal bracing
    svg.append(f'<line x1="{dx+50}" y1="{dy+60}" x2="{dx+115}" y2="{dy+75}" stroke="#555" stroke-width="0.6"/>')
    svg.append(f'<line x1="{dx+50}" y1="{dy+75}" x2="{dx+115}" y2="{dy+60}" stroke="#555" stroke-width="0.6"/>')

    # Notes
    notes_y = dy + 115
    notes = [
        "1. 琴頸與琴身 Truss 採用雙斜撐補強，4×M8 螺絲固定",
        "2. 接合面兩側加 3mm 鋁板補強（焊接）",
        "3. 所有焊接點標記 W1-W8，需 100% 目視檢查",
    ]
    for i, n in enumerate(notes):
        svg.append(f'<text x="{dx+10}" y="{notes_y+i*13}" font-size="6" fill="#555">{n}</text>')

    return svg


def generate_rigging_detail():
    """Generate hanging point detail."""
    svg = []
    dx, dy = 35, 540

    svg.append(f'<text x="{dx}" y="{dy}" font-size="7" font-weight="700" fill="#333">吊掛點詳細 (TYP. HP-1~HP-6)</text>')

    # Hoist block
    svg.append(f'<rect x="{dx+20}" y="{dy+10}" width="40" height="30" fill="#f7f5f0" stroke="#111" stroke-width="1.2" rx="2"/>')
    svg.append(f'<text x="{dx+40}" y="{dy+28}" text-anchor="middle" font-size="6" fill="#333">電動葫蘆</text>')
    svg.append(f'<text x="{dx+40}" y="{dy+36}" text-anchor="middle" font-size="5" fill="#555">250kg</text>')

    # Shackle
    svg.append(f'<path d="M{dx+30},{dy+8} Q{dx+40},{dy} {dx+50},{dy+8}" fill="none" stroke="#333" stroke-width="1.5"/>')
    svg.append(f'<line x1="{dx+40}" y1="{dy}" x2="{dx+40}" y2="{dy-8}" stroke="#333" stroke-width="1"/>')

    # Steel cable
    svg.append(f'<line x1="{dx+40}" y1="{dy+40}" x2="{dx+40}" y2="{dy+65}" stroke="#333" stroke-width="0.8" stroke-dasharray="3,2"/>')

    # Connection plate
    svg.append(f'<rect x="{dx+25}" y="{dy+65}" width="30" height="12" fill="#ddd" stroke="#333" stroke-width="0.8"/>')
    svg.append(f'<text x="{dx+40}" y="{dy+74}" text-anchor="middle" font-size="5" fill="#333">吊板</text>')

    # Labels
    label_items = [
        (dx+70, dy+14, "10mm 鋼板吊掛板 熱浸鍍鋅"),
        (dx+70, dy+28, "鍍鋅鋼索 Ø6mm 7×19"),
        (dx+70, dy+42, "安全係數 5:1 · SWL 250kg"),
        (dx+70, dy+56, "含限位開關 &amp; 緊急停止"),
    ]
    for lx, ly, text in label_items:
        svg.append(f'<text x="{lx}" y="{ly}" font-size="6" fill="#555">{text}</text>')

    # Callout arrow to hoist
    svg.append(f'<line x1="{dx+60}" y1="{dy+25}" x2="{dx+68}" y2="{dy+20}" stroke="#c00" stroke-width="0.5"/>')

    return svg


# ═══════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════

def generate(output_dir):
    """Generate the full production drawing SVG + HTML."""

    # ── Create CAD Drawing ──
    dwg = CADDrawing(
        title="GUITAR TRUSS STRUCTURAL DRAWING",
        subtitle="吉他 Truss 結構製作圖 — Zoe / Taiwan",
        dwg_no="GT-001",
        revision="v3.0",
        scale="1:40 (main views)",
        date="2026.06.25",
        client="Zoe",
        project="Taiwan Guitar Truss",
        designer="TREE",
        checker="",
        approved="",
    )

    # Add BOM
    dwg.add_bom(BOM)

    # Add notes
    dwg.add_notes(MATERIAL_NOTES)

    # Add revision history
    dwg.add_revision("v1.0", "2026.06.20", "初版 — 參考 PDF 技術圖")
    dwg.add_revision("v2.0", "2026.06.23", "加入側視圖、剖面 A-A、詳細 B/C")
    dwg.add_revision("v3.0", "2026.06.25", "CAD 標準格式重製 — 配合廠內生產圖標準")

    # ── FRONT VIEW ──
    front_svg = generate_guitar_front_view()
    front_view = View("FRONT / 正視圖", 30, 55, 700, 430,
                      scale="1:40", svg_content=front_svg)
    dwg.add_view(front_view)

    # ── SIDE VIEW ──
    side_svg = generate_guitar_side_view()
    side_view = View("RIGHT SIDE / 右側視圖", 740, 55, 180, 430,
                     scale="1:40", svg_content=side_svg)
    dwg.add_view(side_view)

    # ── SECTION A-A ──
    section_svg = generate_section_aa()
    section_view = View("SECTION A-A / 剖面 A-A", 740, 200, 200, 160,
                        scale="1:5", svg_content=section_svg)
    dwg.add_view(section_view)

    # ── DETAIL B ──
    detail_b_svg = generate_detail_b()
    detail_b_view = View("DETAIL B / 詳細 B (琴頭接合)", 740, 370, 210, 140,
                         scale="1:10", svg_content=detail_b_svg)
    dwg.add_view(detail_b_view)

    # ── DETAIL C ──
    detail_c_svg = generate_detail_c()
    detail_c_view = View("DETAIL C / 詳細 C (琴頸接合)", 740, 530, 210, 140,
                         scale="1:10", svg_content=detail_c_svg)
    dwg.add_view(detail_c_view)

    # ── Section callout on front view ──
    section_callout = (
        f'<g id="section-callout">'
        f'<line x1="210" y1="450" x2="280" y2="450" class="section"/>'
        f'<line x1="610" y1="450" x2="680" y2="450" class="section"/>'
        f'<circle cx="280" cy="450" r="7" fill="#fff" stroke="#c00" stroke-width="0.8"/>'
        f'<text x="280" y="452.5" text-anchor="middle" font-size="7" font-weight="700" fill="#c00">A</text>'
        f'<circle cx="680" cy="450" r="7" fill="#fff" stroke="#c00" stroke-width="0.8"/>'
        f'<text x="680" y="452.5" text-anchor="middle" font-size="7" font-weight="700" fill="#c00">A</text>'
        f'</g>'
    )
    dwg.custom_svg_before.append(section_callout)

    # ── Rigging detail (bottom-left area) ──
    rigging_svg = '\n'.join(generate_rigging_detail())
    dwg.custom_svg_before.append(f'<g id="rigging-detail">{rigging_svg}</g>')

    # ── Generate SVG ──
    svg = dwg.generate()

    # ── Save SVG ──
    svg_path = os.path.join(output_dir, "Guitar_Truss_工程圖_v3.svg")
    with open(svg_path, 'w', encoding='utf-8') as f:
        f.write(svg)

    # ── Save HTML wrapper ──
    html_path = os.path.join(output_dir, "Guitar_Truss_製作圖_v3.html")
    html = f"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Zoe Taiwan — Guitar Truss 結構製作圖 v3 (CAD 標準)</title>
<style>
  @page {{ margin: 3mm; size: A3 landscape; }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #555; font-family: 'Arial', 'Microsoft JhengHei', sans-serif; }}
  .page {{ width: 1190px; margin: 10px auto; background: #fff; box-shadow: 0 4px 20px rgba(0,0,0,0.3); }}
  .page svg {{ display: block; width: 1190px; height: 841px; }}
  @media print {{
    body {{ background: #fff; }}
    .page {{ box-shadow: none; margin: 0; }}
  }}
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
    output = "/Volumes/Apollo Sync Folder/08collective/Zoe/Taiwan/"
    os.makedirs(output, exist_ok=True)
    generate(output)
