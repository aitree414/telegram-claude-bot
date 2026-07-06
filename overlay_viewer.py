"""
6-Section Overlay Reference Viewer — Interactive HTML with layer toggle & symbol editor.
Serves 6 DXF reference drawings overlaid on the floor plan.
"""
import io, json, math, os, logging, time, base64
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import fitz
import ezdxf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
try:
    fm.fontManager.addfont("/System/Library/Fonts/STHeiti Medium.ttc")
    plt.rcParams["font.sans-serif"] = ["STHeiti", "Heiti TC"] + plt.rcParams.get("font.sans-serif", [])
except Exception:
    pass
plt.rcParams["font.family"] = "sans-serif"
from matplotlib.patches import Circle
from PIL import Image

logger = logging.getLogger(__name__)

PDF_PATH = Path("/Users/aitree414/Documents/Yonex/Yonex for TREE/CAD/26.05.26-YONEX平面圖.pdf")
DXF_DIR = Path("/Users/aitree414/Documents/Yonex/Yonex for TREE/CAD/")
CACHE_DIR = Path("/tmp/overlay_cache/")
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DISCIPLINES = [
    {"id": "fire",       "label": "消防設備 Fire",    "file": "ref01_fire.dxf",      "color": "#E74C3C"},
    {"id": "ac",         "label": "空調設備 HVAC",   "file": "ref02_ac.dxf",        "color": "#27AE60"},
    {"id": "lighting",   "label": "燈光配置 Light",  "file": "ref03_lighting.dxf",  "color": "#F39C12"},
    {"id": "outlets",    "label": "插座配置 Outlet", "file": "ref04_outlets.dxf",   "color": "#9B59B6"},
    {"id": "electrical", "label": "用電設備 Elec",   "file": "ref05_electrical.dxf","color": "#E74C3C"},
    {"id": "cctv",       "label": "監視器 CCTV",     "file": "ref06_cctv.dxf",      "color": "#27AE60"},
]

LAYER_CONFIG = {
    "OUTLINE":      {"color": "#003DA5", "lw": 2.5, "alpha": 0.6, "label": "輪廓/隔間"},
    "ZONE":         {"color": "#4A90D9", "lw": 1.0, "alpha": 0.4, "label": "分區"},
    "FIRE_EQUIP":   {"color": "#E74C3C", "lw": 1.0, "alpha": 0.8, "label": "消防設備"},
    "AC_EQUIP":     {"color": "#27AE60", "lw": 1.0, "alpha": 0.8, "label": "空調設備"},
    "LIGHT_EQUIP":  {"color": "#F39C12", "lw": 1.0, "alpha": 0.8, "label": "燈光設備"},
    "LIGHT_AREA":   {"color": "#8E44AD", "lw": 0.5, "alpha": 0.3, "label": "燈光範圍"},
    "OUTLET":       {"color": "#9B59B6", "lw": 1.0, "alpha": 0.8, "label": "插座"},
    "ELEC_EQUIP":   {"color": "#E74C3C", "lw": 1.0, "alpha": 0.8, "label": "用電設備"},
    "CCTV_EQUIP":   {"color": "#27AE60", "lw": 1.0, "alpha": 0.8, "label": "監視器"},
    "LABEL":        {"color": "#333333", "lw": 0.5, "alpha": 0.9, "label": "標籤"},
}

# Professional symbols for each discipline
SYMBOLS = [
    # Fire
    {"id": "fire_ext",      "label": "滅火器",   "disc": "fire",       "color": "#E74C3C", "size": 14},
    {"id": "sprinkler",     "label": "灑水頭",   "disc": "fire",       "color": "#3498DB", "size": 12},
    {"id": "smoke_detector","label": "偵煙器",   "disc": "fire",       "color": "#95A5A6", "size": 12},
    {"id": "alarm_bell",    "label": "警報鈴",   "disc": "fire",       "color": "#E74C3C", "size": 14},
    {"id": "fire_alarm",    "label": "火警盤",   "disc": "fire",       "color": "#C0392B", "size": 16},
    # HVAC
    {"id": "ac_unit",       "label": "空調主機", "disc": "ac",         "color": "#27AE60", "size": 18},
    {"id": "vent",          "label": "出風口",   "disc": "ac",         "color": "#2ECC71", "size": 14},
    {"id": "exhaust",       "label": "排氣口",   "disc": "ac",         "color": "#1ABC9C", "size": 14},
    {"id": "thermostat",    "label": "溫控器",   "disc": "ac",         "color": "#16A085", "size": 10},
    # Lighting
    {"id": "light",         "label": "燈具",     "disc": "lighting",   "color": "#F39C12", "size": 12},
    {"id": "emergency_light","label": "緊急照明","disc": "lighting",   "color": "#E67E22", "size": 14},
    {"id": "spotlight",     "label": "投射燈",   "disc": "lighting",   "color": "#F1C40F", "size": 12},
    {"id": "track_light",   "label": "軌道燈",   "disc": "lighting",   "color": "#D4AC0D", "size": 16},
    # Outlets
    {"id": "outlet",        "label": "插座",     "disc": "outlets",    "color": "#9B59B6", "size": 12},
    {"id": "switch",        "label": "開關",     "disc": "outlets",    "color": "#8E44AD", "size": 10},
    {"id": "usb_outlet",    "label": "USB插座",  "disc": "outlets",    "color": "#AF7AC5", "size": 12},
    {"id": "data_port",     "label": "資訊插座", "disc": "outlets",    "color": "#7D3C98", "size": 12},
    # Electrical
    {"id": "panel",         "label": "配電盤",   "disc": "electrical", "color": "#E74C3C", "size": 18},
    {"id": "junction_box",  "label": "接線盒",   "disc": "electrical", "color": "#C0392B", "size": 10},
    {"id": "transformer",   "label": "變壓器",   "disc": "electrical", "color": "#A93226", "size": 16},
    {"id": "generator",     "label": "發電機",   "disc": "electrical", "color": "#943126", "size": 20},
    # CCTV
    {"id": "dome_cam",      "label": "半球攝影機","disc": "cctv",      "color": "#27AE60", "size": 12},
    {"id": "bullet_cam",    "label": "槍型攝影機","disc": "cctv",      "color": "#FF9800", "size": 12},
    {"id": "nvr",           "label": "NVR主機",  "disc": "cctv",       "color": "#E74C3C", "size": 18},
    {"id": "ups",           "label": "UPS",      "disc": "cctv",       "color": "#F39C12", "size": 14},
]

# Map symbol → PDF drawing function
def draw_symbol_pdf(page, sym_type, x, y, angle=0, color=(0.8,0.2,0.1), size=12, label=""):
    """Draw a professional symbol on a PDF page using PyMuPDF."""
    c = color if isinstance(color, tuple) else _hex_to_rgb(color)
    a_rad = math.radians(angle)
    s = size / 2  # half-size for drawing

    draw_funcs = {
        "fire_ext": lambda: _draw_fire_ext(page, x, y, c, s),
        "sprinkler": lambda: _draw_sprinkler(page, x, y, c, s),
        "smoke_detector": lambda: _draw_smoke_detector(page, x, y, c, s),
        "alarm_bell": lambda: _draw_alarm_bell(page, x, y, c, s),
        "fire_alarm": lambda: _draw_fire_alarm(page, x, y, c, s),
        "ac_unit": lambda: _draw_ac_unit(page, x, y, c, s),
        "vent": lambda: _draw_vent(page, x, y, c, s),
        "exhaust": lambda: _draw_exhaust(page, x, y, c, s),
        "thermostat": lambda: _draw_thermostat(page, x, y, c, s),
        "light": lambda: _draw_light(page, x, y, c, s),
        "emergency_light": lambda: _draw_emergency_light(page, x, y, c, s),
        "spotlight": lambda: _draw_spotlight(page, x, y, c, s),
        "track_light": lambda: _draw_track_light(page, x, y, c, s),
        "outlet": lambda: _draw_outlet(page, x, y, c, s),
        "switch": lambda: _draw_switch(page, x, y, c, s),
        "usb_outlet": lambda: _draw_usb_outlet(page, x, y, c, s),
        "data_port": lambda: _draw_data_port(page, x, y, c, s),
        "panel": lambda: _draw_panel(page, x, y, c, s),
        "junction_box": lambda: _draw_junction_box(page, x, y, c, s),
        "transformer": lambda: _draw_transformer(page, x, y, c, s),
        "generator": lambda: _draw_generator(page, x, y, c, s),
        "dome_cam": lambda: _draw_dome_cam(page, x, y, c, s),
        "bullet_cam": lambda: _draw_bullet_cam(page, x, y, c, s),
        "nvr": lambda: _draw_nvr(page, x, y, c, s),
        "ups": lambda: _draw_ups(page, x, y, c, s),
    }
    func = draw_funcs.get(sym_type)
    if func:
        func()
    if label:
        page.insert_text(fitz.Point(x + s + 2, y + 2), label,
                         fontname="helv", fontsize=5, color=(0.3, 0.3, 0.3))


def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))

# ── Symbol drawing helpers ──
def _draw_fire_ext(p, x, y, c, s):
    p.draw_circle((x, y), s, color=c, fill=c)
    p.insert_text(fitz.Point(x - s/2, y + s/3), "F", fontname="helv", fontsize=s, color=(1,1,1))

def _draw_sprinkler(p, x, y, c, s):
    p.draw_circle((x, y), s*0.5, color=c, fill=c)
    for a in [0, 90, 180, 270]:
        rad = math.radians(a)
        ex = x + s * math.cos(rad)
        ey = y + s * math.sin(rad)
        p.draw_line((x, y), (ex, ey), color=c, width=0.5)

def _draw_smoke_detector(p, x, y, c, s):
    p.draw_circle((x, y), s*0.7, color=c, fill=None)
    p.draw_circle((x, y), s*0.25, color=c, fill=c)

def _draw_alarm_bell(p, x, y, c, s):
    p.draw_circle((x, y), s*0.7, color=c, fill=None)
    p.draw_line(fitz.Point(x-s*0.7, y), fitz.Point(x+s*0.7, y), color=c, width=0.5)
    p.insert_text(fitz.Point(x-s*0.2, y+s*0.4), "!", fontname="helv", fontsize=s*0.8, color=c)

def _draw_fire_alarm(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s, y-s, x+s, y+s), color=c, fill=c)
    p.insert_text(fitz.Point(x-s*0.4, y+s*0.3), "FA", fontname="helv", fontsize=s*0.6, color=(1,1,1))

def _draw_ac_unit(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s, y-s*0.8, x+s, y+s*0.8), color=c, fill=None)
    # X inside
    p.draw_line(fitz.Point(x-s, y-s*0.8), fitz.Point(x+s, y+s*0.8), color=c, width=0.4)
    p.draw_line(fitz.Point(x+s, y-s*0.8), fitz.Point(x-s, y+s*0.8), color=c, width=0.4)

def _draw_vent(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s*0.8, y-s*0.8, x+s*0.8, y+s*0.8), color=c, fill=None)
    for i in range(3):
        ly = y - s*0.5 + i * s*0.4
        p.draw_line(fitz.Point(x-s*0.6, ly), fitz.Point(x+s*0.6, ly), color=c, width=0.3)

def _draw_exhaust(p, x, y, c, s):
    p.draw_circle((x, y), s*0.7, color=c, fill=None)
    p.draw_line(fitz.Point(x-s*0.4, y-s*0.3), fitz.Point(x+s*0.4, y+s*0.3), color=c, width=0.4)

def _draw_thermostat(p, x, y, c, s):
    p.draw_circle((x, y), s*0.5, color=c, fill=c)
    p.insert_text(fitz.Point(x-s*0.2, y+s*0.2), "T", fontname="helv", fontsize=s*0.7, color=(1,1,1))

def _draw_light(p, x, y, c, s):
    p.draw_circle((x, y), s*0.6, color=c, fill=None)
    p.draw_line(fitz.Point(x-s*0.6, y), fitz.Point(x+s*0.6, y), color=c, width=0.4)
    p.draw_line(fitz.Point(x, y-s*0.6), fitz.Point(x, y+s*0.6), color=c, width=0.4)

def _draw_emergency_light(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s*0.7, y-s*0.5, x+s*0.7, y+s*0.5), color=c, fill=c)
    p.insert_text(fitz.Point(x-s*0.4, y+s*0.2), "EL", fontname="helv", fontsize=s*0.5, color=(1,1,1))

def _draw_spotlight(p, x, y, c, s):
    p.draw_circle((x, y-s*0.3), s*0.3, color=c, fill=c)
    # beam
    p.draw_line(fitz.Point(x-s*0.6, y+s*0.5), fitz.Point(x, y-s*0.3), color=c, width=0.3)
    p.draw_line(fitz.Point(x+s*0.6, y+s*0.5), fitz.Point(x, y-s*0.3), color=c, width=0.3)
    p.draw_line(fitz.Point(x-s*0.6, y+s*0.5), fitz.Point(x+s*0.6, y+s*0.5), color=c, width=0.3)

def _draw_track_light(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s, y-s*0.2, x+s, y+s*0.2), color=c, fill=c)
    for i in range(3):
        lx = x - s*0.6 + i * s*0.6
        p.draw_line(fitz.Point(lx, y+s*0.2), fitz.Point(lx, y+s*0.7), color=c, width=0.3)

def _draw_outlet(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s*0.5, y-s*0.6, x+s*0.5, y+s*0.6), color=c, fill=None)
    p.draw_circle((x-s*0.2, y-s*0.1), s*0.15, color=c, fill=c)
    p.draw_circle((x+s*0.2, y-s*0.1), s*0.15, color=c, fill=c)
    # notch
    p.draw_line(fitz.Point(x-s*0.15, y+s*0.4), fitz.Point(x+s*0.15, y+s*0.4), color=(1,1,1), width=1)

def _draw_switch(p, x, y, c, s):
    p.draw_circle((x, y), s*0.4, color=c, fill=None)
    p.draw_line(fitz.Point(x, y-s*0.3), fitz.Point(x, y+s*0.3), color=c, width=0.5)
    p.insert_text(fitz.Point(x-s*0.15, y+s*0.35), "S", fontname="helv", fontsize=s*0.4, color=c)

def _draw_usb_outlet(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s*0.5, y-s*0.5, x+s*0.5, y+s*0.5), color=c, fill=None)
    p.draw_rect(fitz.Rect(x-s*0.3, y-s*0.3, x+s*0.3, y+s*0.3), color=c, fill=c)
    p.insert_text(fitz.Point(x-s*0.15, y+s*0.15), "U", fontname="helv", fontsize=s*0.5, color=(1,1,1))

def _draw_data_port(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s*0.4, y-s*0.5, x+s*0.4, y+s*0.5), color=c, fill=None)
    p.insert_text(fitz.Point(x-s*0.25, y+s*0.2), "D", fontname="helv", fontsize=s*0.6, color=c)

def _draw_panel(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s, y-s*0.7, x+s, y+s*0.7), color=c, fill=c)
    for i in range(4):
        ly = y - s*0.5 + i * s*0.33
        p.draw_line(fitz.Point(x-s*0.7, ly), fitz.Point(x+s*0.7, ly), color=(1,1,1), width=0.2)

def _draw_junction_box(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s*0.3, y-s*0.3, x+s*0.3, y+s*0.3), color=c, fill=c)

def _draw_transformer(p, x, y, c, s):
    p.draw_circle((x, y), s*0.7, color=c, fill=None)
    # winding symbol
    for i in range(3):
        rx = x - s*0.3 + i * s*0.3
        p.draw_circle((rx, y), s*0.15, color=c, fill=None)

def _draw_generator(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s, y-s*0.8, x+s, y+s*0.8), color=c, fill=c)
    p.insert_text(fitz.Point(x-s*0.4, y+s*0.3), "G", fontname="helv", fontsize=s*0.8, color=(1,1,1))

def _draw_dome_cam(p, x, y, c, s):
    p.draw_circle((x, y), s*0.6, color=c, fill=c)
    p.draw_circle((x, y), s*0.25, color=(0.2,0.2,0.2), fill=(0.2,0.2,0.2))
    # FOV arc
    for a_r in [math.radians(315 - 30), math.radians(315 + 30)]:
        p.draw_line(fitz.Point(x, y), fitz.Point(x + s*1.2*math.cos(a_r), y + s*1.2*math.sin(a_r)), color=c, width=0.3)

def _draw_bullet_cam(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s*0.4, y-s*0.4, x+s*0.4, y+s*0.4), color=c, fill=c)
    p.draw_rect(fitz.Rect(x-s*0.2, y-s*0.5, x+s*0.2, y+s*0.5), color=(0.3,0.3,0.3), fill=(0.3,0.3,0.3))

def _draw_nvr(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s, y-s*0.5, x+s, y+s*0.5), color=c, fill=c)
    for i in range(4):
        ly = y - s*0.3 + i * s*0.2
        p.draw_line(fitz.Point(x-s*0.7, ly), fitz.Point(x+s*0.7, ly), color=(1,1,1), width=0.2)

def _draw_ups(p, x, y, c, s):
    p.draw_rect(fitz.Rect(x-s*0.8, y-s*0.6, x+s*0.8, y+s*0.6), color=c, fill=c)
    p.insert_text(fitz.Point(x-s*0.4, y+s*0.2), "UPS", fontname="helv", fontsize=s*0.4, color=(1,1,1))


# ── Coordinate mapping ──
PDF_X0, PDF_Y0 = 259.8, 89.1
PDF_X1, PDF_Y1 = 940.0, 735.1
DXF_W, DXF_H = 21.3, 12.36
SCALE = (PDF_X1 - PDF_X0) / DXF_W
OFFSET_X = PDF_X0
OFFSET_Y = PDF_Y0 + (PDF_Y1 - PDF_Y0 - DXF_H * SCALE) / 2
RENDER_DPI = 150

def dxf_to_pdf(x, y):
    return OFFSET_X + x * SCALE, OFFSET_Y + y * SCALE

def dxf_len_to_pdf(dxf_len):
    return dxf_len * SCALE

def pdf_to_px(pdf_x, pdf_y, bg_w, bg_h):
    px = pdf_x * (bg_w / (PDF_X1 + 30))
    py = pdf_y * (bg_h / (PDF_Y1 + 30))
    return px, py

def get_floorplan_size():
    """Return (width_px, height_px) of rendered floor plan."""
    bg_path = CACHE_DIR / "floorplan.png"
    if bg_path.exists():
        img = Image.open(bg_path)
        return img.size
    # Render first
    render_floorplan_png()
    img = Image.open(bg_path)
    return img.size


def render_floorplan_png():
    """Render floor plan page 1 as RGB PNG. Checks custom upload first."""
    # Check for custom uploaded floorplan
    custom_pdf = CACHE_DIR / "custom_floorplan.pdf"
    if custom_pdf.exists():
        cache = CACHE_DIR / "floorplan_custom.png"
        if not cache.exists():
            doc = fitz.open(str(custom_pdf))
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72))
            pix.save(str(cache))
            doc.close()
            logger.info("Cached custom floorplan")
        return str(cache)

    # Default floorplan
    cache = CACHE_DIR / "floorplan.png"
    if cache.exists():
        return str(cache)
    doc = fitz.open(PDF_PATH)
    pix = doc[0].get_pixmap(matrix=fitz.Matrix(RENDER_DPI / 72, RENDER_DPI / 72))
    pix.save(str(cache))
    doc.close()
    logger.info("Cached floorplan.png")
    return str(cache)


def get_used_layers(disc_idx):
    """Get set of layer names used in this discipline's DXF."""
    disc = DISCIPLINES[disc_idx]
    dxf_path = DXF_DIR / disc["file"]
    if not dxf_path.exists():
        return set()
    doc = ezdxf.readfile(str(dxf_path))
    layers = set()
    for e in doc.modelspace():
        layer = e.dxf.layer if e.dxf.layer else "0"
        if layer in LAYER_CONFIG:
            layers.add(layer)
    return layers


def render_layer_png(disc_idx, layer_name):
    """Render ONE DXF layer as a transparent PNG (RGBA), aligned with floor plan."""
    disc = DISCIPLINES[disc_idx]
    cache = CACHE_DIR / f"{disc['id']}_{layer_name}.png"

    # Floor plan dimensions
    bg_w, bg_h = get_floorplan_size()
    dpi = RENDER_DPI
    fig_w = bg_w / dpi
    fig_h = bg_h / dpi

    dxf_path = DXF_DIR / disc["file"]
    doc = ezdxf.readfile(str(dxf_path))

    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi)
    fig.patch.set_alpha(0)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.patch.set_alpha(0)
    ax.set_xlim(0, bg_w)
    ax.set_ylim(0, bg_h)
    ax.set_aspect("equal")
    ax.axis("off")

    cfg = LAYER_CONFIG.get(layer_name, {"color": "#888", "lw": 0.5, "alpha": 0.8})
    color = cfg["color"]
    lw = cfg["lw"]
    alpha = cfg["alpha"]

    for e in doc.modelspace():
        elayer = e.dxf.layer if e.dxf.layer else "0"
        if elayer != layer_name:
            continue
        try:
            if e.dxftype() == "LWPOLYLINE":
                pts = list(e.get_points())
                if len(pts) >= 2:
                    xs = [pdf_to_px(*dxf_to_pdf(p[0], p[1]), bg_w, bg_h)[0] for p in pts]
                    xs.append(xs[0])
                    ys = [pdf_to_px(*dxf_to_pdf(p[0], p[1]), bg_w, bg_h)[1] for p in pts]
                    ys.append(ys[0])
                    ax.plot(xs, ys, color=color, linewidth=lw, alpha=alpha, linestyle="-", zorder=2)
            elif e.dxftype() == "LINE":
                s, e2 = e.dxf.start, e.dxf.end
                x1, y1 = pdf_to_px(*dxf_to_pdf(s[0], s[1]), bg_w, bg_h)
                x2, y2 = pdf_to_px(*dxf_to_pdf(e2[0], e2[1]), bg_w, bg_h)
                ax.plot([x1, x2], [y1, y2], color=color, linewidth=lw, alpha=alpha, zorder=2)
            elif e.dxftype() == "CIRCLE":
                cx, cy = pdf_to_px(*dxf_to_pdf(e.dxf.center.x, e.dxf.center.y), bg_w, bg_h)
                r = dxf_len_to_pdf(e.dxf.radius) * (bg_w / PDF_X1)
                if r < 3: r = 3
                circ = Circle((cx, cy), r, color=color, fill=True, alpha=alpha*0.6, linewidth=1, zorder=3)
                ax.add_patch(circ)
            elif e.dxftype() == "TEXT":
                txt = e.dxf.text.strip()
                if txt:
                    tx, ty = pdf_to_px(*dxf_to_pdf(e.dxf.insert.x, e.dxf.insert.y), bg_w, bg_h)
                    h = e.dxf.height
                    fs = max(3, min(8, h * 9))
                    ax.text(tx, ty, txt, fontsize=fs, color=color, alpha=0.9,
                            ha="center", va="center",
                            bbox=dict(boxstyle="round,pad=0.1", facecolor="white", edgecolor="none", alpha=0.6),
                            zorder=4)
        except Exception:
            continue

    fig.savefig(str(cache), dpi=dpi, transparent=True, pad_inches=0)
    plt.close(fig)
    logger.info("Cached layer %s/%s", disc["id"], layer_name)
    return str(cache)


def render_composite_png(disc_idx):
    """Render a composite (floor plan + all DXF layers) as a single RGB PNG."""
    disc = DISCIPLINES[disc_idx]
    cache = CACHE_DIR / f"composite_{disc['id']}.png"
    bg_path = CACHE_DIR / "floorplan.png"

    if not bg_path.exists():
        render_floorplan_png()
    dxf_path = DXF_DIR / disc["file"]
    dxf_mtime = os.path.getmtime(dxf_path) if dxf_path.exists() else 0
    cache_mtime = cache.stat().st_mtime if cache.exists() else 0
    if cache.exists() and cache_mtime > dxf_mtime:
        return str(cache)

    doc = ezdxf.readfile(str(dxf_path))
    bg_w, bg_h = get_floorplan_size()
    dpi = RENDER_DPI
    fig_w, fig_h = bg_w / dpi, bg_h / dpi

    fig, ax = plt.subplots(1, 1, figsize=(fig_w, fig_h), dpi=dpi)
    fig.patch.set_facecolor("white")
    bg_pil = Image.open(bg_path).convert("RGB")
    ax.imshow(bg_pil, extent=[0, bg_w, 0, bg_h], alpha=1.0, zorder=0)
    ax.set_xlim(0, bg_w)
    ax.set_ylim(0, bg_h)

    layers = {}
    for e in doc.modelspace():
        layer = e.dxf.layer if e.dxf.layer else "0"
        if layer in LAYER_CONFIG:
            layers.setdefault(layer, []).append(e)

    for layer_name, entities in layers.items():
        cfg = LAYER_CONFIG.get(layer_name, {"color": "#888", "lw": 0.5, "alpha": 0.7})
        color, lw, alpha = cfg["color"], cfg["lw"], cfg["alpha"]
        for e in entities:
            try:
                if e.dxftype() == "LWPOLYLINE":
                    pts = list(e.get_points())
                    if len(pts) >= 2:
                        xs = [pdf_to_px(*dxf_to_pdf(p[0], p[1]), bg_w, bg_h)[0] for p in pts] + [pdf_to_px(*dxf_to_pdf(pts[0][0], pts[0][1]), bg_w, bg_h)[0]]
                        ys = [pdf_to_px(*dxf_to_pdf(p[0], p[1]), bg_w, bg_h)[1] for p in pts] + [pdf_to_px(*dxf_to_pdf(pts[0][0], pts[0][1]), bg_w, bg_h)[1]]
                        ax.plot(xs, ys, color=color, linewidth=lw, alpha=alpha, linestyle="-", zorder=2)
                elif e.dxftype() == "LINE":
                    s, e2 = e.dxf.start, e.dxf.end
                    x1, y1 = pdf_to_px(*dxf_to_pdf(s[0], s[1]), bg_w, bg_h)
                    x2, y2 = pdf_to_px(*dxf_to_pdf(e2[0], e2[1]), bg_w, bg_h)
                    ax.plot([x1, x2], [y1, y2], color=color, linewidth=lw, alpha=alpha, zorder=2)
                elif e.dxftype() == "CIRCLE":
                    cx, cy = pdf_to_px(*dxf_to_pdf(e.dxf.center.x, e.dxf.center.y), bg_w, bg_h)
                    r = dxf_len_to_pdf(e.dxf.radius) * (bg_w / PDF_X1)
                    if r < 3: r = 3
                    ax.add_patch(Circle((cx, cy), r, color=color, fill=True, alpha=alpha*0.6, linewidth=1, zorder=3))
                elif e.dxftype() == "TEXT":
                    txt = e.dxf.text.strip()
                    if txt:
                        tx, ty = pdf_to_px(*dxf_to_pdf(e.dxf.insert.x, e.dxf.insert.y), bg_w, bg_h)
                        h = e.dxf.height
                        fs = max(3, min(8, h * 9))
                        ax.text(tx, ty, txt, fontsize=fs, color=color, alpha=0.9,
                                ha="center", va="center",
                                bbox=dict(boxstyle="round,pad=0.1", facecolor="white", edgecolor="none", alpha=0.6),
                                zorder=4)
            except Exception:
                continue

    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(str(cache), dpi=dpi, bbox_inches="tight", facecolor="white", pad_inches=0)
    plt.close(fig)
    logger.info("Cached composite_%s.png", disc["id"])
    return str(cache)


def generate_pdf(cameras, symbols, disc_idx):
    """Generate PDF with DXF layers + user symbols."""
    doc = fitz.open(PDF_PATH)
    src = doc[0]
    pr = src.rect

    out = fitz.open()
    page = out.new_page(width=pr.width, height=pr.height)
    pix = src.get_pixmap(matrix=fitz.Matrix(200/72, 200/72))
    page.insert_image(pr, pixmap=pix)
    doc.close()

    # Draw DXF layers
    disc = DISCIPLINES[disc_idx]
    dxf_path = DXF_DIR / disc["file"]
    if dxf_path.exists():
        ddoc = ezdxf.readfile(str(dxf_path))
        for e in ddoc.modelspace():
            layer = e.dxf.layer if e.dxf.layer else "0"
            if layer not in LAYER_CONFIG:
                continue
            cfg = LAYER_CONFIG[layer]
            c = _hex_to_rgb(cfg["color"])
            try:
                if e.dxftype() == "LWPOLYLINE":
                    pts = list(e.get_points())
                    if len(pts) >= 2:
                        for i in range(len(pts) - 1):
                            p1 = dxf_to_pdf(pts[i][0], pts[i][1])
                            p2 = dxf_to_pdf(pts[i+1][0], pts[i+1][1])
                            page.draw_line(p1, p2, color=c, width=0.3)
                elif e.dxftype() == "LINE":
                    s, e2 = e.dxf.start, e.dxf.end
                    p1 = dxf_to_pdf(s[0], s[1])
                    p2 = dxf_to_pdf(e2[0], e2[1])
                    page.draw_line(p1, p2, color=c, width=0.3)
                elif e.dxftype() == "CIRCLE":
                    cx, cy = dxf_to_pdf(e.dxf.center.x, e.dxf.center.y)
                    r = dxf_len_to_pdf(e.dxf.radius) * 0.5
                    if r < 2: r = 2
                    page.draw_circle((cx, cy), r, color=c, fill=c)
            except Exception:
                continue

    # Draw user symbols
    for sym in symbols:
        draw_symbol_pdf(page, sym["type"], sym["x"], sym["y"],
                       sym.get("angle", 0), sym.get("color", "#E74C3C"),
                       sym.get("size", 12), sym.get("label", ""))

    # Title
    page.insert_text(fitz.Point(30, 25),
        f"YONEX TAIPEI SHOWROOM — {disc['label']} 參考圖",
        fontname="helv", fontsize=12, color=(0, 0.24, 0.65))
    page.insert_text(fitz.Point(30, 42),
        f"包含 DXF 原始圖層 + {len(symbols)} 個使用者符號",
        fontname="helv", fontsize=6.5, color=(0.4, 0.4, 0.4))

    output = str(CACHE_DIR / f"YONEX_參考圖_{disc['id']}.pdf")
    out.save(output, deflate=True, garbage=4)
    out.close()
    return output


# ── HTML Template ─────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>6面參考圖編輯器</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; font-family:'Segoe UI','Microsoft JhengHei',sans-serif; }
body { background:#1a1a2e; color:#fff; overflow:hidden; display:flex; flex-direction:column; height:100vh; }

/* Toolbar */
.toolbar {
    display:flex; align-items:center; gap:10px; padding:8px 16px;
    background:#16213e; border-bottom:1px solid rgba(255,255,255,0.1);
    flex-shrink:0; flex-wrap:wrap;
}
.toolbar h1 { font-size:1rem; margin-right:8px; color:#f59e0b; white-space:nowrap; }
.toolbar .sub { font-size:0.75rem; color:rgba(255,255,255,0.4); margin-right:12px; }
.toolbar button {
    padding:5px 14px; border-radius:5px; border:none; cursor:pointer;
    font-size:0.8rem; font-weight:600; transition:all 0.15s;
}
.btn-outline { background:transparent; color:rgba(255,255,255,0.7); border:1px solid rgba(255,255,255,0.2); }
.btn-outline:hover { background:rgba(255,255,255,0.1); }
.btn-primary { background:#3b82f6; color:#fff; }
.btn-primary:hover { background:#2563eb; }
.btn-success { background:#10b981; color:#fff; }
.btn-success:hover { background:#059669; }

/* Discipline tabs */
.disc-tabs {
    display:flex; gap:3px; padding:0 16px; background:#0f172a;
    border-bottom:1px solid rgba(255,255,255,0.06); flex-shrink:0; overflow-x:auto;
}
.disc-tab {
    padding:6px 14px; border:none; background:transparent; color:rgba(255,255,255,0.5);
    font-size:0.78rem; cursor:pointer; border-bottom:2px solid transparent;
    transition:all 0.15s; white-space:nowrap; font-weight:500;
}
.disc-tab:hover { color:rgba(255,255,255,0.8); background:rgba(255,255,255,0.03); }
.disc-tab.active { color:#f59e0b; border-bottom-color:#f59e0b; }
.disc-tab .badge { display:inline-block; width:7px; height:7px; border-radius:50%; margin-right:5px; vertical-align:middle; }

/* Body layout */
.body { display:flex; flex:1; overflow:hidden; }

/* Left panel — layers + symbols */
#left-panel {
    width: 240px; background:#16213e; border-right:1px solid rgba(255,255,255,0.1);
    display:flex; flex-direction:column; flex-shrink:0;
    overflow-y:auto;
}
.panel-section { padding:12px 14px; border-bottom:1px solid rgba(255,255,255,0.06); }
.panel-section h3 {
    font-size:0.78rem; color:rgba(255,255,255,0.4); margin-bottom:8px;
    text-transform:uppercase; letter-spacing:0.5px;
}
.layer-toggle {
    display:flex; align-items:center; gap:8px; padding:4px 0;
    font-size:0.78rem; color:rgba(255,255,255,0.7); cursor:pointer;
}
.layer-toggle input { accent-color:#3b82f6; cursor:pointer; }
.layer-toggle .swatch { width:16px; height:3px; border-radius:2px; flex-shrink:0; }
.layer-toggle .dot { width:7px; height:7px; border-radius:50%; flex-shrink:0; }

/* Symbol palette */
#symbol-palette {
    display:grid; grid-template-columns:1fr 1fr; gap:6px; padding:4px 0;
}
.sym-btn {
    display:flex; align-items:center; gap:6px; padding:5px 6px; border-radius:5px;
    background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06);
    cursor:grab; transition:all 0.15s; font-size:0.7rem; color:rgba(255,255,255,0.8);
    user-select:none;
}
.sym-btn:hover { background:rgba(59,130,246,0.15); border-color:#3b82f6; }
.sym-btn .sym-icon { width:18px; height:18px; flex-shrink:0; }

/* Main area */
#image-area {
    flex:1; overflow:hidden; position:relative; background:#0f172a; cursor:grab;
}
#image-area:active { cursor:grabbing; }
#layer-stack {
    position:absolute; top:0; left:0;
    transform-origin:0 0;
    pointer-events:none;
}
#layer-stack img {
    position:absolute; top:0; left:0; width:100%; height:100%;
    pointer-events:none; image-rendering:auto;
}

/* User symbols on canvas */
#user-symbols {
    position:absolute; top:0; left:0; pointer-events:none;
    transform-origin:0 0;
}
.user-sym {
    position:absolute; pointer-events:auto; cursor:move;
    transform:translate(-50%, -50%); z-index:100;
    user-select:none;
}
.user-sym.selected { filter:drop-shadow(0 0 6px #fbbf24); }
.user-sym .sym-svg { width:100%; height:100%; }
.user-sym .sym-label {
    position:absolute; top:100%; left:50%; transform:translateX(-50%);
    font-size:9px; white-space:nowrap; color:rgba(255,255,255,0.7);
    text-shadow:0 1px 3px rgba(0,0,0,0.8); pointer-events:none;
}

#zoom-info {
    position:absolute; bottom:12px; left:12px;
    background:rgba(0,0,0,0.6); padding:3px 10px; border-radius:4px;
    font-size:0.75rem; color:rgba(255,255,255,0.5); pointer-events:none;
}

/* Right panel */
#right-panel {
    width:200px; background:#16213e; border-left:1px solid rgba(255,255,255,0.1);
    padding:12px; overflow-y:auto; flex-shrink:0; font-size:0.78rem;
}
#right-panel h3 { font-size:0.75rem; color:rgba(255,255,255,0.4); margin-bottom:8px; text-transform:uppercase; }
#right-panel .field { margin-bottom:8px; }
#right-panel label { display:block; font-size:0.7rem; color:rgba(255,255,255,0.4); margin-bottom:2px; }
#right-panel input, #right-panel select {
    width:100%; padding:4px 8px; border-radius:4px; border:1px solid rgba(255,255,255,0.12);
    background:rgba(255,255,255,0.05); color:#fff; font-size:0.75rem;
}
#right-panel input:focus, #right-panel select:focus { outline:none; border-color:#3b82f6; }
#right-panel .btn-row { display:flex; gap:6px; margin-top:10px; }
#right-panel .btn-row button { flex:1; padding:5px; border-radius:4px; border:none; cursor:pointer; font-size:0.72rem; font-weight:600; }

#loading {
    position:fixed; inset:0; display:flex; align-items:center; justify-content:center;
    background:#1a1a2e; z-index:9999; flex-direction:column; gap:14px;
}
#loading .spinner { width:36px; height:36px; border:3px solid rgba(255,255,255,0.1); border-top-color:#f59e0b; border-radius:50%; animation:spin 0.8s linear infinite; }
@keyframes spin { to { transform:rotate(360deg); } }

@media (max-width:900px) {
    #left-panel { width:180px; }
    #right-panel { width:160px; }
}
</style>
</head>
<body>

<div id="loading"><div class="spinner"></div><div style="color:rgba(255,255,255,0.6);font-size:0.85rem;">載入中...</div></div>

<div class="toolbar">
    <h1>📐 6面參考圖</h1>
    <span class="sub">YONEX TAIPEI</span>
    <button class="btn-outline" onclick="zoomIn()">＋</button>
    <button class="btn-outline" onclick="zoomOut()">−</button>
    <button class="btn-outline" onclick="fitView()">⊞ 滿版</button>
    <button class="btn-outline" onclick="resetView()">⟲</button>
    <button class="btn-success" onclick="exportPDF()">📥 PDF</button>
    <button class="btn-outline" onclick="exportJSON()">📋 JSON</button>
    <button class="btn-outline" onclick="document.getElementById('import-file').click()">📂 匯入</button>
    <input type="file" id="import-file" accept=".json" style="display:none" onchange="importJSON(event)">
    <button class="btn-outline" onclick="document.getElementById('upload-fp').click()" title="上傳自訂平面圖">📄 上傳平面圖</button>
    <input type="file" id="upload-fp" accept=".pdf,.png,.jpg" style="display:none" onchange="uploadFloorplan(event)">
    <button class="btn-outline" onclick="resetSymbols()" style="margin-left:auto">↺ 重置</button>
    <span id="sym-count" style="font-size:0.75rem;color:rgba(255,255,255,0.3)"></span>
</div>

<div class="disc-tabs" id="tabs"></div>

<div class="body">
    <!-- Left panel -->
    <div id="left-panel">
        <div class="panel-section">
            <h3>圖層 Layers</h3>
            <div id="layer-toggles"></div>
            <div id="no-layers" style="font-size:0.72rem;color:rgba(255,255,255,0.3);padding:4px 0;display:none">無圖層資訊</div>
        </div>
        <div class="panel-section">
            <h3>符號 Symbols</h3>
            <div id="symbol-palette"></div>
        </div>
    </div>

    <!-- Image area -->
    <div id="image-area">
        <div id="layer-stack">
            <img id="floorplan-bg" alt="Floor Plan">
        </div>
        <div id="user-symbols"></div>
        <div id="zoom-info">100%</div>
        <div id="toast" style="position:absolute;bottom:40px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,0.75);color:#fff;padding:6px 16px;border-radius:6px;font-size:0.8rem;opacity:0;transition:opacity 0.3s;pointer-events:none;z-index:999;"></div>
    </div>

    <!-- Right panel (symbol properties) -->
    <div id="right-panel">
        <h3>符號屬性</h3>
        <div id="prop-no-sel" style="color:rgba(255,255,255,0.3);font-size:0.72rem;padding:10px 0">點選符號編輯</div>
        <div id="prop-fields" style="display:none">
            <div class="field"><label>類型</label><div id="prop-type" style="padding:4px 0;font-weight:600"></div></div>
            <div class="field"><label>X</label><input type="number" id="prop-x" onchange="updateSymFromProp()"></div>
            <div class="field"><label>Y</label><input type="number" id="prop-y" onchange="updateSymFromProp()"></div>
            <div class="field"><label>角度</label><input type="number" id="prop-angle" min="0" max="360" onchange="updateSymFromProp()"></div>
            <div class="field"><label>標籤</label><input type="text" id="prop-label" onchange="updateSymFromProp()"></div>
            <div class="btn-row">
                <button class="btn-primary" onclick="document.getElementById('right-panel').style.display='none'; deselectSym()" style="background:#3b82f6">✓</button>
                <button class="btn-danger" onclick="deleteSelectedSym()" style="background:#ef4444;color:#fff">🗑 刪除</button>
            </div>
        </div>
    </div>
</div>

<script>
// ── State ──────────────────────────────────────────────────────
const DISCIPLINES = __DISCIPLINES_JSON__;
const SYMBOLS = __SYMBOLS_JSON__;

let currentIdx = 0;
let zoom = 1, panX = 0, panY = 0;
let isPanning = false, panStart = {x:0,y:0};
let bgW = 0, bgH = 0;
let layerImgs = {};  // {layerName: img}
let userSymbols = []; // [{id, type, x, y, angle, label}]
let selectedSymId = null;
let dragSymId = null;
let symCounter = 0;
let layerVisible = {};  // {layerName: bool}

const imageArea = document.getElementById('image-area');
const layerStack = document.getElementById('layer-stack');
const userSymLayer = document.getElementById('user-symbols');

// ── Init ───────────────────────────────────────────────────────
function init() {
    renderTabs();
    loadDiscipline(0);
}

function renderTabs() {
    document.getElementById('tabs').innerHTML = DISCIPLINES.map((d,i) =>
        `<button class="disc-tab ${i===0?'active':''}" onclick="loadDiscipline(${i})">
            <span class="badge" style="background:${d.color}"></span>${d.label}
        </button>`
    ).join('');
}

function renderSymbolPalette() {
    const disc = DISCIPLINES[currentIdx];
    const available = SYMBOLS.filter(s => s.disc === disc.id);
    const el = document.getElementById('symbol-palette');
    if (!available.length) {
        el.innerHTML = '<div style="font-size:0.72rem;color:rgba(255,255,255,0.3)">此分類無可用符號</div>';
        return;
    }
    el.innerHTML = available.map(s => {
        const icon = drawSymbolCanvas(s.id, s.color, 18);
        return `<div class="sym-btn" draggable="true" data-type="${s.id}" data-color="${s.color}" data-size="${s.size}" data-label="${s.label}">
            <img class="sym-icon" src="${icon}" draggable="false">
            <span>${s.label}</span>
        </div>`;
    }).join('');

    // Drag events
    el.querySelectorAll('.sym-btn').forEach(btn => {
        btn.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('text/plain', JSON.stringify({
                type: btn.dataset.type, color: btn.dataset.color,
                size: parseInt(btn.dataset.size), label: btn.dataset.label,
            }));
            e.dataTransfer.effectAllowed = 'copy';
        });
    });
}

function drawSymbolCanvas(type, color, size) {
    // Draw symbol icon on a canvas
    const c = document.createElement('canvas');
    c.width = size; c.height = size;
    const ctx = c.getContext('2d');
    ctx.clearRect(0, 0, size, size);

    const s = size/2 - 1;
    const cx = size/2, cy = size/2;
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1.2;

    switch(type) {
        case 'fire_ext':
            ctx.beginPath(); ctx.arc(cx, cy, s*0.7, 0, 2*Math.PI); ctx.fill();
            ctx.fillStyle = '#fff'; ctx.font = `bold ${s*0.7}px sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('F', cx, cy+1);
            break;
        case 'sprinkler':
            ctx.beginPath(); ctx.arc(cx, cy, s*0.4, 0, 2*Math.PI); ctx.fill();
            for (let a=0;a<360;a+=90) {
                const r = a*Math.PI/180;
                ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(cx+s*Math.cos(r), cy+s*Math.sin(r)); ctx.stroke();
            }
            break;
        case 'smoke_detector':
            ctx.beginPath(); ctx.arc(cx, cy, s*0.6, 0, 2*Math.PI); ctx.stroke();
            ctx.beginPath(); ctx.arc(cx, cy, s*0.25, 0, 2*Math.PI); ctx.fill();
            break;
        case 'alarm_bell':
            ctx.beginPath(); ctx.arc(cx, cy, s*0.6, 0, Math.PI); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx-s*0.6,cy); ctx.lineTo(cx+s*0.6,cy); ctx.stroke();
            ctx.fillStyle = color; ctx.font = `bold ${s*0.7}px sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('!', cx, cy+s*0.2);
            break;
        case 'fire_alarm':
            ctx.fillRect(cx-s*0.7, cy-s*0.6, s*1.4, s*1.2);
            ctx.fillStyle = '#fff'; ctx.font = `bold ${s*0.5}px sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('FA', cx, cy+1);
            break;
        case 'ac_unit':
            ctx.strokeRect(cx-s*0.8, cy-s*0.6, s*1.6, s*1.2);
            ctx.beginPath(); ctx.moveTo(cx-s*0.8,cy-s*0.6); ctx.lineTo(cx+s*0.8,cy+s*0.6); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx+s*0.8,cy-s*0.6); ctx.lineTo(cx-s*0.8,cy+s*0.6); ctx.stroke();
            break;
        case 'vent':
            ctx.strokeRect(cx-s*0.7, cy-s*0.7, s*1.4, s*1.4);
            for (let i=0;i<3;i++) { ctx.beginPath(); ctx.moveTo(cx-s*0.5, cy-s*0.4+i*s*0.4); ctx.lineTo(cx+s*0.5, cy-s*0.4+i*s*0.4); ctx.stroke(); }
            break;
        case 'exhaust':
            ctx.beginPath(); ctx.arc(cx, cy, s*0.6, 0, 2*Math.PI); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx-s*0.3,cy-s*0.2); ctx.lineTo(cx+s*0.3,cy+s*0.2); ctx.stroke();
            break;
        case 'thermostat':
            ctx.beginPath(); ctx.arc(cx, cy, s*0.45, 0, 2*Math.PI); ctx.fill();
            ctx.fillStyle = '#fff'; ctx.font = `bold ${s*0.6}px sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('T', cx, cy+1);
            break;
        case 'light':
            ctx.beginPath(); ctx.arc(cx, cy, s*0.5, 0, 2*Math.PI); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx-s*0.5,cy); ctx.lineTo(cx+s*0.5,cy); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx,cy-s*0.5); ctx.lineTo(cx,cy+s*0.5); ctx.stroke();
            break;
        case 'emergency_light':
            ctx.fillRect(cx-s*0.6, cy-s*0.4, s*1.2, s*0.8);
            ctx.fillStyle = '#fff'; ctx.font = `bold ${s*0.4}px sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('EL', cx, cy+1);
            break;
        case 'spotlight':
            ctx.beginPath(); ctx.arc(cx, cy-s*0.2, s*0.3, 0, 2*Math.PI); ctx.fill();
            ctx.beginPath(); ctx.moveTo(cx-s*0.5,cy+s*0.5); ctx.lineTo(cx,cy-s*0.2); ctx.lineTo(cx+s*0.5,cy+s*0.5); ctx.stroke();
            break;
        case 'track_light':
            ctx.fillRect(cx-s*0.8, cy-s*0.15, s*1.6, s*0.3);
            for (let i=0;i<3;i++) { ctx.beginPath(); ctx.moveTo(cx-s*0.5+i*s*0.5,cy+s*0.15); ctx.lineTo(cx-s*0.5+i*s*0.5,cy+s*0.6); ctx.stroke(); }
            break;
        case 'outlet':
            ctx.strokeRect(cx-s*0.45, cy-s*0.5, s*0.9, s*1.0);
            ctx.beginPath(); ctx.arc(cx-s*0.15, cy-s*0.05, s*0.15, 0, 2*Math.PI); ctx.fill();
            ctx.beginPath(); ctx.arc(cx+s*0.15, cy-s*0.05, s*0.15, 0, 2*Math.PI); ctx.fill();
            break;
        case 'switch':
            ctx.beginPath(); ctx.arc(cx, cy, s*0.4, 0, 2*Math.PI); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(cx,cy-s*0.25); ctx.lineTo(cx,cy+s*0.25); ctx.stroke();
            ctx.fillStyle = color; ctx.font = `bold ${s*0.35}px sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('S', cx, cy+s*0.3);
            break;
        case 'usb_outlet':
            ctx.strokeRect(cx-s*0.45, cy-s*0.45, s*0.9, s*0.9);
            ctx.fillRect(cx-s*0.3, cy-s*0.3, s*0.6, s*0.6);
            ctx.fillStyle = '#fff'; ctx.font = `bold ${s*0.45}px sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('U', cx, cy+1);
            break;
        case 'data_port':
            ctx.strokeRect(cx-s*0.35, cy-s*0.45, s*0.7, s*0.9);
            ctx.fillStyle = color; ctx.font = `bold ${s*0.5}px sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('D', cx, cy+1);
            break;
        case 'panel':
            ctx.fillRect(cx-s*0.8, cy-s*0.6, s*1.6, s*1.2);
            ctx.fillStyle = 'rgba(255,255,255,0.4)';
            for (let i=0;i<4;i++) ctx.fillRect(cx-s*0.6, cy-s*0.4+i*s*0.27, s*1.2, 1);
            break;
        case 'junction_box':
            ctx.fillRect(cx-s*0.3, cy-s*0.3, s*0.6, s*0.6);
            break;
        case 'transformer':
            ctx.beginPath(); ctx.arc(cx, cy, s*0.6, 0, 2*Math.PI); ctx.stroke();
            for (let i=0;i<3;i++) {
                ctx.beginPath(); ctx.arc(cx-s*0.2+i*s*0.2, cy, s*0.12, 0, 2*Math.PI); ctx.stroke();
            }
            break;
        case 'generator':
            ctx.fillRect(cx-s*0.8, cy-s*0.6, s*1.6, s*1.2);
            ctx.fillStyle = '#fff'; ctx.font = `bold ${s*0.7}px sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('G', cx, cy+1);
            break;
        case 'dome_cam':
            ctx.beginPath(); ctx.arc(cx, cy, s*0.5, 0, 2*Math.PI); ctx.fill();
            ctx.fillStyle = '#333'; ctx.beginPath(); ctx.arc(cx, cy, s*0.2, 0, 2*Math.PI); ctx.fill();
            break;
        case 'bullet_cam':
            ctx.fillRect(cx-s*0.3, cy-s*0.3, s*0.6, s*0.6);
            ctx.fillStyle = '#555'; ctx.fillRect(cx-s*0.15, cy-s*0.45, s*0.3, s*0.7);
            break;
        case 'nvr':
            ctx.fillRect(cx-s*0.8, cy-s*0.4, s*1.6, s*0.8);
            ctx.fillStyle = 'rgba(255,255,255,0.3)';
            for (let i=0;i<3;i++) ctx.fillRect(cx-s*0.6, cy-s*0.25+i*s*0.25, s*1.2, 1);
            break;
        case 'ups':
            ctx.fillRect(cx-s*0.7, cy-s*0.5, s*1.4, s*1.0);
            ctx.fillStyle = '#fff'; ctx.font = `bold ${s*0.35}px sans-serif`;
            ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText('UPS', cx, cy+1);
            break;
        default:
            ctx.beginPath(); ctx.arc(cx, cy, s*0.4, 0, 2*Math.PI); ctx.stroke();
    }
    return c.toDataURL();
}

// ── Load discipline ────────────────────────────────────────────
async function loadDiscipline(idx) {
    currentIdx = idx;
    document.querySelectorAll('.disc-tab').forEach((el,i) => el.classList.toggle('active', i===idx));
    document.getElementById('loading').style.display = 'flex';
    document.getElementById('loading').querySelector('div').textContent = '載入中...';

    try {
        // Load floor plan bg
        const img = document.getElementById('floorplan-bg');
        img.src = '/api/overlay/floorplan-img?' + Date.now();
        await new Promise(r => { img.onload = r; setTimeout(r, 10000); });

        if (!img.naturalWidth) {
            // Retry once
            img.src = '/api/overlay/floorplan-img?' + Date.now();
            await new Promise(r => { img.onload = r; setTimeout(r, 10000); });
        }

        bgW = img.naturalWidth;
        bgH = img.naturalHeight;
        if (!bgW) { bgW = 1000; bgH = 800; } // fallback size
        layerStack.style.width = bgW + 'px';
        layerStack.style.height = bgH + 'px';
        userSymLayer.style.width = bgW + 'px';
        userSymLayer.style.height = bgH + 'px';

        // Load layer info
        await loadLayers(idx);
        renderSymbolPalette();
        loadUserSymbols();
    } catch(err) {
        console.error('loadDiscipline error:', err);
    }

    document.getElementById('loading').style.display = 'none';
    fitView();
}

async function loadLayers(idx) {
    const resp = await fetch(`/api/overlay/layers/${idx}`);
    const layers = await resp.json();
    const el = document.getElementById('layer-toggles');
    const noLayers = document.getElementById('no-layers');

    // Remove old layer images
    document.querySelectorAll('.layer-img').forEach(el2 => el2.remove());

    if (!layers.length) {
        el.innerHTML = '';
        noLayers.style.display = 'block';
        return;
    }
    noLayers.style.display = 'none';

    layerVisible = {};
    el.innerHTML = layers.map(l => {
        layerVisible[l.name] = true;
        const isCircle = ['FIRE_EQUIP','OUTLET','CCTV_EQUIP','ELEC_EQUIP','AC_EQUIP','LIGHT_EQUIP'].includes(l.name);
        const swatch = isCircle
            ? `<span class="dot" style="background:${l.color}"></span>`
            : `<span class="swatch" style="background:${l.color}"></span>`;
        return `<label class="layer-toggle">
            <input type="checkbox" checked onchange="toggleLayer('${l.name}', this.checked)">
            ${swatch}${l.label}
        </label>`;
    }).join('');

    // Load each layer as transparent PNG
    for (const l of layers) {
        const layerImg = document.createElement('img');
        layerImg.className = 'layer-img';
        layerImg.dataset.layer = l.name;
        layerImg.style.width = '100%';
        layerImg.style.height = '100%';
        layerImg.src = `/api/overlay/layer-img/${idx}/${l.name}?t=${Date.now()}`;
        layerStack.appendChild(layerImg);
    }
}

function toggleLayer(name, visible) {
    layerVisible[name] = visible;
    document.querySelectorAll(`.layer-img[data-layer="${name}"]`).forEach(el => {
        el.style.display = visible ? 'block' : 'none';
    });
}

// ── User Symbols ──────────────────────────────────────────────
function loadUserSymbols() {
    renderUserSymbols();
    updateSymCount();
}

function placeSymbol(type, color, size, label, x, y) {
    const id = 'sym_' + (++symCounter);
    userSymbols.push({id, type, color: color || '#E74C3C', size: size || 12, label: label || '', x: x || 500, y: y || 400, angle: 0});
    renderUserSymbols();
    updateSymCount();
    return id;
}

function renderUserSymbols() {
    userSymLayer.innerHTML = '';
    userSymbols.forEach(sym => {
        const el = document.createElement('div');
        el.className = 'user-sym' + (sym.id === selectedSymId ? ' selected' : '');
        el.dataset.id = sym.id;
        const sz = sym.size * 1.8;
        el.style.left = sym.x + 'px';
        el.style.top = sym.y + 'px';
        el.style.width = sz + 'px';
        el.style.height = sz + 'px';
        el.style.transform = `translate(-50%, -50%) rotate(${sym.angle||0}deg)`;

        const icon = drawSymbolCanvas(sym.type, sym.color, Math.round(sz));
        el.innerHTML = `<img class="sym-svg" src="${icon}" draggable="false">
            <div class="sym-label">${sym.label}</div>`;

        el.addEventListener('mousedown', (e) => {
            e.stopPropagation();
            selectSymbol(sym.id);
            startSymDrag(e);
        });
        el.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            selectSymbol(sym.id);
            openProperties();
        });
        userSymLayer.appendChild(el);
    });
}

function selectSymbol(id) {
    selectedSymId = id;
    // Toggle class on existing elements — don't rebuild DOM
    document.querySelectorAll('.user-sym').forEach(el => {
        el.classList.toggle('selected', el.dataset.id === id);
    });
    const sym = userSymbols.find(s => s.id === id);
    if (sym) {
        document.getElementById('prop-no-sel').style.display = 'none';
        document.getElementById('prop-fields').style.display = 'block';
        document.getElementById('prop-type').textContent = sym.type;
        document.getElementById('prop-x').value = Math.round(sym.x);
        document.getElementById('prop-y').value = Math.round(sym.y);
        document.getElementById('prop-angle').value = sym.angle || 0;
        document.getElementById('prop-label').value = sym.label || '';
        document.getElementById('right-panel').style.display = '';
    }
}

function deselectSym() {
    selectedSymId = null;
    document.getElementById('prop-no-sel').style.display = 'block';
    document.getElementById('prop-fields').style.display = 'none';
    document.querySelectorAll('.user-sym').forEach(el => el.classList.remove('selected'));
}

function openProperties() {
    document.getElementById('right-panel').style.display = '';
}

function updateSymFromProp() {
    if (!selectedSymId) return;
    const sym = userSymbols.find(s => s.id === selectedSymId);
    if (!sym) return;
    sym.x = parseFloat(document.getElementById('prop-x').value) || 0;
    sym.y = parseFloat(document.getElementById('prop-y').value) || 0;
    sym.angle = parseInt(document.getElementById('prop-angle').value) || 0;
    sym.label = document.getElementById('prop-label').value || '';
    const el = document.querySelector(`.user-sym[data-id="${selectedSymId}"]`);
    if (el) {
        el.style.left = sym.x + 'px';
        el.style.top = sym.y + 'px';
        el.style.transform = `translate(-50%, -50%) rotate(${sym.angle}deg)`;
        const lbl = el.querySelector('.sym-label');
        if (lbl) lbl.textContent = sym.label;
    }
}

function deleteSelectedSym() {
    if (!selectedSymId) return;
    userSymbols = userSymbols.filter(s => s.id !== selectedSymId);
    selectedSymId = null;
    document.getElementById('prop-no-sel').style.display = 'block';
    document.getElementById('prop-fields').style.display = 'none';
    renderUserSymbols();
    updateSymCount();
}

function startSymDrag(e) {
    const sym = userSymbols.find(s => s.id === selectedSymId);
    if (!sym) return;
    dragSymId = sym.id;
    const rect = imageArea.getBoundingClientRect();
    const startX = e.clientX, startY = e.clientY;
    const origX = sym.x, origY = sym.y;

    function onMove(ev) {
        if (!dragSymId) return;
        const s = bgW / layerStack.offsetWidth;
        const dx = (ev.clientX - startX) / zoom * s;
        const dy = (ev.clientY - startY) / zoom * s;
        const c = userSymbols.find(x => x.id === dragSymId);
        if (c) {
            c.x = Math.max(0, origX + dx);
            c.y = Math.max(0, origY + dy);
            // Update DOM directly without full rebuild
            const el = document.querySelector(`.user-sym[data-id="${c.id}"]`);
            if (el) {
                el.style.left = c.x + 'px';
                el.style.top = c.y + 'px';
            }
        }
    }
    function onUp() {
        dragSymId = null;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        renderUserSymbols(); // sync DOM after drag completes
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

function updateSymCount() {
    document.getElementById('sym-count').textContent = userSymbols.length + ' symbols';
}

function showToast(msg, isError) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.style.background = isError ? 'rgba(220,38,38,0.85)' : 'rgba(0,0,0,0.75)';
    el.style.opacity = 1;
    setTimeout(() => { el.style.opacity = 0; }, 2000);
}

// ── Drop handler ──────────────────────────────────────────────
imageArea.addEventListener('dragover', (e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; });
imageArea.addEventListener('drop', (e) => {
    e.preventDefault();
    try {
        const data = JSON.parse(e.dataTransfer.getData('text/plain'));
        if (!data.type) return;
        const rect = imageArea.getBoundingClientRect();
        const scale = zoom;
        const px = (e.clientX - rect.left - panX) / scale * (bgW / layerStack.offsetWidth);
        const py = (e.clientY - rect.top - panY) / scale * (bgH / layerStack.offsetHeight);
        const symId = placeSymbol(data.type, data.color, data.size, data.label, px, py);
        if (symId) showToast('已放置 ' + (data.label||data.type));
    } catch(err) {
        console.error('Drop error:', err);
        showToast('放置失敗: ' + err.message, true);
    }
});

// ── Pan / Zoom ─────────────────────────────────────────────────
function updateTransform() {
    layerStack.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
    userSymLayer.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
    document.getElementById('zoom-info').textContent = Math.round(zoom*100) + '%';
}
function zoomIn() { zoom *= 1.3; updateTransform(); }
function zoomOut() { zoom /= 1.3; if (zoom<0.05) zoom=0.05; updateTransform(); }
function resetView() { zoom=1; panX=0; panY=0; updateTransform(); }
function fitView() {
    const cw = imageArea.clientWidth, ch = imageArea.clientHeight;
    const sX = (cw-20)/bgW, sY = (ch-20)/bgH;
    zoom = Math.min(sX, sY, 3);
    panX = (cw - bgW*zoom)/2; panY = (ch - bgH*zoom)/2;
    updateTransform();
}
imageArea.addEventListener('mousedown', (e) => {
    if (e.target === imageArea || e.target.id === 'layer-stack' || e.target.id === 'floorplan-bg') {
        isPanning = true; panStart = {x: e.clientX - panX, y: e.clientY - panY};
        deselectSym();
    }
});
document.addEventListener('mousemove', (e) => { if (!isPanning) return; panX = e.clientX - panStart.x; panY = e.clientY - panStart.y; updateTransform(); });
document.addEventListener('mouseup', () => { isPanning = false; });
imageArea.addEventListener('wheel', (e) => {
    e.preventDefault();
    const rect = imageArea.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const d = e.deltaY > 0 ? 0.9 : 1.1;
    const nz = zoom * d;
    if (nz < 0.05 || nz > 20) return;
    panX = mx - (mx - panX) * (nz/zoom); panY = my - (my - panY) * (nz/zoom);
    zoom = nz; updateTransform();
}, {passive: false});

// Keyboard
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') deselectSym();
    if ((e.key === 'Delete' || e.key === 'Backspace') && selectedSymId) { deleteSelectedSym(); }
    const n = parseInt(e.key);
    if (n >= 1 && n <= 6) loadDiscipline(n-1);
});
window.addEventListener('resize', () => { fitView(); });

// ── Export ─────────────────────────────────────────────────────
async function exportPDF() {
    document.getElementById('loading').style.display = 'flex';
    document.getElementById('loading').querySelector('div').textContent = '生成 PDF...';
    try {
        const visibleLayers = Object.entries(layerVisible).filter(([,v]) => v).map(([k]) => k);
        const resp = await fetch('/api/overlay/generate-pdf', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({discipline_idx: currentIdx, symbols: userSymbols, visible_layers: visibleLayers}),
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'YONEX_參考圖_' + DISCIPLINES[currentIdx].id + '.pdf';
        a.click(); URL.revokeObjectURL(url);
    } catch(e) { alert('PDF生成失敗: ' + e.message); }
    document.getElementById('loading').querySelector('div').textContent = '載入中...';
    document.getElementById('loading').style.display = 'none';
}

function exportJSON() {
    const data = JSON.stringify({
        discipline: currentIdx,
        symbols: userSymbols,
        layer_visible: layerVisible,
    }, null, 2);
    const blob = new Blob([data], {type:'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'overlay_symbols.json';
    a.click(); URL.revokeObjectURL(url);
}

function importJSON(event) {
    const file = event.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
        try {
            const data = JSON.parse(e.target.result);
            if (data.symbols) { userSymbols = data.symbols; renderUserSymbols(); updateSymCount(); }
            if (data.discipline !== undefined) loadDiscipline(data.discipline);
        } catch(err) { alert('匯入失敗: ' + err.message); }
    };
    reader.readAsText(file);
    event.target.value = '';
}

function resetSymbols() {
    if (!confirm('清除所有放置的符號？')) return;
    userSymbols = [];
    selectedSymId = null;
    document.getElementById('prop-no-sel').style.display = 'block';
    document.getElementById('prop-fields').style.display = 'none';
    renderUserSymbols();
    updateSymCount();
}

// ── Floorplan Upload ──────────────────────────────────────────
async function uploadFloorplan(event) {
    const file = event.target.files[0];
    if (!file) return;
    document.getElementById('loading').style.display = 'flex';
    document.getElementById('loading').querySelector('div').textContent = '上傳平面圖...';
    try {
        const base64 = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result.split(',')[1]);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
        const resp = await fetch('/api/upload-floorplan', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({data: base64, filename: file.name}),
        });
        const result = await resp.json();
        if (!result.ok) throw new Error(result.error || 'Upload failed');
        // Reload current discipline with new floorplan
        await loadDiscipline(currentIdx);
        document.getElementById('loading').querySelector('div').textContent = '載入中...';
        document.getElementById('loading').style.display = 'none';
    } catch(e) {
        alert('上傳失敗: ' + e.message);
        document.getElementById('loading').style.display = 'none';
    }
    event.target.value = '';
}

async function resetFloorplan() {
    if (!confirm('重置為預設平面圖？將清除所有圖層快取。')) return;
    await fetch('/api/reset-floorplan', {method: 'POST'});
    await loadDiscipline(currentIdx);
}

// ── Start ──────────────────────────────────────────────────────
init();
</script>
</body>
</html>
"""


# ── HTTP Handler ─────────────────────────────────────────────────────

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
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(body)

    def _png_file(self, path):
        data = Path(path).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if path == "/" or path == "/overlay-viewer":
                html = HTML_TEMPLATE
                html = html.replace("__DISCIPLINES_JSON__", json.dumps(DISCIPLINES, ensure_ascii=False))
                html = html.replace("__SYMBOLS_JSON__", json.dumps(SYMBOLS, ensure_ascii=False))
                self._html(html)

            elif path == "/api/overlay/floorplan-img":
                p = render_floorplan_png()
                self._png_file(p)

            elif path.startswith("/api/overlay/layer-img/"):
                parts = path.split("/")
                idx = int(parts[-2])
                layer = parts[-1]
                if idx < 0 or idx >= len(DISCIPLINES):
                    self._json({"error": "invalid index"}, 404)
                    return
                p = render_layer_png(idx, layer)
                self._png_file(p)

            elif path.startswith("/api/overlay/layers/"):
                idx = int(path.split("/")[-1])
                if idx < 0 or idx >= len(DISCIPLINES):
                    self._json({"error": "invalid index"}, 404)
                    return
                used = get_used_layers(idx)
                result = []
                for ln in sorted(used):
                    if ln in LAYER_CONFIG:
                        result.append({
                            "name": ln,
                            "label": LAYER_CONFIG[ln]["label"],
                            "color": LAYER_CONFIG[ln]["color"],
                        })
                self._json(result)

            elif path == "/api/overlay/symbols":
                self._json(SYMBOLS)

            else:
                self._json({"error": "not found"}, 404)

        except Exception as e:
            logger.exception("GET error")
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if path == "/api/overlay/generate-pdf":
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                disc_idx = body.get("discipline_idx", 0)
                symbols = body.get("symbols", [])
                cameras = body.get("cameras", [])  # legacy
                pdf_path = generate_pdf(cameras, symbols, disc_idx)
                data = Path(pdf_path).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/pdf")
                fname = f'YONEX_{DISCIPLINES[disc_idx]["id"]}.pdf'
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            elif path == "/api/upload-floorplan":
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                raw = base64.b64decode(body["data"])
                custom_pdf = CACHE_DIR / "custom_floorplan.pdf"
                custom_pdf.write_bytes(raw)
                # Clear custom cache
                for f in CACHE_DIR.glob("floorplan_custom*"):
                    f.unlink()
                # Also invalidate layer caches
                for f in CACHE_DIR.glob("*.png"):
                    if f.name != "floorplan.png":
                        f.unlink()
                self._json({"ok": True, "message": "已上傳自訂平面圖"})

            elif path == "/api/reset-floorplan":
                for f in CACHE_DIR.glob("custom_floorplan*"):
                    f.unlink()
                for f in CACHE_DIR.glob("floorplan_custom*"):
                    f.unlink()
                self._json({"ok": True, "message": "已重置為預設平面圖"})

            else:
                self._json({"error": "not found"}, 404)

        except Exception as e:
            logger.exception("POST error")
            self._json({"error": str(e)}, 500)

    def log_message(self, fmt, *args):
        pass


def pre_cache():
    logger.info("Pre-caching floor plan...")
    render_floorplan_png()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    port = 8892
    pre_cache()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    logger.info("Overlay Editor → http://localhost:%d/overlay-viewer", port)
    print(f"\n  📐 http://localhost:{port}/overlay-viewer")
    print(f"    圖層切換 | 專業符號拖放 | PDF生成\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
