"""
YONEX 配電/燈具配置設計工具 — Interactive Floor Plan Editor
Serves on port 8893.  Based on CCTV designer pattern but specialized for
lighting and outlet/electrical layout with proper electrical symbols.
"""
import json, math, os, logging, textwrap
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
PDF_PATH = Path("/Users/aitree414/Documents/Yonex/Yonex for TREE/CAD/26.05.26-YONEX平面圖.pdf")
OUTPUT_DIR = BASE_DIR

# ── Symbol definitions ──────────────────────────────────────────────────

SYMBOLS = {
    "lighting": [
        {"id": "downlight",         "label": "嵌燈 Downlight",        "color": "#F39C12", "size": 14, "qty": 24},
        {"id": "track_light",       "label": "軌道燈 Track Light",    "color": "#E67E22", "size": 18, "qty": 12},
        {"id": "spotlight",         "label": "投射燈 Spotlight",      "color": "#F1C40F", "size": 14, "qty": 8},
        {"id": "pendant",           "label": "吊燈 Pendant",          "color": "#D4AC0D", "size": 16, "qty": 4},
        {"id": "linear",            "label": "線性燈 Linear",         "color": "#F0B27A", "size": 20, "qty": 6},
        {"id": "emergency_light",   "label": "緊急照明 Emergency",    "color": "#E74C3C", "size": 16, "qty": 3},
        {"id": "exit_sign",         "label": "出口標示 Exit",         "color": "#2ECC71", "size": 18, "qty": 1},
        {"id": "direction_sign",    "label": "避難方向 Direction",    "color": "#2ECC71", "size": 18, "qty": 1},
        {"id": "circuit_panel",     "label": "配電盤 Panel",          "color": "#C0392B", "size": 22, "qty": 1},
        {"id": "sub_panel",         "label": "分電盤 Sub-Panel",      "color": "#E74C3C", "size": 18, "qty": 2},
        {"id": "switch_1g",         "label": "單切開關 1G",           "color": "#5D6D7E", "size": 10, "qty": 6},
        {"id": "switch_2g",         "label": "雙切開關 2G",           "color": "#5D6D7E", "size": 14, "qty": 4},
        {"id": "dimmer",            "label": "調光器 Dimmer",         "color": "#85929E", "size": 10, "qty": 3},
        {"id": "sensor",            "label": "感應器 Sensor",         "color": "#AAB7B8", "size": 12, "qty": 4},
    ],
    "outlet": [
        {"id": "outlet_duplex",     "label": "雙插座 110V Duplex",    "color": "#9B59B6", "size": 14, "qty": 20},
        {"id": "outlet_quad",       "label": "四插座 110V Quad",      "color": "#8E44AD", "size": 18, "qty": 6},
        {"id": "outlet_usb",        "label": "USB 插座 USB+A",        "color": "#AF7AC5", "size": 14, "qty": 8},
        {"id": "outlet_220v",       "label": "220V 插座",             "color": "#E74C3C", "size": 14, "qty": 2},
        {"id": "floor_box",         "label": "地板插座 Floor Box",    "color": "#7D3C98", "size": 16, "qty": 4},
        {"id": "data_port",         "label": "資訊插座 RJ45",         "color": "#5B2C6F", "size": 12, "qty": 12},
        {"id": "hdmi_port",         "label": "HDMI 面板",             "color": "#6C3483", "size": 12, "qty": 6},
        {"id": "junction_box",      "label": "接線盒 J-Box",          "color": "#A93226", "size": 10, "qty": 8},
        {"id": "av_outlet",         "label": "AV 電源+訊號",          "color": "#FF9800", "size": 16, "qty": 10},
    ],
}

COLORS = {
    "blue":    (0.13, 0.59, 0.95),
    "green":   (0.30, 0.68, 0.31),
    "orange":  (1.00, 0.60, 0.00),
    "red":     (0.85, 0.15, 0.08),
    "purple":  (0.61, 0.35, 0.71),
    "yellow":  (0.95, 0.76, 0.06),
}

# ── Pre-populated suggested positions (based on quotation + equipment analysis) ──
# Format: [symbol_id, label, x_pdf, y_pdf, angle, circuit]

SUGGESTED_LIGHTS = [
    # === 入口 Entrance area ===
    ["track_light", "入口軌道燈1",   300, 570, 180, "L1"],
    ["track_light", "入口軌道燈2",   370, 570, 180, "L1"],
    ["track_light", "入口軌道燈3",   440, 570, 180, "L1"],
    ["downlight",   "入口嵌燈1",      320, 530, 0,   "L2"],
    ["downlight",   "入口嵌燈2",      390, 530, 0,   "L2"],
    ["downlight",   "入口嵌燈3",      460, 530, 0,   "L2"],
    ["downlight",   "入口嵌燈4",      530, 530, 0,   "L2"],
    # === TV Wall (入口處 – 10× TV) ===
    ["av_outlet",   "電視牆電源×10",  350, 600, 0,   "AV1"],
    # === 左展示區 Left Display ===
    ["track_light", "左區軌道燈1",    340, 400, 270, "L3"],
    ["track_light", "左區軌道燈2",    340, 450, 270, "L3"],
    ["downlight",   "左區嵌燈1",      300, 380, 0,   "L4"],
    ["downlight",   "左區嵌燈2",      300, 430, 0,   "L4"],
    ["spotlight",   "左區投射燈1",    380, 390, 45,  "L5"],
    ["spotlight",   "左區投射燈2",    380, 440, 45,  "L5"],
    # === 中展示區 Center Display ===
    ["track_light", "中區軌道燈1",    630, 370, 180, "L6"],
    ["track_light", "中區軌道燈2",    700, 370, 180, "L6"],
    ["track_light", "中區軌道燈3",    770, 370, 180, "L6"],
    ["downlight",   "中區嵌燈1",      630, 420, 0,   "L7"],
    ["downlight",   "中區嵌燈2",      700, 420, 0,   "L7"],
    ["downlight",   "中區嵌燈3",      770, 420, 0,   "L7"],
    ["spotlight",   "中區投射燈3",    700, 480, 90,  "L8"],
    # === 右展示區 Right Display ===
    ["track_light", "右區軌道燈1",    870, 400, 90,  "L9"],
    ["track_light", "右區軌道燈2",    870, 450, 90,  "L9"],
    ["downlight",   "右區嵌燈1",      840, 380, 0,   "L10"],
    ["downlight",   "右區嵌燈2",      840, 430, 0,   "L10"],
    ["spotlight",   "右區投射燈1",    920, 420, 225, "L11"],
    # === 網球區 Tennis ===
    ["linear",      "網球區線性燈1",   550, 600, 0,   "L12"],
    ["linear",      "網球區線性燈2",   650, 600, 0,   "L12"],
    ["downlight",   "網球區嵌燈1",    560, 560, 0,   "L13"],
    ["downlight",   "網球區嵌燈2",    640, 560, 0,   "L13"],
    # === 羽球區 Badminton ===
    ["linear",      "羽球區線性燈1",   500, 680, 0,   "L14"],
    ["linear",      "羽球區線性燈2",   600, 680, 0,   "L14"],
    ["linear",      "羽球區線性燈3",   700, 680, 0,   "L14"],
    ["downlight",   "羽球區嵌燈3",    550, 660, 0,   "L15"],
    ["downlight",   "羽球區嵌燈4",    650, 660, 0,   "L15"],
    # === 互動體驗區 Interactive ===
    ["spotlight",   "體驗區投射燈",    620, 540, 90,  "L16"],
    ["downlight",   "體驗區嵌燈",      580, 530, 0,   "L16"],
    # === 洽談區 Meeting ===
    ["pendant",     "洽談區吊燈",      800, 570, 0,   "L17"],
    ["downlight",   "洽談區嵌燈1",    780, 560, 0,   "L17"],
    ["downlight",   "洽談區嵌燈2",    820, 560, 0,   "L17"],
    # === 試衣間 Fitting ===
    ["downlight",   "試衣間嵌燈",      410, 200, 0,   "L18"],
    # === 左上儲藏室 Storage ===
    ["downlight",   "儲藏室嵌燈1",    380, 140, 0,   "L19"],
    ["downlight",   "儲藏室嵌燈2",    430, 140, 0,   "L19"],
    # === Emergency & Safety ===
    ["emergency_light", "緊急照明1",   320, 580, 0,   "EM1"],
    ["emergency_light", "緊急照明2",   700, 580, 0,   "EM2"],
    ["emergency_light", "緊急照明3",   500, 400, 0,   "EM3"],
    ["exit_sign",       "出口標示",    490, 320, 0,   "EM4"],
    ["direction_sign",  "避難方向燈",  470, 310, 0,   "EM5"],
    # === 配電盤 Panels ===
    ["circuit_panel",   "主配電盤",    280, 150, 0,   "MDP"],
    ["sub_panel",       "照明分電盤",  280, 180, 0,   "LP1"],
    ["sub_panel",       "插座分電盤",  310, 150, 0,   "OP1"],
    # === Switches ===
    ["switch_1g",   "入口開關",       280, 510, 0,   "S1"],
    ["switch_2g",   "左區開關",       280, 370, 0,   "S2"],
    ["switch_2g",   "中區開關",       600, 340, 0,   "S3"],
    ["switch_1g",   "右區開關",       950, 390, 0,   "S4"],
    ["switch_1g",   "儲藏室開關",     370, 170, 0,   "S5"],
    ["dimmer",      "洽談區調光",     830, 530, 0,   "D1"],
    ["sensor",      "儲藏室感應器",   410, 120, 0,   "SE1"],
    ["sensor",      "廁所感應器",     350, 180, 0,   "SE2"],
]

SUGGESTED_OUTLETS = [
    # === 入口 Entrance ===
    ["outlet_duplex", "入口插座1",     290, 560, 0,   "O1"],
    ["outlet_duplex", "入口插座2",     470, 560, 0,   "O1"],
    ["av_outlet",     "電視牆電源",    350, 590, 0,   "AV1"],
    # === 左展示區 Left Display (每面展示牆旁1組 × 4) ===
    ["outlet_duplex", "左展示區插座1",  290, 390, 0,   "O2"],
    ["outlet_duplex", "左展示區插座2",  290, 440, 0,   "O2"],
    ["outlet_duplex", "左展示區插座3",  410, 370, 0,   "O3"],
    ["outlet_duplex", "左展示區插座4",  410, 470, 0,   "O3"],
    # === 中展示區 Center Display ===
    ["outlet_duplex", "中展示區插座1",  610, 380, 0,   "O4"],
    ["outlet_duplex", "中展示區插座2",  700, 380, 0,   "O4"],
    ["outlet_duplex", "中展示區插座3",  790, 380, 0,   "O5"],
    # === 右展示區 Right Display ===
    ["outlet_duplex", "右展示區插座1",  840, 390, 0,   "O6"],
    ["outlet_duplex", "右展示區插座2",  840, 440, 0,   "O6"],
    ["outlet_duplex", "右展示區插座3",  950, 420, 0,   "O7"],
    # === 服飾區 Apparel (每2個吊掛桿之間1組 × 3) ===
    ["outlet_quad",   "服飾區插座1",    520, 380, 0,   "O8"],
    ["outlet_quad",   "服飾區插座2",    680, 380, 0,   "O8"],
    ["outlet_quad",   "服飾區插座3",    820, 380, 0,   "O8"],
    # === 服務區 SERVICE AREA ===
    ["outlet_duplex", "服務區插座1",    480, 240, 0,   "O9"],
    ["outlet_duplex", "服務區插座2",    520, 240, 0,   "O9"],
    ["outlet_220v",   "服務區220V",     500, 260, 0,   "O10"],
    ["data_port",     "服務區網路",     510, 230, 0,   "D1"],
    # === 互動體驗區 Interactive (發球機×2 + 投影機 + 電腦) ===
    ["outlet_duplex", "體驗區插座1",    580, 500, 0,   "O11"],
    ["outlet_duplex", "體驗區插座2",    650, 540, 0,   "O11"],
    ["data_port",     "體驗區網路",      615, 520, 0,   "D2"],
    # === 高爾夫區 Golf (projector + GC Quad) ===
    ["outlet_duplex", "高爾夫區插座1",  750, 520, 0,   "O12"],
    ["outlet_duplex", "高爾夫區插座2",  750, 560, 0,   "O12"],
    # === 洽談區 Meeting (桌旁充電) ===
    ["floor_box",     "洽談區地板插座1", 790, 550, 0,   "O13"],
    ["floor_box",     "洽談區地板插座2", 830, 550, 0,   "O13"],
    ["outlet_usb",    "洽談區USB插座",   810, 570, 0,   "O14"],
    ["data_port",     "洽談區網路",      810, 530, 0,   "D3"],
    # === 試衣間 Fitting ===
    ["outlet_duplex", "試衣間插座",      420, 190, 0,   "O15"],
    # === 櫥窗區 Window Display (4× TV) ===
    ["av_outlet",     "櫥窗電視電源1",  300, 640, 0,   "AV2"],
    ["av_outlet",     "櫥窗電視電源2",  400, 640, 0,   "AV2"],
    ["av_outlet",     "櫥窗電視電源3",  500, 640, 0,   "AV3"],
    ["av_outlet",     "櫥窗電視電源4",  600, 640, 0,   "AV3"],
    # === 網球區 Tennis (5× digital frame) ===
    ["outlet_usb",    "網球區相框電源1", 540, 580, 0,   "O16"],
    ["outlet_usb",    "網球區相框電源2", 640, 580, 0,   "O16"],
    ["data_port",     "網球區網路",      590, 600, 0,   "D4"],
    # === 羽球區 Badminton (3× digital frame) ===
    ["outlet_usb",    "羽球區相框電源1", 530, 660, 0,   "O17"],
    ["outlet_usb",    "羽球區相框電源2", 670, 660, 0,   "O17"],
    ["data_port",     "羽球區網路",      600, 680, 0,   "D5"],
    # === 左上儲藏室 Storage ===
    ["outlet_duplex", "儲藏室插座",      370, 130, 0,   "O18"],
    # === 入口區域 IT ===
    ["data_port",     "入口IT弱電箱",    330, 570, 0,   "IT1"],
    ["hdmi_port",     "電視牆HDMI",      350, 610, 0,   "AV4"],
    ["hdmi_port",     "電視牆HDMI2",     380, 610, 0,   "AV4"],
]

# Symbol ID → SVG path data for rendering
# Each is a simple SVG-like path drawn inside a 24×24 viewBox
SYMBOL_SVG = {
    # ── Lighting ──
    "downlight": """<circle cx="12" cy="12" r="7" fill="none" stroke="currentColor" stroke-width="1.5"/>
    <line x1="5" y1="12" x2="19" y2="12" stroke="currentColor" stroke-width="1.2"/>
    <line x1="12" y1="5" x2="12" y2="19" stroke="currentColor" stroke-width="1.2"/>""",

    "track_light": """<rect x="3" y="8" width="18" height="4" rx="1" fill="currentColor" opacity="0.3"/>
    <rect x="3" y="8" width="18" height="4" rx="1" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <rect x="6" y="12" width="4" height="6" rx="1" fill="currentColor"/>
    <rect x="14" y="12" width="4" height="6" rx="1" fill="currentColor"/>""",

    "spotlight": """<circle cx="12" cy="10" r="4" fill="currentColor"/>
    <path d="M6 18 L12 10 L18 18 Z" fill="none" stroke="currentColor" stroke-width="1"/>
    <line x1="6" y1="18" x2="18" y2="18" stroke="currentColor" stroke-width="1.2"/>""",

    "pendant": """<line x1="12" y1="2" x2="12" y2="8" stroke="currentColor" stroke-width="1"/>
    <circle cx="12" cy="11" r="5" fill="none" stroke="currentColor" stroke-width="1.5"/>
    <path d="M7 16 Q12 20 17 16" fill="none" stroke="currentColor" stroke-width="1"/>""",

    "linear": """<rect x="2" y="9" width="20" height="6" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/>
    <rect x="4" y="11" width="16" height="2" fill="currentColor" opacity="0.5"/>""",

    "emergency_light": """<rect x="4" y="7" width="16" height="12" rx="1" fill="currentColor" opacity="0.2"/>
    <rect x="4" y="7" width="16" height="12" rx="1" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <text x="12" y="16" text-anchor="middle" fill="currentColor" font-size="8" font-weight="bold">EL</text>""",

    "exit_sign": """<rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <rect x="3" y="5" width="18" height="14" rx="2" fill="currentColor" opacity="0.15"/>
    <text x="12" y="16" text-anchor="middle" fill="currentColor" font-size="9" font-weight="bold">EXIT</text>""",

    "direction_sign": """<rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <path d="M6 12 L10 8 L10 11 L18 11 L18 13 L10 13 L10 16 Z" fill="currentColor"/>""",

    "circuit_panel": """<rect x="3" y="4" width="18" height="16" rx="2" fill="currentColor" opacity="0.2"/>
    <rect x="3" y="4" width="18" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.5"/>
    <line x1="6" y1="9" x2="18" y2="9" stroke="currentColor" stroke-width="0.8"/>
    <line x1="6" y1="12" x2="18" y2="12" stroke="currentColor" stroke-width="0.8"/>
    <line x1="6" y1="15" x2="18" y2="15" stroke="currentColor" stroke-width="0.8"/>""",

    "sub_panel": """<rect x="4" y="5" width="16" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <line x1="7" y1="10" x2="17" y2="10" stroke="currentColor" stroke-width="0.7"/>
    <line x1="7" y1="13" x2="17" y2="13" stroke="currentColor" stroke-width="0.7"/>""",

    "switch_1g": """<circle cx="12" cy="12" r="5" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <line x1="12" y1="8" x2="12" y2="16" stroke="currentColor" stroke-width="1"/>
    <text x="12" y="21" text-anchor="middle" fill="currentColor" font-size="5">S</text>""",

    "switch_2g": """<circle cx="12" cy="12" r="6" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <line x1="12" y1="7" x2="12" y2="17" stroke="currentColor" stroke-width="0.8"/>
    <line x1="8" y1="12" x2="16" y2="12" stroke="currentColor" stroke-width="0.8"/>""",

    "dimmer": """<circle cx="12" cy="12" r="5" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <path d="M8 12 Q10 8 12 8 Q14 8 16 12" fill="none" stroke="currentColor" stroke-width="0.8"/>
    <text x="12" y="21" text-anchor="middle" fill="currentColor" font-size="4.5">D</text>""",

    "sensor": """<rect x="5" y="7" width="14" height="10" rx="4" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <circle cx="12" cy="12" r="3" fill="currentColor" opacity="0.5"/>""",

    # ── Outlet ──
    "outlet_duplex": """<rect x="4" y="6" width="16" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <circle cx="8.5" cy="10" r="2" fill="currentColor"/>
    <circle cx="15.5" cy="10" r="2" fill="currentColor"/>
    <line x1="7" y1="15" x2="17" y2="15" stroke="currentColor" stroke-width="1.2"/>""",

    "outlet_quad": """<rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <circle cx="7" cy="9" r="1.8" fill="currentColor"/>
    <circle cx="13" cy="9" r="1.8" fill="currentColor"/>
    <circle cx="7" cy="15" r="1.8" fill="currentColor"/>
    <circle cx="13" cy="15" r="1.8" fill="currentColor"/>""",

    "outlet_usb": """<rect x="4" y="6" width="16" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <rect x="6" y="9" width="5" height="6" rx="1" fill="currentColor" opacity="0.3"/>
    <rect x="13" y="9" width="5" height="6" rx="1" fill="currentColor" opacity="0.3"/>
    <text x="12" y="17" text-anchor="middle" fill="currentColor" font-size="5">USB</text>""",

    "outlet_220v": """<rect x="4" y="6" width="16" height="12" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <circle cx="9" cy="10" r="2.2" fill="currentColor"/>
    <circle cx="15" cy="10" r="2.2" fill="currentColor"/>
    <line x1="12" y1="6" x2="12" y2="3" stroke="currentColor" stroke-width="0.8"/>
    <text x="12" y="19" text-anchor="middle" fill="currentColor" font-size="4.5">220</text>""",

    "floor_box": """<rect x="4" y="5" width="16" height="14" rx="3" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <circle cx="12" cy="10" r="2.5" fill="currentColor"/>
    <rect x="9" y="13" width="6" height="3" rx="0.5" fill="currentColor" opacity="0.5"/>""",

    "data_port": """<rect x="5" y="7" width="14" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="12" y="14" text-anchor="middle" fill="currentColor" font-size="7" font-weight="bold">D</text>""",

    "hdmi_port": """<rect x="5" y="7" width="14" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <text x="12" y="14" text-anchor="middle" fill="currentColor" font-size="5.5">HDMI</text>""",

    "junction_box": """<rect x="5" y="5" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <line x1="5" y1="5" x2="19" y2="19" stroke="currentColor" stroke-width="0.6"/>
    <line x1="19" y1="5" x2="5" y2="19" stroke="currentColor" stroke-width="0.6"/>""",

    "av_outlet": """<rect x="3" y="4" width="18" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <rect x="3" y="4" width="18" height="16" rx="2" fill="currentColor" opacity="0.08"/>
    <circle cx="8" cy="10" r="1.8" fill="currentColor"/>
    <rect x="12" y="7" width="7" height="6" rx="1" fill="none" stroke="currentColor" stroke-width="0.8"/>
    <text x="12" y="18" text-anchor="middle" fill="currentColor" font-size="4.5">AV</text>""",
}


# ── PDF Generation ──────────────────────────────────────────────────────

def _color(name: str, default=(0.5, 0.5, 0.5)):
    """Resolve color name or hex to RGB tuple."""
    if name in COLORS:
        return COLORS[name]
    h = name.lstrip("#")
    if len(h) == 6:
        return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))
    return default

def generate_pdf(items: list[dict], output_path: str | Path, mode: str = "lighting"):
    """Generate PDF layout for electrical/lighting items."""
    doc = fitz.open(PDF_PATH)
    src = doc[0]
    pr = src.rect
    out = fitz.open()
    page = out.new_page(width=pr.width, height=pr.height)

    pix = src.get_pixmap(matrix=fitz.Matrix(200/72, 200/72))
    page.insert_image(pr, pixmap=pix)
    doc.close()

    # Title
    mode_label = "燈具配置 Lighting" if mode == "lighting" else "插座配置 Outlet"
    page.insert_text(fitz.Point(30, 25),
        f"YONEX TAIPEI SHOWROOM — {mode_label}",
        fontname="helv", fontsize=13, color=(0, 0.24, 0.65))

    qty = len(items)
    page.insert_text(fitz.Point(30, 42),
        f"{qty} items  |  {mode.upper()} Layout",
        fontname="helv", fontsize=7, color=(0.4, 0.4, 0.4))

    def draw_item(item):
        ix, iy = item["x"], item["y"]
        sid = item["symbol_id"]
        angle = item.get("angle", 0)
        label = item.get("label", "")

        svg_info = SYMBOL_SVG.get(sid)
        color_hex = "#F39C12"
        # Find symbol color
        for cat in SYMBOLS.values():
            for s in cat:
                if s["id"] == sid:
                    color_hex = s["color"]
                    break

        c = _color(color_hex)
        s = 8  # symbol size in PDF pt

        # Draw the symbol (simplified geometric shapes)
        if sid in ("downlight",):
            page.draw_circle((ix, iy), s, color=c, fill=None)
            page.draw_line(fitz.Point(ix-s, iy), fitz.Point(ix+s, iy), color=c, width=0.5)
            page.draw_line(fitz.Point(ix, iy-s), fitz.Point(ix, iy+s), color=c, width=0.5)
        elif sid in ("track_light",):
            a_rad = math.radians(angle)
            dx = s * 0.8 * math.cos(a_rad)
            dy = s * 0.8 * math.sin(a_rad)
            page.draw_line(fitz.Point(ix-dx, iy-dy), fitz.Point(ix+dx, iy+dy), color=c, width=1)
            page.draw_rect(fitz.Rect(ix+dx-3, iy-2, ix+dx+3, iy+2), color=c, fill=c)
            page.draw_rect(fitz.Rect(ix-dx-3, iy-2, ix-dx+3, iy+2), color=c, fill=c)
        elif sid in ("spotlight",):
            page.draw_circle((ix, iy-3), s*0.5, color=c, fill=c)
            a1 = angle - 25
            a2 = angle + 25
            for a in [a1, a2]:
                rad = math.radians(a)
                page.draw_line(fitz.Point(ix, iy), fitz.Point(ix+s*math.cos(rad), iy+s*math.sin(rad)), color=c, width=0.3)
        elif sid in ("emergency_light",):
            page.draw_rect(fitz.Rect(ix-s, iy-s*0.6, ix+s, iy+s*0.6), color=c, fill=c)
            page.insert_text(fitz.Point(ix-s*0.4, iy+s*0.2), "EL", fontname="helv", fontsize=s*0.6, color=(1,1,1))
        elif sid in ("exit_sign",):
            page.draw_rect(fitz.Rect(ix-s*0.8, iy-s*0.5, ix+s*0.8, iy+s*0.5), color=c, fill=c)
            page.insert_text(fitz.Point(ix-s*0.4, iy+s*0.2), "EXIT", fontname="helv", fontsize=s*0.4, color=(1,1,1))
        elif sid in ("direction_sign",):
            page.draw_rect(fitz.Rect(ix-s*0.8, iy-s*0.5, ix+s*0.8, iy+s*0.5), color=c, fill=c)
            page.insert_text(fitz.Point(ix-s*0.3, iy+s*0.15), "→", fontname="helv", fontsize=s*0.5, color=(1,1,1))
        elif sid in ("circuit_panel",):
            page.draw_rect(fitz.Rect(ix-s, iy-s*0.7, ix+s, iy+s*0.7), color=c, fill=c)
            for i in range(4):
                ly = iy - s*0.5 + i * s*0.33
                page.draw_line(fitz.Point(ix-s*0.7, ly), fitz.Point(ix+s*0.7, ly), color=(1,1,1), width=0.2)
        elif sid in ("sub_panel",):
            page.draw_rect(fitz.Rect(ix-s*0.8, iy-s*0.5, ix+s*0.8, iy+s*0.5), color=c, fill=c)
        elif sid in ("switch_1g", "switch_2g", "dimmer"):
            page.draw_circle((ix, iy), s*0.5, color=c, fill=None)
            page.draw_line(fitz.Point(ix, iy-s*0.3), fitz.Point(ix, iy+s*0.3), color=c, width=0.5)
        elif sid in ("sensor",):
            page.draw_rect(fitz.Rect(ix-s*0.5, iy-s*0.4, ix+s*0.5, iy+s*0.4), color=c, fill=None)
        elif sid in ("outlet_duplex", "outlet_quad", "outlet_usb", "av_outlet"):
            page.draw_rect(fitz.Rect(ix-s*0.5, iy-s*0.6, ix+s*0.5, iy+s*0.6), color=c, fill=None)
            page.draw_circle((ix-s*0.2, iy-s*0.1), s*0.15, color=c, fill=c)
            page.draw_circle((ix+s*0.2, iy-s*0.1), s*0.15, color=c, fill=c)
            page.draw_line(fitz.Point(ix-s*0.15, iy+s*0.4), fitz.Point(ix+s*0.15, iy+s*0.4), color=c, width=0.8)
        elif sid in ("outlet_220v",):
            page.draw_rect(fitz.Rect(ix-s*0.5, iy-s*0.6, ix+s*0.5, iy+s*0.6), color=c, fill=None)
            page.draw_circle((ix-s*0.2, iy-s*0.1), s*0.2, color=c, fill=c)
            page.draw_circle((ix+s*0.2, iy-s*0.1), s*0.2, color=c, fill=c)
        elif sid in ("floor_box",):
            page.draw_rect(fitz.Rect(ix-s*0.5, iy-s*0.5, ix+s*0.5, iy+s*0.5), color=c, fill=c)
        elif sid in ("data_port", "hdmi_port"):
            page.draw_rect(fitz.Rect(ix-s*0.4, iy-s*0.5, ix+s*0.4, iy+s*0.5), color=c, fill=None)
            page.insert_text(fitz.Point(ix-s*0.25, iy+s*0.2), "D" if sid == "data_port" else "H", fontname="helv", fontsize=s*0.4, color=c)
        elif sid in ("junction_box",):
            page.draw_rect(fitz.Rect(ix-s*0.3, iy-s*0.3, ix+s*0.3, iy+s*0.3), color=c, fill=c)
        elif sid in ("linear",):
            a_rad = math.radians(angle)
            dx = s * 0.9 * math.cos(a_rad)
            dy = s * 0.9 * math.sin(a_rad)
            page.draw_line(fitz.Point(ix-dx, iy-dy), fitz.Point(ix+dx, iy+dy), color=c, width=1.5)
            page.draw_line(fitz.Point(ix-dx*0.6, iy-dy*0.6), fitz.Point(ix+dx*0.6, iy+dy*0.6), color=(1,1,1), width=0.4)
        elif sid in ("pendant",):
            page.draw_line(fitz.Point(ix, iy-s), fitz.Point(ix, iy), color=c, width=0.5)
            page.draw_circle((ix, iy+3), s*0.5, color=c, fill=None)
            page.draw_line(fitz.Point(ix-s*0.6, iy+8), fitz.Point(ix+s*0.6, iy+8), color=c, width=0.5)
        else:
            page.draw_circle((ix, iy), s*0.5, color=c, fill=c)

        # Circuit label
        circuit = item.get("circuit", "")
        if circuit:
            page.insert_text(fitz.Point(ix + s + 2, iy - 2), circuit,
                             fontname="helv", fontsize=4.5, color=(0.5, 0.5, 0.5))

        # Label below
        page.insert_text(fitz.Point(ix + s + 2, iy + 6), label or "",
                         fontname="helv", fontsize=4.5, color=(0.4, 0.4, 0.4))

    for item in items:
        draw_item(item)

    # Legend
    lx, ly = 730, 700
    legend_items = []
    for cat in SYMBOLS.get(mode, []):
        legend_items.append((cat["color"], cat["label"], cat["qty"]))

    lh = min(len(legend_items), 14) * 14 + 45
    page.draw_rect(fitz.Rect(lx, ly, lx + 200, ly + lh),
                   color=(0.7, 0.7, 0.7), fill=(0.95, 0.95, 0.95))

    subtitle = "燈具 Lighting" if mode == "lighting" else "插座 Outlet"
    page.insert_text(fitz.Point(lx + 8, ly + 12), f"圖例 Legend — {subtitle}",
                     fontname="helv", fontsize=8, color=(0.2, 0.2, 0.2))

    for i, (cn, txt, qt) in enumerate(legend_items[:14]):
        px, py2 = lx + 12, ly + 26 + i * 14
        cc = _color(cn, (0.5, 0.5, 0.5))
        page.draw_circle((px, py2), 3.5, color=cc, fill=cc)
        page.insert_text(fitz.Point(px + 10, py2 + 2), f"{txt} × {qt}",
                         fontname="helv", fontsize=5, color=(0.3, 0.3, 0.3))

    out.save(str(output_path), deflate=True, garbage=4)
    out.close()
    return str(output_path)


# ── HTML Template ───────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>YONEX 配電/燈具配置設計工具</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; }
body { background: #1a1a2e; color: white; overflow-x: hidden; }

.toolbar {
    display: flex; align-items: center; gap: 10px; padding: 8px 16px;
    background: #16213e; border-bottom: 1px solid rgba(255,255,255,0.1);
    position: sticky; top: 0; z-index: 1000; flex-wrap: wrap;
}
.toolbar h1 { font-size: 1rem; margin-right: 12px; color: #f59e0b; }
.toolbar button, .toolbar .tab {
    padding: 5px 14px; border-radius: 6px; border: none; cursor: pointer;
    font-size: 0.8rem; font-weight: 600; transition: all 0.2s;
}
.toolbar .tab { background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.6); }
.toolbar .tab.active { background: #3b82f6; color: white; }
.btn-primary { background: #3b82f6; color: white; }
.btn-primary:hover { background: #2563eb; }
.btn-success { background: #10b981; color: white; }
.btn-success:hover { background: #059669; }
.btn-warning { background: #f59e0b; color: #1a1a2e; }
.btn-outline { background: transparent; color: rgba(255,255,255,0.7); border: 1px solid rgba(255,255,255,0.2); }
.btn-outline:hover { background: rgba(255,255,255,0.1); }

/* Floor plan */
#floorplan-container {
    position: relative; margin: 12px auto; cursor: grab;
    background: #0f172a; border-radius: 8px; overflow: hidden;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
}
#floorplan-container:active { cursor: grabbing; }
#floorplan-bg { display: block; width: 100%; height: auto; pointer-events: none; }
#item-layer { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }

/* Symbol styles */
.symbol-item {
    position: absolute; pointer-events: auto; cursor: move; z-index: 10;
    transform: translate(-50%, -50%); user-select: none;
}
.symbol-item .sym-icon {
    position: relative; z-index: 2;
    transition: filter 0.15s;
}
.symbol-item.selected .sym-icon { filter: drop-shadow(0 0 8px rgba(251,191,36,0.8)); }
.symbol-item .sym-label {
    position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
    font-size: 9px; white-space: nowrap; text-shadow: 0 1px 3px rgba(0,0,0,0.9);
    padding: 1px 3px; border-radius: 2px; margin-top: 1px; pointer-events: none;
    background: rgba(0,0,0,0.5); color: white; line-height: 1.2;
}
.symbol-item .sym-circuit {
    position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%);
    font-size: 8px; white-space: nowrap; text-shadow: 0 1px 3px rgba(0,0,0,0.9);
    padding: 0 3px; border-radius: 2px; margin-bottom: 1px; pointer-events: none;
    background: rgba(0,0,0,0.4); color: #fbbf24; line-height: 1.2;
}

/* Symbol palette */
#palette {
    position: fixed; left: -300px; top: 56px; width: 280px; height: calc(100vh - 56px);
    background: #16213e; border-right: 1px solid rgba(255,255,255,0.1);
    transition: left 0.3s; padding: 12px; overflow-y: auto; z-index: 500;
}
#palette.open { left: 0; }
#palette h3 { font-size: 0.85rem; margin-bottom: 8px; color: rgba(255,255,255,0.6); }
.palette-item {
    display: flex; align-items: center; gap: 8px; padding: 5px 8px; border-radius: 6px;
    cursor: grab; transition: background 0.15s; font-size: 0.78rem;
    border: 1px solid transparent; margin-bottom: 2px;
}
.palette-item:hover { background: rgba(255,255,255,0.06); border-color: rgba(255,255,255,0.1); }
.palette-item .dot { width: 16px; height: 16px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
.palette-item .qty-badge { margin-left: auto; background: rgba(255,255,255,0.1); padding: 1px 6px; border-radius: 8px; font-size: 0.7rem; color: rgba(255,255,255,0.5); }

/* Properties panel */
#panel {
    position: fixed; right: -350px; top: 56px; width: 300px; height: calc(100vh - 56px);
    background: #16213e; border-left: 1px solid rgba(255,255,255,0.1);
    transition: right 0.3s; padding: 16px; overflow-y: auto; z-index: 500;
}
#panel.open { right: 0; }
#panel h2 { font-size: 0.95rem; margin-bottom: 12px; color: #f59e0b; }
#panel .field { margin-bottom: 10px; }
#panel label { display: block; font-size: 0.72rem; color: rgba(255,255,255,0.5); margin-bottom: 3px; }
#panel input, #panel select {
    width: 100%; padding: 5px 8px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.15);
    background: rgba(255,255,255,0.05); color: white; font-size: 0.82rem;
}
#panel input:focus, #panel select:focus { outline: none; border-color: #3b82f6; }
#panel .row { display: flex; gap: 8px; }
#panel .row .field { flex: 1; }
#panel .btn-row { display: flex; gap: 8px; margin-top: 12px; }
#panel .btn-row button { flex: 1; padding: 6px; }

/* Stats bar */
#stats {
    font-size: 0.75rem; color: rgba(255,255,255,0.4); display: flex; gap: 16px; align-items: center;
}

/* Camera list / item list */
#item-list-panel {
    position: fixed; left: -300px; top: 56px; width: 280px; height: calc(100vh - 56px);
    background: #16213e; border-right: 1px solid rgba(255,255,255,0.1);
    transition: left 0.3s; padding: 12px; overflow-y: auto; z-index: 500;
}
#item-list-panel.open { left: 0; z-index: 501; }
#item-list-panel h3 { font-size: 0.85rem; margin-bottom: 8px; color: rgba(255,255,255,0.6); }
.item-list-entry {
    display: flex; align-items: center; gap: 6px; padding: 4px 6px; border-radius: 4px;
    cursor: pointer; transition: background 0.12s; font-size: 0.75rem;
}
.item-list-entry:hover { background: rgba(255,255,255,0.05); }
.item-list-entry .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

/* Legend on floorplan */
#inline-legend {
    position: absolute; bottom: 16px; right: 16px; z-index: 20;
    background: rgba(0,0,0,0.75); border-radius: 6px; padding: 8px 12px;
    backdrop-filter: blur(4px); font-size: 0.7rem; max-height: 180px; overflow-y: auto;
}
#inline-legend .legend-item { display: flex; align-items: center; gap: 6px; padding: 1px 0; }
#inline-legend .legend-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
#inline-legend .legend-qty { margin-left: auto; color: rgba(255,255,255,0.4); font-size: 0.65rem; }

#loading { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; background: #1a1a2e; z-index: 9999; flex-direction: column; gap: 16px; }
#loading .spinner { width: 40px; height: 40px; border: 3px solid rgba(255,255,255,0.1); border-top-color: #f59e0b; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
#toast { position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%); z-index: 9999; padding: 8px 20px; border-radius: 8px; font-size: 0.82rem; opacity: 0; transition: opacity 0.3s; pointer-events: none; }
#toast.show { opacity: 1; }
#toast.success { background: #065f46; color: #6ee7b7; }
#toast.error { background: #7f1d1d; color: #fca5a5; }

.hidden { display: none !important; }

@media (max-width: 768px) {
    #panel { width: 100%; right: -100%; }
    #palette, #item-list-panel { width: 100%; left: -100%; }
}
</style>
</head>
<body>

<div id="loading">
    <div class="spinner"></div>
    <div style="color:rgba(255,255,255,0.6);font-size:0.9rem;">載入平面圖中...</div>
</div>

<div class="toolbar">
    <button class="btn-outline" onclick="togglePalette()" title="符號面板">📦</button>
    <button class="btn-outline" onclick="toggleItemList()" title="列表">≡</button>
    <h1>⚡ YONEX 配電設計</h1>
    <button class="tab" id="tab-lighting" onclick="switchMode('lighting')">💡 燈具 Lighting</button>
    <button class="tab" id="tab-outlet" onclick="switchMode('outlet')">🔌 插座 Outlet</button>
    <button class="btn-primary" onclick="centerView()">◉ 置中</button>
    <button class="btn-success" onclick="exportPDF()">📥 生成 PDF</button>
    <button class="btn-warning" onclick="exportJSON()">📋 匯出 JSON</button>
    <button class="btn-outline" onclick="document.getElementById('import-file').click()">📂 匯入</button>
    <input type="file" id="import-file" accept=".json" style="display:none" onchange="importJSON(event)">
    <span id="stats"></span>
</div>

<div id="floorplan-container">
    <img id="floorplan-bg" alt="Floor Plan">
    <div id="item-layer"></div>
    <div id="inline-legend"></div>
</div>

<!-- Palette -->
<div id="palette">
    <h3>符號面板 <span style="font-weight:normal;font-size:0.7rem;color:rgba(255,255,255,0.3)">(拖曳至平面圖)</span></h3>
    <div id="palette-items"></div>
    <div style="margin-top:8px">
        <button class="btn-outline" onclick="togglePalette()" style="width:100%;padding:6px">✕ 關閉</button>
    </div>
</div>

<!-- Item List -->
<div id="item-list-panel">
    <h3 id="item-list-title">項目列表</h3>
    <div id="item-list"></div>
    <div style="margin-top:8px">
        <button class="btn-outline" onclick="toggleItemList()" style="width:100%;padding:6px">✕ 關閉</button>
    </div>
</div>

<!-- Property Panel -->
<div id="panel">
    <button style="position:absolute;top:8px;right:8px;background:none;border:none;color:rgba(255,255,255,0.4);font-size:1.1rem;cursor:pointer" onclick="closePanel()">✕</button>
    <h2 id="panel-title">項目設定</h2>
    <div class="field">
        <label>符號類型</label>
        <select id="edit-symbol" onchange="updateItemFromPanel()"></select>
    </div>
    <div class="field">
        <label>標籤 Label</label>
        <input type="text" id="edit-label" onchange="updateItemFromPanel()">
    </div>
    <div class="row">
        <div class="field"><label>X 座標</label><input type="number" id="edit-x" onchange="updateItemFromPanel()"></div>
        <div class="field"><label>Y 座標</label><input type="number" id="edit-y" onchange="updateItemFromPanel()"></div>
    </div>
    <div class="row">
        <div class="field"><label>角度 Angle°</label><input type="number" id="edit-angle" min="0" max="360" onchange="updateItemFromPanel()"></div>
        <div class="field"><label>迴路 Circuit</label><input type="text" id="edit-circuit" onchange="updateItemFromPanel()"></div>
    </div>
    <div class="btn-row">
        <button class="btn-primary" onclick="closePanel()">✓ 完成</button>
        <button class="btn-danger" onclick="deleteSelected()" style="background:#ef4444;color:white;border:none;border-radius:6px;cursor:pointer">🗑 刪除</button>
    </div>
</div>

<div id="toast"></div>

<script>
// ── State ──────────────────────────────────────────────────────
let items = [];
let selectedId = null;
let nextId = 100;
let bgImage = null;
let scale = 1;
let pdfWidth = 0, pdfHeight = 0;
let bgLoaded = false;
let currentMode = 'lighting';
let dragItemId = null;

const SYMBOL_DATA = __SYMBOLS_JSON__;
const SYMBOL_SVG = __SVG_JSON__;
const SUGGESTED = __SUGGESTED_JSON__;

// ── Init ───────────────────────────────────────────────────────
async function init() {
    const resp = await fetch('/api/electrical/floorplan');
    const data = await resp.json();
    if (!data.ok) { alert('載入失敗: ' + data.error); return; }

    bgImage = new Image();
    bgImage.onload = () => {
        const container = document.getElementById('floorplan-container');
        document.getElementById('floorplan-bg').src = bgImage.src;
        pdfWidth = data.pdf_width;
        pdfHeight = data.pdf_height;

        const maxW = window.innerWidth - 40;
        const maxH = window.innerHeight - 100;
        const imgAspect = bgImage.width / bgImage.height;
        let dispW, dispH;
        if (maxW / maxH > imgAspect) { dispH = maxH; dispW = maxH * imgAspect; }
        else { dispW = maxW; dispH = maxW / imgAspect; }
        container.style.width = dispW + 'px';
        container.style.height = dispH + 'px';
        scale = dispW / pdfWidth;

        document.getElementById('loading').style.display = 'none';
        bgLoaded = true;
        buildPalette(currentMode);
        loadItems(currentMode);
        renderAll();
    };
    bgImage.src = '/api/electrical/floorplan-img?' + Date.now();
}

// ── Symbol palette ────────────────────────────────────────────
function buildPalette(mode) {
    const el = document.getElementById('palette-items');
    const symbols = SYMBOL_DATA[mode] || [];
    el.innerHTML = symbols.map(s => `
        <div class="palette-item" draggable="true" data-symbol="${s.id}"
             ondragstart="paletteDragStart(event, '${s.id}')">
            <span class="dot" style="color:${s.color}">${svgIcon(s.id, 16, s.color)}</span>
            <span>${s.label}</span>
            <span class="qty-badge">×${s.qty}</span>
        </div>
    `).join('');
}

function paletteDragStart(e, symbolId) {
    e.dataTransfer.setData('text/plain', symbolId);
    e.dataTransfer.effectAllowed = 'copy';
}

function svgIcon(sid, size, color) {
    const svg = SYMBOL_SVG[sid] || '<circle cx="12" cy="12" r="6" fill="currentColor"/>';
    return '<svg width="'+size+'" height="'+size+'" viewBox="0 0 24 24" style="color:'+color+'">'+svg+'</svg>';
}

// ── Floor plan drop ────────────────────────────────────────────
document.getElementById('floorplan-container').addEventListener('dragover', (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'copy';
});
document.getElementById('floorplan-container').addEventListener('drop', (e) => {
    e.preventDefault();
    const symbolId = e.dataTransfer.getData('text/plain');
    if (!symbolId || !bgLoaded) return;

    const rect = document.getElementById('floorplan-container').getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const pdfX = px / scale;
    const pdfY = py / scale;

    const symbol = findSymbolDef(symbolId);
    const id = 'ITEM-' + (nextId++);
    items.push({
        id, symbol_id: symbolId,
        label: symbol ? symbol.label : symbolId,
        x: pdfX, y: pdfY,
        angle: 0, circuit: '',
        color: symbol ? symbol.color : '#F39C12',
    });
    renderAll();
    showToast('已放置 ' + (symbol ? symbol.label : symbolId), 'success');
});

function findSymbolDef(sid) {
    for (const cat of Object.values(SYMBOL_DATA)) {
        for (const s of cat) {
            if (s.id === sid) return s;
        }
    }
    return null;
}

// ── Mode switching ─────────────────────────────────────────────
function switchMode(mode) {
    currentMode = mode;
    document.getElementById('tab-lighting').className = 'tab' + (mode === 'lighting' ? ' active' : '');
    document.getElementById('tab-outlet').className = 'tab' + (mode === 'outlet' ? ' active' : '');
    loadItems(mode);
    buildPalette(mode);
    closePanel();
    renderAll();
}

// ── Load items for mode ────────────────────────────────────────
function loadItems(mode) {
    items = SUGGESTED[mode].map((s) => ({
        id: s[0] + '-' + (Math.random()*10000|0),
        symbol_id: s[0], label: s[1],
        x: s[2], y: s[3],
        angle: s[4], circuit: s[5],
        color: (findSymbolDef(s[0]) || {}).color || '#F39C12',
    }));
    nextId = 1000;
    updateStats();
}

// ── Rendering ──────────────────────────────────────────────────
function renderAll() {
    renderItems();
    renderLegend();
    renderItemList();
}

function renderItems() {
    const layer = document.getElementById('item-layer');
    layer.innerHTML = '';
    items.forEach(item => {
        const el = document.createElement('div');
        el.className = 'symbol-item' + (item.id === selectedId ? ' selected' : '');
        el.dataset.id = item.id;
        el.style.left = (item.x * scale) + 'px';
        el.style.top = (item.y * scale) + 'px';

        const color = item.color || '#F39C12';
        el.innerHTML = `
            <div class="sym-icon">${svgIcon(item.symbol_id, 28, color)}</div>
            ${item.circuit ? `<div class="sym-circuit">${item.circuit}</div>` : ''}
            <div class="sym-label" style="color:${color}">${item.label}</div>
        `;

        el.addEventListener('mousedown', (e) => {
            e.stopPropagation();
            selectItem(item.id);
            startDrag(e);
        });
        el.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            selectItem(item.id);
            openPanel();
        });

        layer.appendChild(el);
    });
}

function renderLegend() {
    const el = document.getElementById('inline-legend');
    const symbols = SYMBOL_DATA[currentMode] || [];
    const counts = {};
    items.forEach(item => {
        counts[item.symbol_id] = (counts[item.symbol_id] || 0) + 1;
    });
    el.innerHTML = '<div style="font-weight:bold;margin-bottom:4px;color:rgba(255,255,255,0.5)">'
        + (currentMode === 'lighting' ? '💡 燈具' : '🔌 插座') + '</div>'
        + symbols.map(s => {
            const c = counts[s.id] || 0;
            return `<div class="legend-item">
                <span class="legend-dot" style="background:${s.color}"></span>
                <span>${s.label}</span>
                <span class="legend-qty">${c}/${s.qty}</span>
            </div>`;
        }).join('');
}

function renderItemList() {
    const el = document.getElementById('item-list');
    el.innerHTML = items.map(item => `
        <div class="item-list-entry" onclick="selectItem('${item.id}');openPanel()">
            <span class="dot" style="background:${item.color||'#F39C12'}"></span>
            <span>${item.label}</span>
            <span style="color:rgba(255,255,255,0.3);font-size:0.7rem;margin-left:auto">${item.circuit || ''}</span>
        </div>
    `).join('');
    document.getElementById('item-list-title').textContent =
        `項目列表 (${items.length})`;
}

// ── Selection ──────────────────────────────────────────────────
function selectItem(id) {
    if (selectedId === id) { renderAll(); return; }
    selectedId = id;
    renderItems();
    const item = items.find(i => i.id === id);
    if (item) updatePanel(item);
}
function updatePanel(item) {
    document.getElementById('panel-title').textContent = item.label + ' 設定';
    // Build symbol options
    const sel = document.getElementById('edit-symbol');
    const symbols = SYMBOL_DATA[currentMode] || [];
    sel.innerHTML = symbols.map(s =>
        `<option value="${s.id}" ${s.id === item.symbol_id ? 'selected' : ''}>${s.label}</option>`
    ).join('');
    document.getElementById('edit-label').value = item.label;
    document.getElementById('edit-x').value = Math.round(item.x);
    document.getElementById('edit-y').value = Math.round(item.y);
    document.getElementById('edit-angle').value = item.angle || 0;
    document.getElementById('edit-circuit').value = item.circuit || '';
}

// ── Panel ──────────────────────────────────────────────────────
function openPanel() { document.getElementById('panel').classList.add('open'); }
function closePanel() { document.getElementById('panel').classList.remove('open'); }
function togglePalette() { document.getElementById('palette').classList.toggle('open'); }
function toggleItemList() { document.getElementById('item-list-panel').classList.toggle('open'); }

function updateItemFromPanel() {
    if (!selectedId) return;
    const item = items.find(i => i.id === selectedId);
    if (!item) return;
    const sid = document.getElementById('edit-symbol').value;
    item.symbol_id = sid;
    item.label = document.getElementById('edit-label').value;
    item.x = parseFloat(document.getElementById('edit-x').value) || 0;
    item.y = parseFloat(document.getElementById('edit-y').value) || 0;
    item.angle = parseInt(document.getElementById('edit-angle').value) || 0;
    item.circuit = document.getElementById('edit-circuit').value || '';
    const symDef = findSymbolDef(sid);
    if (symDef) item.color = symDef.color;
    renderAll();
    updatePanel(item);
}

function deleteSelected() {
    if (!selectedId) return;
    items = items.filter(i => i.id !== selectedId);
    selectedId = null;
    closePanel();
    renderAll();
    showToast('已刪除', 'success');
}

// ── Drag ───────────────────────────────────────────────────────
function startDrag(e) {
    const item = items.find(i => i.id === selectedId);
    if (!item) return;
    dragItemId = item.id;

    const rect = document.getElementById('floorplan-container').getBoundingClientRect();
    const startX = e.clientX, startY = e.clientY;
    const origX = item.x, origY = item.y;

    function onMove(ev) {
        if (!dragItemId) return;
        const dx = (ev.clientX - startX) / scale;
        const dy = (ev.clientY - startY) / scale;
        const it = items.find(x => x.id === dragItemId);
        if (it) { it.x = Math.max(0, origX + dx); it.y = Math.max(0, origY + dy); renderAll(); }
    }
    function onUp() {
        dragItemId = null;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

// ── Actions ────────────────────────────────────────────────────
function centerView() {
    document.getElementById('floorplan-container').scrollIntoView({behavior:'smooth',block:'center'});
}

function updateStats() {
    const symbols = SYMBOL_DATA[currentMode] || [];
    const counts = {};
    items.forEach(i => { counts[i.symbol_id] = (counts[i.symbol_id]||0) + 1; });
    const total = items.length;
    const planned = symbols.reduce((s, sym) => s + sym.qty, 0);
    document.getElementById('stats').textContent = `${total} placed / ${planned} planned`;
}

async function exportPDF() {
    showToast('正在生成 PDF...', 'success');
    try {
        const data = {
            mode: currentMode,
            items: items.map(i => ({
                symbol_id: i.symbol_id, label: i.label,
                x: i.x, y: i.y, angle: i.angle || 0, circuit: i.circuit || '',
            })),
        };
        const resp = await fetch('/api/electrical/generate-pdf', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data),
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'YONEX_' + (currentMode === 'lighting' ? '燈具配置' : '插座配置') + '.pdf';
        a.click();
        URL.revokeObjectURL(url);
        showToast('PDF 已下載!', 'success');
    } catch(e) {
        showToast('生成失敗: ' + e.message, 'error');
    }
}

function exportJSON() {
    const data = {mode: currentMode, items};
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'yonex_' + currentMode + '_layout.json';
    a.click();
    URL.revokeObjectURL(url);
    showToast('JSON 已匯出', 'success');
}

function importJSON(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const data = JSON.parse(e.target.result);
            if (data.mode && data.items) {
                currentMode = data.mode;
                items = data.items;
                switchMode(currentMode);
                showToast('已匯入 ' + items.length + ' 項', 'success');
            } else if (data.cameras) {
                showToast('這是 CCTV 配置檔，請切換到 CCTV Designer', 'error');
            }
        } catch(err) {
            showToast('匯入失敗: ' + err.message, 'error');
        }
    };
    reader.readAsText(file);
    event.target.value = '';
}

// ── Toast ─────────────────────────────────────────────────────
function showToast(msg, type) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'show ' + type;
    setTimeout(() => el.classList.remove('show'), 3000);
}

// ── Keyboard ──────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePanel();
    if (e.key === 'Delete' && selectedId) deleteSelected();
});

// ── Window resize ─────────────────────────────────────────────
window.addEventListener('resize', () => {
    if (bgLoaded) renderAll();
});

// ── Start ─────────────────────────────────────────────────────
init();
</script>
</body>
</html>
"""


# ── HTTP Handler ────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def _json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _png(self, path):
        data = Path(path).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _pdf_response(self, pdf_path):
        data = Path(pdf_path).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", "attachment; filename=\"YONEX_electrical.pdf\"; filename*=UTF-8''YONEX_%E9%85%8D%E9%9B%BB%E9%85%8D%E7%BD%AE.pdf")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if path in ("/", "/electrical-designer"):
                symbols_json = json.dumps(SYMBOLS, ensure_ascii=False)
                svg_json = json.dumps(SYMBOL_SVG, ensure_ascii=False)
                suggested_json = json.dumps({"lighting": SUGGESTED_LIGHTS, "outlet": SUGGESTED_OUTLETS}, ensure_ascii=False)
                html = HTML_TEMPLATE.replace("__SYMBOLS_JSON__", symbols_json)
                html = html.replace("__SVG_JSON__", svg_json)
                html = html.replace("__SUGGESTED_JSON__", suggested_json)
                self._html(html)

            elif path == "/api/electrical/floorplan":
                pdf_doc = fitz.open(PDF_PATH)
                pr = pdf_doc[0].rect
                pdf_doc.close()
                self._json({
                    "ok": True,
                    "pdf_width": pr.width,
                    "pdf_height": pr.height,
                })

            elif path == "/api/electrical/floorplan-img":
                tmp_png = "/tmp/electrical_floorplan_bg.png"
                if not os.path.exists(tmp_png):
                    pdf_doc = fitz.open(PDF_PATH)
                    page = pdf_doc[0]
                    pix = page.get_pixmap(matrix=fitz.Matrix(200/72, 200/72))
                    pix.save(tmp_png)
                    pdf_doc.close()
                self._png(tmp_png)

            else:
                self._json({"error": "not found"}, 404)

        except Exception as e:
            logger.exception("GET error")
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if path == "/api/electrical/generate-pdf":
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                mode = body.get("mode", "lighting")
                items = body.get("items", [])
                output = str(OUTPUT_DIR / f"YONEX_{mode}_配置.pdf")
                pdf_path = generate_pdf(items, output, mode)
                self._pdf_response(pdf_path)
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            logger.exception("POST error")
            self._json({"error": str(e)}, 500)

    def log_message(self, fmt, *args):
        pass


def pre_cache():
    tmp_png = "/tmp/electrical_floorplan_bg.png"
    if not os.path.exists(tmp_png):
        doc = fitz.open(PDF_PATH)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(200/72, 200/72))
        pix.save(tmp_png)
        doc.close()
        logger.info("Cached electrical floorplan background")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    port = 8893
    pre_cache()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    logger.info("YONEX 配電設計 → http://localhost:%d/electrical-designer", port)
    print(f"\n  ⚡ 開啟瀏覽器: http://localhost:{port}/electrical-designer")
    print(f"    左側面板拖曳符號至平面圖放置")
    print(f"    上方切換 燈具/插座 模式")
    print(f"    點兩下符號打開設定面板")
    print(f"    調整完按「生成 PDF」下載\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
