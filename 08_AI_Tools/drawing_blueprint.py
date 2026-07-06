"""
08 Collective — Blueprint-style Production Drawing Generator
=============================================================
Generates SVG technical/production drawings in 08 Collective's
Blueprint style (dark background, cyan lines, orange dimensions).

Usage: Import and call generate_drawing(spec) or use as CLI.
"""

import xml.etree.ElementTree as ET
from datetime import datetime


def _s(sw, *lines):
    """Add lines to SVG content list."""
    for line in lines:
        sw.append(line)


def generate_drawing(config):
    """Generate a Blueprint-style production drawing SVG.

    Config dict:
        title, subtitle, dwg_no, revision, scale, date, client, project
        views: list of view dicts...
        notes: list of strings
        bom: list of {qty, unit, description, spec}
    """
    W, H = 1190, 841  # A3 landscape
    lines = []
    _s(lines,
       '<?xml version="1.0" encoding="UTF-8"?>',
       f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
       '<style>',
       '  text { font-family: "Courier New", "Lucida Console", "Microsoft JhengHei", monospace; }',
       '  .title-lg { fill: #caf0f8; font-size: 18px; font-weight: 700; letter-spacing: 0.05em; }',
       '  .title { fill: #caf0f8; font-size: 11px; font-weight: 700; letter-spacing: 0.03em; }',
       '  .subtitle { fill: #90e0ef; font-size: 9px; }',
       '  .label { fill: #00b4d8; font-size: 9px; font-weight: 600; }',
       '  .label-sm { fill: #48cae4; font-size: 7px; }',
       '  .dim-value { fill: #f77f00; font-size: 8px; font-weight: 600; }',
       '  .dim-line { stroke: #f77f00; stroke-width: 0.5; stroke-dasharray: 3,2; }',
       '  .dim-ext { stroke: #f77f00; stroke-width: 0.3; }',
       '  .note { fill: #90e0ef; font-size: 7px; }',
       '  .note-warn { fill: #f77f00; font-size: 7px; }',
       '  .geom { fill: none; stroke: #48cae4; stroke-width: 1.2; }',
       '  .geom-fill { fill: #0d1f3c; stroke: #48cae4; stroke-width: 1; }',
       '  .wall { fill: #0d1f3c; stroke: #00b4d8; stroke-width: 1.2; }',
       '  .grid-minor { stroke: #112240; stroke-width: 0.3; }',
       '  .grid-major { stroke: #1a3a5c; stroke-width: 0.5; }',
       '  .hatch { fill: url(#hatch); stroke: #48cae4; stroke-width: 0.5; }',
       '  .bom-text { fill: #caf0f8; font-size: 7px; }',
       '  .bom-hdr { fill: #00b4d8; font-size: 7px; font-weight: 700; }',
       '  .table-header { fill: #0d1f3c; stroke: #00b4d8; stroke-width: 0.5; }',
       '  .table-cell { fill: #0a1628; stroke: #00b4d8; stroke-width: 0.5; }',
       '</style>',
       '<defs>',
       '  <pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">',
       '    <path d="M 20 0 L 0 0 0 20" fill="none" class="grid-minor"/>',
       '  </pattern>',
       '  <pattern id="grid-major" width="100" height="100" patternUnits="userSpaceOnUse">',
       '    <path d="M 100 0 L 0 0 0 100" fill="none" class="grid-major"/>',
       '  </pattern>',
       '  <marker id="arr-org" markerWidth="5" markerHeight="3.5" refX="4" refY="1.75" orient="auto">',
       '    <polygon points="0 0, 5 1.75, 0 3.5" fill="#f77f00"/>',
       '  </marker>',
       '  <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">',
       '    <line x1="0" y1="0" x2="0" y2="6" stroke="#00b4d8" stroke-width="0.2" opacity="0.3"/>',
       '  </pattern>',
       '</defs>',
       f'<rect width="{W}" height="{H}" fill="#0a1628"/>',
       f'<rect width="{W}" height="{H}" fill="url(#grid)"/>',
       f'<rect width="{W}" height="{H}" fill="url(#grid-major)"/>',
       f'<rect x="15" y="15" width="{W-30}" height="{H-30}" fill="none" stroke="#00b4d8" stroke-width="1"/>',
       f'<rect x="18" y="18" width="{W-36}" height="{H-36}" fill="none" stroke="#00b4d8" stroke-width="0.3"/>',
    )

    # Title
    title = config.get("title", "PRODUCTION DRAWING")
    subtitle = config.get("subtitle", "")
    _s(lines,
       f'<text x="{W//2}" y="45" text-anchor="middle" class="title-lg">{title}</text>',
       f'<text x="{W//2}" y="62" text-anchor="middle" fill="#00b4d8" font-size="14">{subtitle}</text>',
    )

    # Info line
    info_parts = [
        f"DWG: {config.get('dwg_no','')}",
        f"Rev: {config.get('revision','')}",
        f"Scale: {config.get('scale','')}",
        f"Date: {config.get('date','')}",
        f"Client: {config.get('client','')}",
    ]
    _s(lines,
       f'<text x="{W//2}" y="78" text-anchor="middle" class="subtitle">{" | ".join(info_parts)}</text>',
    )

    # Drawing views — override in subclass or pass custom SVG content
    if "svg_content" in config:
        for svg_line in config["svg_content"]:
            lines.append(svg_line)

    # BOM table
    bom = config.get("bom", [])
    if bom:
        bx, by = 25, 650
        _s(lines,
           f'<text x="{bx}" y="{by-8}" class="title">BILL OF MATERIALS  材料表</text>',
        )
        hdrs, cols = ["ITEM","QTY","UNIT","DESCRIPTION","SPEC"], [30,40,35,300,250]
        xp = bx
        for hdr, w in zip(hdrs, cols):
            _s(lines,
               f'<rect x="{xp}" y="{by}" width="{w}" height="16" class="table-header"/>',
               f'<text x="{xp+4}" y="{by+11}" class="bom-hdr">{hdr}</text>',
            )
            xp += w
        for ri, row in enumerate(bom):
            ry = by + 16 + ri*14
            xp = bx
            # row is list of [item_no, qty, unit, desc, spec]
            for val, w in zip(row, cols):
                _s(lines,
                   f'<rect x="{xp}" y="{ry}" width="{w}" height="14" class="table-cell"/>',
                   f'<text x="{xp+4}" y="{ry+10}" class="bom-text">{val}</text>',
                )
                xp += w

    # Notes
    notes = config.get("notes", [])
    if notes:
        ny = 580
        _s(lines, f'<text x="25" y="{ny}" class="title">NOTES  備註</text>')
        for i, n in enumerate(notes):
            _s(lines, f'<text x="35" y="{ny+14+i*13}" class="note">{n}</text>')

    # Title block
    tb_x, tb_y, tb_w, tb_h = 700, 730, 460, 85
    _s(lines,
       f'<rect x="{tb_x}" y="{tb_y}" width="{tb_w}" height="{tb_h}" fill="#0d1f3c" stroke="#00b4d8" stroke-width="1"/>',
       f'<line x1="{tb_x}" y1="{tb_y+22}" x2="{tb_x+tb_w}" y2="{tb_y+22}" stroke="#00b4d8" stroke-width="0.5"/>',
       f'<text x="{tb_x+tb_w/2}" y="{tb_y+15}" text-anchor="middle" class="title" font-size="10">{title}</text>',
    )
    for i, (k, v) in enumerate([
        ("DWG NO.", config.get("dwg_no","")),
        ("REV", config.get("revision","v1")),
        ("SCALE", config.get("scale","")),
        ("DATE", config.get("date","")),
        ("CLIENT", config.get("client","")),
        ("PROJECT", config.get("project","")),
    ]):
        col, row = i%2, i//2
        _s(lines,
           f'<text x="{tb_x+20+col*(tb_w//2-10)}" y="{tb_y+36+row*11}" class="label">{k}:</text>',
           f'<text x="{tb_x+100+col*(tb_w//2-10)}" y="{tb_y+36+row*11}" class="bom-text">{v}</text>',
        )

    lines.append('</svg>')
    return '\n'.join(lines)


def save_svg(svg_text, output_path):
    """Validate and save SVG to file."""
    # Basic XML validation
    svg_end = svg_text.rindex('</svg>') + 6
    ET.fromstring(svg_text[:svg_end].encode('utf-8'))
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(svg_text)
    return output_path


if __name__ == "__main__":
    # Demo: simple floor plan
    cfg = {
        "title": "EXHIBITION FLOOR PLAN",
        "subtitle": "展位平面配置圖",
        "dwg_no": "EP-001",
        "revision": "v1",
        "scale": "1:100",
        "date": "2026-06-25",
        "client": "Sample Client",
        "project": "Sample Exhibition",
        "notes": [
            "1. ALL DIMENSIONS IN MILLIMETERS.  所有尺寸單位為公釐。",
            "2. VENUE: 24m × 12m.  場地 24×12m。",
            "3. CEILING HEIGHT: 8m.  挑高 8m。",
            "4. POWER: 3-PHASE 380V / 100A.  三項電源。",
        ],
        "bom": [
            ["1", "1", "set", "Main Structure", "AL6061 Truss 500×500mm"],
            ["2", "2", "set", "Display Case", "1200×600×900mm"],
            ["3", "1", "lot", "Graphics", "Backdrop + Signage"],
        ],
    }
    svg = generate_drawing(cfg)
    out = "/Users/aitree414/telegram-claude-bot/08_AI_Tools/demo_drawing.svg"
    save_svg(svg, out)
    print(f"✓ Drawing saved: {out}")
