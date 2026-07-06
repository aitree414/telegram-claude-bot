"""
CCTV Layout Designer — Interactive HTML + PDF Generator
Serves an interactive floor plan with draggable cameras.
POST /api/cctv/generate-pdf → generates updated PDF.
"""
import json, math, os, io, logging
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
PDF_PATH = Path("/Volumes/Apollo Sync Folder/PicoTW/2026/Yonex for TREE/CAD/26.06.01-YONEX 敦南旗艦店平面圖.pdf")
OUTPUT_DIR = BASE_DIR

# Default camera positions (same as cctv_plan.py)
DEFAULT_CAMERAS = [
    {"id": "CAM-01", "label": "入口 進店",     "x": 290, "y": 520, "angle": 135, "fov": 90,  "type": "dome", "color": "red"},
    {"id": "CAM-02", "label": "入口 反向",     "x": 720, "y": 520, "angle": 315, "fov": 90,  "type": "dome", "color": "red"},
    {"id": "CAM-03", "label": "左上儲藏室",     "x": 370, "y": 150, "angle": 135, "fov": 100, "type": "dome", "color": "green"},
    {"id": "CAM-04", "label": "左展示區",       "x": 450, "y": 450, "angle": 135, "fov": 90,  "type": "dome", "color": "blue"},
    {"id": "CAM-05", "label": "左區後方",       "x": 450, "y": 650, "angle": 180, "fov": 90,  "type": "dome", "color": "blue"},
    {"id": "CAM-06", "label": "櫃檯收銀① 方頭", "x": 620, "y": 250, "angle": 315, "fov": 60,  "type": "bullet", "color": "orange"},
    {"id": "CAM-07", "label": "中展示區",       "x": 730, "y": 450, "angle": 270, "fov": 90,  "type": "dome", "color": "blue"},
    {"id": "CAM-08", "label": "中區後方",       "x": 730, "y": 650, "angle": 90,  "fov": 90,  "type": "dome", "color": "blue"},
    {"id": "CAM-09", "label": "右展示區",       "x": 880, "y": 450, "angle": 270, "fov": 90,  "type": "dome", "color": "blue"},
    {"id": "CAM-10", "label": "右區後方",       "x": 880, "y": 650, "angle": 90,  "fov": 90,  "type": "dome", "color": "blue"},
    {"id": "CAM-11", "label": "櫃檯收銀② 方頭", "x": 550, "y": 270, "angle": 45,  "fov": 60,  "type": "bullet", "color": "orange"},
]

COLORS = {
    "blue":   (0.13, 0.59, 0.95),
    "green":  (0.30, 0.68, 0.31),
    "orange": (1.00, 0.60, 0.00),
    "red":    (0.85, 0.15, 0.08),
}


def generate_pdf(cameras: list[dict], output_path: str | Path) -> str:
    """Generate a CCTV layout PDF from camera position data."""
    doc = fitz.open(PDF_PATH)
    src = doc[0]
    pr = src.rect

    out = fitz.open()
    page = out.new_page(width=pr.width, height=pr.height)

    # Background floor plan
    pix = src.get_pixmap(matrix=fitz.Matrix(200/72, 200/72))
    page.insert_image(pr, pixmap=pix)
    doc.close()

    # Title
    page.insert_text(fitz.Point(30, 25),
        "YONEX TAIPEI SHOWROOM — 監視器配置圖 CCTV Layout",
        fontname="helv", fontsize=13, color=(0, 0.24, 0.65))
    page.insert_text(fitz.Point(30, 42),
        "VIVOTEK 5MP PoE  |  9× FD9380 Dome + 2× IB9380 Bullet  |  NVR × 1",
        fontname="helv", fontsize=6.5, color=(0.4, 0.4, 0.4))

    domes = sum(1 for c in cameras if c["type"] == "dome")
    bullets = sum(1 for c in cameras if c["type"] == "bullet")
    page.insert_text(fitz.Point(30, 55),
        f"{domes + bullets} cameras ({domes} Dome + {bullets} Bullet)  |  NVR in storage + UPS",
        fontname="helv", fontsize=6, color=(0.6, 0.6, 0.6))

    def draw_cam(cam):
        cx, cy = cam["x"], cam["y"]
        angle, fov = cam["angle"], cam["fov"]
        c = COLORS.get(cam["color"], (0.13, 0.59, 0.95))
        a_rad = math.radians(angle)
        f_rad = math.radians(fov)
        clen = 50

        left_a = a_rad - f_rad / 2
        right_a = a_rad + f_rad / 2

        # Camera icon
        r = 5
        if cam["type"] == "bullet":
            page.draw_rect(fitz.Rect(cx - r, cy - r, cx + r, cy + r), color=c, fill=c)
        else:
            page.draw_circle((cx, cy), r, color=c, fill=c)

        # FOV cone
        n = 11
        for i in range(n):
            a = left_a + (right_a - left_a) * i / (n - 1)
            page.draw_line((cx, cy),
                           (cx + clen * math.cos(a), cy + clen * math.sin(a)),
                           color=c, width=0.25)

        # Center axis
        mx = cx + clen * 0.6 * math.cos(a_rad)
        my = cy + clen * 0.6 * math.sin(a_rad)
        page.draw_line((cx, cy), (mx, my), color=c, width=0.6)

        # Arc
        prev = None
        for i in range(n):
            a = left_a + (right_a - left_a) * i / (n - 1)
            px = cx + clen * math.cos(a)
            py = cy + clen * math.sin(a)
            if prev:
                page.draw_line(prev, (px, py), color=c, width=0.35)
            prev = (px, py)

        # Label
        page.insert_text(fitz.Point(cx + 7, cy - 10), cam["id"],
                         fontname="helv", fontsize=6, color=c)
        page.insert_text(fitz.Point(cx + 7, cy - 2), cam["label"],
                         fontname="helv", fontsize=4.5, color=(0.4, 0.4, 0.4))

    for cam in cameras:
        draw_cam(cam)

    # Legend
    lx, ly = 730, 700
    page.draw_rect(fitz.Rect(lx, ly, lx + 200, ly + 88),
                   color=(0.7, 0.7, 0.7), fill=(0.95, 0.95, 0.95))
    page.insert_text(fitz.Point(lx + 8, ly + 12), "圖例 Legend",
                     fontname="helv", fontsize=8, color=(0.2, 0.2, 0.2))

    legend = [
        ("blue",   "FD9380 Dome (5MP) 展示區"),
        ("green",  "FD9380 Dome (5MP) 後場/儲藏"),
        ("orange", "IB9380 Bullet (5MP) 櫃檯"),
        ("red",    "FD9380 Dome (5MP) 入口"),
    ]
    for i, (cn, txt) in enumerate(legend):
        px, py2 = lx + 12, ly + 26 + i * 14
        cc = COLORS[cn]
        if cn == "orange":
            page.draw_rect(fitz.Rect(px - 4, py2 - 4, px + 4, py2 + 4), color=cc, fill=cc)
        else:
            page.draw_circle((px, py2), 4, color=cc, fill=cc)
        page.insert_text(fitz.Point(px + 10, py2 + 2), txt,
                         fontname="helv", fontsize=5, color=(0.3, 0.3, 0.3))

    # FOV sample
    fx, fy = lx + 12, ly + 26 + 4 * 14 + 2
    page.draw_line((fx, fy), (fx + 16, fy - 4), color=(0.5, 0.5, 0.5), width=0.4)
    page.draw_line((fx, fy), (fx + 16, fy + 4), color=(0.5, 0.5, 0.5), width=0.4)
    page.insert_text(fitz.Point(fx + 20, fy + 2), "拍攝範圍 (FOV)",
                     fontname="helv", fontsize=5, color=(0.5, 0.5, 0.5))

    # NVR
    px, py2 = lx + 100, ly + 26 + 4 * 14 + 6
    page.draw_rect(fitz.Rect(px, py2 - 4, px + 10, py2 + 4),
                   color=(0.85, 0.15, 0.08), fill=(0.85, 0.15, 0.08))
    page.insert_text(fitz.Point(px + 14, py2 + 2), "NVR 主機",
                     fontname="helv", fontsize=5, color=(0.5, 0.5, 0.5))

    out.save(str(output_path), deflate=True, garbage=4)
    out.close()
    return str(output_path)


# ── HTML Template ───────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CCTV 配置設計工具</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; }
body { background: #1a1a2e; color: white; overflow-x: hidden; }

/* Top toolbar */
.toolbar {
    display: flex; align-items: center; gap: 12px; padding: 10px 20px;
    background: #16213e; border-bottom: 1px solid rgba(255,255,255,0.1);
    position: sticky; top: 0; z-index: 1000; flex-wrap: wrap;
}
.toolbar h1 { font-size: 1.1rem; margin-right: 20px; color: #f59e0b; }
.toolbar button {
    padding: 6px 16px; border-radius: 6px; border: none; cursor: pointer;
    font-size: 0.82rem; font-weight: 600; transition: all 0.2s;
}
.btn-primary { background: #3b82f6; color: white; }
.btn-primary:hover { background: #2563eb; }
.btn-success { background: #10b981; color: white; }
.btn-success:hover { background: #059669; }
.btn-warning { background: #f59e0b; color: #1a1a2e; }
.btn-danger { background: #ef4444; color: white; }
.btn-outline { background: transparent; color: rgba(255,255,255,0.7); border: 1px solid rgba(255,255,255,0.2); }
.btn-outline:hover { background: rgba(255,255,255,0.1); }

/* Floor plan container */
#floorplan-container {
    position: relative; margin: 20px auto; cursor: grab;
    background: #0f172a; border-radius: 8px; overflow: hidden;
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    /* Size set by JS based on image */
}
#floorplan-container:active { cursor: grabbing; }
#floorplan-bg { display: block; width: 100%; height: auto; pointer-events: none; }
#camera-layer { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; }

/* Camera icon */
.camera {
    position: absolute; pointer-events: auto; cursor: move;
    width: 40px; height: 40px; transform: translate(-50%, -50%);
    user-select: none; z-index: 10;
}
.camera-icon {
    width: 20px; height: 20px; border-radius: 50%;
    position: relative; top: 50%; left: 50%;
    transform: translate(-50%, -50%);
    border: 2px solid white; box-shadow: 0 0 8px rgba(0,0,0,0.5);
    transition: transform 0.1s;
}
.camera.bullet .camera-icon { border-radius: 3px; }
.camera.selected .camera-icon { transform: translate(-50%, -50%) scale(1.3); border-color: #fbbf24; box-shadow: 0 0 12px rgba(251,191,36,0.6); }
.camera-label {
    position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
    font-size: 10px; white-space: nowrap; text-shadow: 0 1px 3px rgba(0,0,0,0.8);
    padding: 1px 4px; border-radius: 3px; margin-top: 2px;
    pointer-events: none;
}
.camera .cam-dir {
    position: absolute; top: 0; left: 0; pointer-events: none; z-index: 3;
}
.camera .fov-cone {
    position: absolute; top: 50%; left: 50%; pointer-events: none;
    transform-origin: 0 0;
}

/* FOV drawn via canvas overlay */
#fov-canvas { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 5; }

/* Properties panel */
#panel {
    position: fixed; right: -350px; top: 60px; width: 320px; height: calc(100vh - 60px);
    background: #16213e; border-left: 1px solid rgba(255,255,255,0.1);
    transition: right 0.3s; padding: 20px; overflow-y: auto; z-index: 500;
}
#panel.open { right: 0; }
#panel h2 { font-size: 1rem; margin-bottom: 16px; color: #f59e0b; }
#panel .field { margin-bottom: 12px; }
#panel label { display: block; font-size: 0.78rem; color: rgba(255,255,255,0.5); margin-bottom: 4px; }
#panel input, #panel select {
    width: 100%; padding: 6px 10px; border-radius: 6px; border: 1px solid rgba(255,255,255,0.15);
    background: rgba(255,255,255,0.05); color: white; font-size: 0.85rem;
}
#panel input:focus, #panel select:focus { outline: none; border-color: #3b82f6; }
#panel .row { display: flex; gap: 10px; }
#panel .row .field { flex: 1; }
#panel .btn-row { display: flex; gap: 8px; margin-top: 16px; }
#panel .btn-row button { flex: 1; }
#panel-close { position: absolute; top: 12px; right: 12px; background: none; border: none; color: rgba(255,255,255,0.4); font-size: 1.2rem; cursor: pointer; }
#panel-close:hover { color: white; }

/* Camera list sidebar */
#camera-list-panel {
    position: fixed; left: -280px; top: 60px; width: 260px; height: calc(100vh - 60px);
    background: #16213e; border-right: 1px solid rgba(255,255,255,0.1);
    transition: left 0.3s; padding: 16px; overflow-y: auto; z-index: 500;
}
#camera-list-panel.open { left: 0; }
#camera-list-panel h3 { font-size: 0.9rem; margin-bottom: 12px; color: rgba(255,255,255,0.6); }
.cam-list-item {
    display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px;
    cursor: pointer; transition: background 0.15s; font-size: 0.82rem;
}
.cam-list-item:hover { background: rgba(255,255,255,0.05); }
.cam-list-item .dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.cam-list-item.bullet .dot { border-radius: 2px; }

/* Loading / error */
#loading { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; background: #1a1a2e; z-index: 9999; flex-direction: column; gap: 16px; }
#loading .spinner { width: 40px; height: 40px; border: 3px solid rgba(255,255,255,0.1); border-top-color: #f59e0b; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Notification */
#toast { position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%); z-index: 9999; padding: 10px 24px; border-radius: 8px; font-size: 0.85rem; opacity: 0; transition: opacity 0.3s; pointer-events: none; }
#toast.show { opacity: 1; }
#toast.success { background: #065f46; color: #6ee7b7; }
#toast.error { background: #7f1d1d; color: #fca5a5; }

@media (max-width: 768px) {
    #panel { width: 100%; right: -100%; }
    #camera-list-panel { width: 100%; left: -100%; }
}
</style>
</head>
<body>

<div id="loading">
    <div class="spinner"></div>
    <div style="color:rgba(255,255,255,0.6);font-size:0.9rem;">載入平面圖中...</div>
</div>

<div class="toolbar">
    <button class="btn-outline" onclick="toggleCameraList()" title="攝影機列表">≡</button>
    <button class="btn-primary" onclick="addCamera()" style="background:#8b5cf6" title="新增攝影機">＋ CAM</button>
    <h1>🎥 CCTV 配置設計</h1>
    <button class="btn-primary" onclick="centerView()">◉ 置中</button>
    <button class="btn-success" onclick="exportPDF()">📥 生成 PDF</button>
    <button class="btn-warning" onclick="exportJSON()">📋 匯出 JSON</button>
    <button class="btn-outline" onclick="document.getElementById('import-file').click()">📂 匯入</button>
    <input type="file" id="import-file" accept=".json" style="display:none" onchange="importJSON(event)">
    <button class="btn-danger" onclick="resetDefaults()" style="margin-left:auto">↺ 重置</button>
    <span id="camCount" style="font-size:0.8rem;color:rgba(255,255,255,0.4);"></span>
</div>

<div id="floorplan-container">
    <img id="floorplan-bg" alt="Floor Plan" crossorigin="anonymous">
    <div id="camera-layer"></div>
    <canvas id="fov-canvas"></canvas>
</div>

<div id="panel">
    <button id="panel-close" onclick="closePanel()">✕</button>
    <h2 id="panel-title">CAM-00 設定</h2>
    <div class="field">
        <label>標籤 Label</label>
        <input type="text" id="edit-label" onchange="updateCamFromPanel()">
    </div>
    <div class="row">
        <div class="field">
            <label>X 座標</label>
            <input type="number" id="edit-x" onchange="updateCamFromPanel()">
        </div>
        <div class="field">
            <label>Y 座標</label>
            <input type="number" id="edit-y" onchange="updateCamFromPanel()">
        </div>
    </div>
    <div class="row">
        <div class="field">
            <label>角度 Angle°</label>
            <input type="number" id="edit-angle" min="0" max="360" onchange="updateCamFromPanel()">
        </div>
        <div class="field">
            <label>視角 FOV°</label>
            <input type="number" id="edit-fov" min="10" max="180" onchange="updateCamFromPanel()">
        </div>
    </div>
    <div class="row">
        <div class="field">
            <label>類型 Type</label>
            <select id="edit-type" onchange="updateCamFromPanel()">
                <option value="dome">Dome 半球型</option>
                <option value="bullet">Bullet 方頭</option>
            </select>
        </div>
        <div class="field">
            <label>顏色 Color</label>
            <select id="edit-color" onchange="updateCamFromPanel()">
                <option value="blue">藍 展示區</option>
                <option value="green">綠 後場</option>
                <option value="orange">橘 櫃檯</option>
                <option value="red">紅 入口</option>
            </select>
        </div>
    </div>
    <div class="btn-row">
        <button class="btn-primary" onclick="closePanel()">✓ 完成</button>
        <button class="btn-danger" onclick="deleteSelectedCam()">🗑 刪除</button>
    </div>
</div>

<div id="camera-list-panel">
    <h3>攝影機列表</h3>
    <div id="camera-list"></div>
    <div style="margin-top:12px">
        <button class="btn-primary" onclick="addCamera()" style="width:100%;padding:8px">＋ 新增攝影機</button>
    </div>
    <div style="margin-top:8px">
        <button class="btn-outline" onclick="toggleCameraList()" style="width:100%;padding:6px">✕ 關閉</button>
    </div>
</div>

<div id="toast"></div>

<script>
// ── State ──────────────────────────────────────────────────────
let cameras = [];
let selectedId = null;
let bgImage = null;
let scale = 1;  // pixels per PDF pt
let offsetX = 0, offsetY = 0;  // pan offset
let isPanning = false, panStart = {x:0,y:0};
let isRotating = false;
let rotCamId = null;
let dragCamId = null;
let pdfWidth = 0, pdfHeight = 0;
let bgLoaded = false;

const COLORS = {
    blue: '#2196F3', green: '#4CAF50', orange: '#FF9800', red: '#D32F2F'
};

// ── Init ───────────────────────────────────────────────────────
async function init() {
    // Load floor plan image
    const resp = await fetch('/api/cctv/floorplan');
    const data = await resp.json();
    if (!data.ok) { alert('Failed to load: ' + data.error); return; }

    bgImage = new Image();
    bgImage.onload = () => {
        const container = document.getElementById('floorplan-container');
        const bg = document.getElementById('floorplan-bg');
        bg.src = bgImage.src;

        pdfWidth = data.pdf_width;
        pdfHeight = data.pdf_height;

        // Scale image to fit viewport
        const maxW = window.innerWidth - 40;
        const maxH = window.innerHeight - 100;
        const imgAspect = bgImage.width / bgImage.height;
        let dispW, dispH;
        if (maxW / maxH > imgAspect) {
            dispH = maxH;
            dispW = maxH * imgAspect;
        } else {
            dispW = maxW;
            dispH = maxW / imgAspect;
        }
        container.style.width = dispW + 'px';
        container.style.height = dispH + 'px';
        scale = dispW / pdfWidth;

        document.getElementById('loading').style.display = 'none';
        bgLoaded = true;

        // Load cameras
        loadCameras(data.cameras || DEFAULT_CAMERAS);
        renderAll();
    };
    bgImage.src = '/api/cctv/floorplan-img?' + Date.now();
}

// ── Camera Data ────────────────────────────────────────────────
function loadCameras(data) {
    cameras = data.map((c, i) => ({
        id: c.id || 'CAM-' + String(i+1).padStart(2,'0'),
        label: c.label || '',
        x: c.x || 0, y: c.y || 0,
        angle: c.angle || 0, fov: c.fov || 90,
        type: c.type || 'dome',
        color: c.color || 'blue',
    }));
    updateCamCount();
    renderCameraList();
}

function updateCamCount() {
    const domes = cameras.filter(c => c.type === 'dome').length;
    const bullets = cameras.filter(c => c.type === 'bullet').length;
    document.getElementById('camCount').textContent = `${cameras.length} cameras (${domes}D + ${bullets}B)`;
}

// ── Rendering ──────────────────────────────────────────────────
function renderAll() {
    renderCameras();
    renderFOV();
    renderCameraList();
}

function renderCameras() {
    const layer = document.getElementById('camera-layer');
    layer.innerHTML = '';
    cameras.forEach(cam => {
        const el = document.createElement('div');
        el.className = 'camera' + (cam.type === 'bullet' ? ' bullet' : '') + (cam.id === selectedId ? ' selected' : '');
        el.dataset.id = cam.id;
        const px = cam.x * scale + (bgLoaded ? 0 : 0);
        const py = cam.y * scale + (bgLoaded ? 0 : 0);
        el.style.left = px + 'px';
        el.style.top = py + 'px';

        el.innerHTML = `
            <svg class="cam-dir" width="40" height="40" viewBox="0 0 40 40">
                <line x1="20" y1="20" x2="20" y2="6" stroke="rgba(255,255,255,0.9)" stroke-width="2.5" stroke-linecap="round" transform="rotate(${cam.angle} 20 20)"/>
            </svg>
            <div class="camera-icon" style="background:${COLORS[cam.color]||'#2196F3'}"></div>
            <div class="camera-label" style="color:${COLORS[cam.color]||'#2196F3'}">${cam.id}</div>
        `;

        // Rotation handle for selected camera
        if (cam.id === selectedId) {
            const hr = 55;
            const ar = cam.angle * Math.PI / 180;
            const hx = 20 + hr * Math.cos(ar);
            const hy = 20 + hr * Math.sin(ar);
            const handle = document.createElement('div');
            handle.className = 'rot-handle';
            handle.style.cssText = 'position:absolute;left:'+(hx-7)+'px;top:'+(hy-7)+'px;width:14px;height:14px;background:#fbbf24;border:2px solid #fff;border-radius:50%;cursor:grab;z-index:20;box-shadow:0 0 8px rgba(251,191,36,0.6);';
            handle.addEventListener('mousedown', (e) => {
                e.stopPropagation();
                isRotating = true;
                rotCamId = cam.id;
            });
            el.appendChild(handle);
            const lbl = document.createElement('div');
            lbl.style.cssText = 'position:absolute;left:'+(hx+10)+'px;top:'+(hy-8)+'px;font-size:11px;color:#fbbf24;white-space:nowrap;pointer-events:none;font-weight:bold;text-shadow:0 1px 4px rgba(0,0,0,0.9);';
            lbl.textContent = cam.angle + '°';
            el.appendChild(lbl);
        }

        el.addEventListener('mousedown', (e) => {
            e.stopPropagation();
            selectCamera(cam.id);
            startDrag(e);
        });
        el.addEventListener('dblclick', (e) => {
            e.stopPropagation();
            selectCamera(cam.id);
            openPanel();
        });

        layer.appendChild(el);
    });
}

function renderFOV() {
    const canvas = document.getElementById('fov-canvas');
    const container = document.getElementById('floorplan-container');
    canvas.width = container.offsetWidth;
    canvas.height = container.offsetHeight;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    cameras.forEach(cam => {
        const cx = cam.x * scale;
        const cy = cam.y * scale;
        const angleRad = cam.angle * Math.PI / 180;
        const fovRad = cam.fov * Math.PI / 180;
        const clen = 50 * scale;
        const color = COLORS[cam.color] || '#2196F3';

        const leftA = angleRad - fovRad / 2;
        const rightA = angleRad + fovRad / 2;

        ctx.save();
        ctx.globalAlpha = cam.id === selectedId ? 0.5 : 0.2;
        ctx.strokeStyle = color;
        ctx.lineWidth = cam.id === selectedId ? 1.5 : 0.8;

        // Radial lines
        const n = 11;
        for (let i = 0; i < n; i++) {
            const a = leftA + (rightA - leftA) * i / (n - 1);
            const ex = cx + clen * Math.cos(a);
            const ey = cy + clen * Math.sin(a);
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(ex, ey);
            ctx.stroke();
        }

        // Center axis (brighter)
        ctx.globalAlpha = cam.id === selectedId ? 0.8 : 0.5;
        ctx.lineWidth = cam.id === selectedId ? 2 : 1.2;
        const mx = cx + clen * 0.6 * Math.cos(angleRad);
        const my = cy + clen * 0.6 * Math.sin(angleRad);
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(mx, my);
        ctx.stroke();

        // Arc
        ctx.globalAlpha = cam.id === selectedId ? 0.6 : 0.25;
        ctx.lineWidth = cam.id === selectedId ? 1.5 : 0.8;
        ctx.beginPath();
        for (let i = 0; i < n; i++) {
            const a = leftA + (rightA - leftA) * i / (n - 1);
            const px = cx + clen * Math.cos(a);
            const py = cy + clen * Math.sin(a);
            if (i === 0) ctx.moveTo(px, py);
            else ctx.lineTo(px, py);
        }
        ctx.stroke();

        // Rotation ring for selected camera
        if (cam.id === selectedId) {
            ctx.setLineDash([5, 5]);
            ctx.strokeStyle = 'rgba(255,255,255,0.35)';
            ctx.lineWidth = 1.2;
            ctx.beginPath();
            ctx.arc(cx, cy, 55 * scale, 0, 2 * Math.PI);
            ctx.stroke();
            ctx.setLineDash([]);
        }

        ctx.restore();
    });
}

function renderCameraList() {
    const list = document.getElementById('camera-list');
    list.innerHTML = cameras.map(c => `
        <div class="cam-list-item ${c.type}" onclick="selectCamera('${c.id}');openPanel()">
            <span class="dot" style="background:${COLORS[c.color]||'#2196F3'}"></span>
            <span>${c.id}</span>
            <span style="color:rgba(255,255,255,0.4);font-size:0.75rem;margin-left:auto">${c.label||''}</span>
        </div>
    `).join('');
}

// ── Selection ──────────────────────────────────────────────────
function selectCamera(id) {
    selectedId = id;
    renderCameras();
    renderFOV();
    // Update panel if open
    const cam = cameras.find(c => c.id === id);
    if (cam) {
        document.getElementById('panel-title').textContent = cam.id + ' 設定';
        document.getElementById('edit-label').value = cam.label;
        document.getElementById('edit-x').value = Math.round(cam.x);
        document.getElementById('edit-y').value = Math.round(cam.y);
        document.getElementById('edit-angle').value = cam.angle;
        document.getElementById('edit-fov').value = cam.fov;
        document.getElementById('edit-type').value = cam.type;
        document.getElementById('edit-color').value = cam.color;
    }
}

// ── Panel ──────────────────────────────────────────────────────
function openPanel() {
    document.getElementById('panel').classList.add('open');
}
function closePanel() {
    document.getElementById('panel').classList.remove('open');
}
function toggleCameraList() {
    document.getElementById('camera-list-panel').classList.toggle('open');
}

// ── Edit from panel ────────────────────────────────────────────
function updateCamFromPanel() {
    if (!selectedId) return;
    const cam = cameras.find(c => c.id === selectedId);
    if (!cam) return;
    cam.label = document.getElementById('edit-label').value;
    cam.x = parseFloat(document.getElementById('edit-x').value) || 0;
    cam.y = parseFloat(document.getElementById('edit-y').value) || 0;
    cam.angle = parseInt(document.getElementById('edit-angle').value) || 0;
    cam.fov = parseInt(document.getElementById('edit-fov').value) || 90;
    cam.type = document.getElementById('edit-type').value;
    cam.color = document.getElementById('edit-color').value;
    renderAll();
}

function deleteSelectedCam() {
    if (!selectedId) return;
    cameras = cameras.filter(c => c.id !== selectedId);
    selectedId = null;
    closePanel();
    renderAll();
    showToast('已刪除', 'success');
}

function addCamera() {
    const n = cameras.length + 1;
    const id = 'CAM-' + String(n).padStart(2, '0');
    cameras.push({
        id, label: '新攝影機', x: 500, y: 400,
        angle: 0, fov: 90, type: 'dome', color: 'blue',
    });
    selectCamera(id);
    openPanel();
    renderAll();
    showToast('已新增 ' + id, 'success');
}

// ── Drag ───────────────────────────────────────────────────────
function startDrag(e) {
    const cam = cameras.find(c => c.id === selectedId);
    if (!cam) return;
    dragCamId = cam.id;

    const rect = document.getElementById('floorplan-container').getBoundingClientRect();
    const startX = e.clientX;
    const startY = e.clientY;
    const origX = cam.x;
    const origY = cam.y;

    function onMove(ev) {
        if (!dragCamId) return;
        const dx = (ev.clientX - startX) / scale;
        const dy = (ev.clientY - startY) / scale;
        const c = cameras.find(x => x.id === dragCamId);
        if (c) {
            c.x = Math.max(0, origX + dx);
            c.y = Math.max(0, origY + dy);
            renderAll();
        }
    }
    function onUp() {
        dragCamId = null;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

// ── Rotation ───────────────────────────────────────────────────
document.addEventListener('mousemove', (e) => {
    if (!isRotating || !rotCamId) return;
    const container = document.getElementById('floorplan-container');
    const rect = container.getBoundingClientRect();
    const cam = cameras.find(c => c.id === rotCamId);
    if (!cam) return;
    const mx = (e.clientX - rect.left) / scale;
    const my = (e.clientY - rect.top) / scale;
    let angle = Math.atan2(my - cam.y, mx - cam.x) * 180 / Math.PI;
    if (angle < 0) angle += 360;
    cam.angle = Math.round(angle / 5) * 5;
    renderFOV();
    renderCameras();
    updatePanelIfOpen();
});

document.addEventListener('mouseup', () => {
    if (isRotating && rotCamId) {
        const cam = cameras.find(c => c.id === rotCamId);
        if (cam) cam.angle = Math.round(cam.angle);
        renderFOV();
        renderCameras();
        updatePanelIfOpen();
    }
    isRotating = false;
    rotCamId = null;
});

function updatePanelIfOpen() {
    const panel = document.getElementById('panel');
    if (panel.classList.contains('open') && selectedId) {
        const cam = cameras.find(c => c.id === selectedId);
        if (cam) document.getElementById('edit-angle').value = cam.angle;
    }
}

// ── Pan ────────────────────────────────────────────────────────
// Handled by the container's mousedown when not on a camera

// ── Actions ────────────────────────────────────────────────────
function centerView() {
    const container = document.getElementById('floorplan-container');
    container.scrollIntoView({behavior: 'smooth', block: 'center'});
}

async function exportPDF() {
    showToast('正在生成 PDF...', 'success');
    try {
        const resp = await fetch('/api/cctv/generate-pdf', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({cameras}),
        });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const blob = await resp.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'YONEX_CCTV配置圖.pdf';
        a.click();
        URL.revokeObjectURL(url);
        showToast('PDF 已下載!', 'success');
    } catch(e) {
        showToast('生成失敗: ' + e.message, 'error');
    }
}

function exportJSON() {
    const data = JSON.stringify({cameras}, null, 2);
    const blob = new Blob([data], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'cctv_layout.json';
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
            if (data.cameras) {
                loadCameras(data.cameras);
                renderAll();
                showToast('已匯入 ' + data.cameras.length + ' 支攝影機', 'success');
            }
        } catch(err) {
            showToast('匯入失敗: ' + err.message, 'error');
        }
    };
    reader.readAsText(file);
    event.target.value = '';
}

function resetDefaults() {
    if (!confirm('重置所有攝影機到預設位置？')) return;
    loadCameras(DEFAULT_CAMERAS);
    renderAll();
    showToast('已重置', 'success');
}

const DEFAULT_CAMERAS = __CAMERAS_JSON__;

// ── Toast ─────────────────────────────────────────────────────
function showToast(msg, type) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    el.className = 'show ' + type;
    setTimeout(() => el.classList.remove('show'), 3000);
}

// ── Keyboard shortcuts ──────────────────────────────────────────
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePanel();
    if (e.key === 'Delete' && selectedId) { deleteSelectedCam(); }
});

// ── Start ─────────────────────────────────────────────────────
init();
</script>
</body>
</html>
"""


# ── HTTP Handler ────────────────────────────────────────────────────

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
        # Use ASCII-only filename in Content-Disposition (RFC 6266)
        self.send_header("Content-Disposition", "attachment; filename=\"YONEX_CCTV.pdf\"; filename*=UTF-8''YONEX_CCTV%E9%85%8D%E7%BD%AE%E5%9C%96.pdf")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/") or "/"
        try:
            if path == "/" or path == "/cctv-designer":
                # Inject DEFAULT_CAMERAS JSON into template
                html = HTML_TEMPLATE.replace("__CAMERAS_JSON__", json.dumps(DEFAULT_CAMERAS, ensure_ascii=False))
                self._html(html)

            elif path == "/api/cctv/floorplan":
                # Return floorplan metadata + default cameras
                pdf_doc = fitz.open(PDF_PATH)
                pr = pdf_doc[0].rect
                pdf_doc.close()
                self._json({
                    "ok": True,
                    "pdf_width": pr.width,
                    "pdf_height": pr.height,
                    "cameras": DEFAULT_CAMERAS,
                })

            elif path == "/api/cctv/floorplan-img":
                tmp_png = "/tmp/cctv_floorplan_bg.png"
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
            if path == "/api/cctv/generate-pdf":
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cameras_data = body.get("cameras", DEFAULT_CAMERAS)
                output = str(OUTPUT_DIR / "YONEX_CCTV配置圖_自訂.pdf")
                pdf_path = generate_pdf(cameras_data, output)
                self._pdf_response(pdf_path)

            elif path == "/api/cctv/preview":
                # Return a PNG preview of the current layout
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cameras_data = body.get("cameras", DEFAULT_CAMERAS)
                tmp_pdf = "/tmp/cctv_preview.pdf"
                generate_pdf(cameras_data, tmp_pdf)

                # Convert first page to PNG
                doc = fitz.open(tmp_pdf)
                pix = doc[0].get_pixmap(matrix=fitz.Matrix(150/72, 150/72))
                tmp_png = "/tmp/cctv_preview.png"
                pix.save(tmp_png)
                doc.close()
                self._png(tmp_png)

            else:
                self._json({"error": "not found"}, 404)

        except Exception as e:
            logger.exception("POST error")
            self._json({"error": str(e)}, 500)

    def log_message(self, fmt, *args):
        pass


def pre_cache():
    """Pre-render floorplan for fast first access."""
    tmp_png = "/tmp/cctv_floorplan_bg.png"
    if not os.path.exists(tmp_png):
        doc = fitz.open(PDF_PATH)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(200/72, 200/72))
        pix.save(tmp_png)
        doc.close()
        logger.info("Cached floorplan background")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    port = 8891
    pre_cache()
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    logger.info("CCTV Designer → http://localhost:%d/cctv-designer", port)
    print(f"\n  🎥 開啟瀏覽器: http://localhost:{port}/cctv-designer")
    print(f"    拖曳攝影機調整位置，點兩下打開設定面板")
    print(f"    調整完按「生成 PDF」下載\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
