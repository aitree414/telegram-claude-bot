"""
香港文聯 — Exhibition Fabrication Drawings Generator
=====================================================
Reads extracted SketchUp JSON data and generates DXF
fabrication drawings for all exhibition items.

Item categories:
  1. huodongban (movable panels) — 3 sizes
  2. zhanban (display boards)
  3. 灰色展板 (gray display boards)
  4. Obj3d66 display cases — 6 unique sizes
  5. 材料11 material panels
  6. Other exhibition furniture
"""

import json, os, sys, math
from importlib import import_module

df = import_module("08_AI_Tools.dxf_detail_fab")

OUTPUT_DIR = "/Volumes/Apollo Sync Folder/08collective/香港文聯/施工圖/"
os.makedirs(OUTPUT_DIR, exist_ok=True)

DATA_PATH = "/tmp/sketchup_items.json"


def load_data():
    with open(DATA_PATH) as f:
        return json.load(f)


def get_unique_items(data):
    """Group items by definition/type to get unique fabrication items."""
    items = data["items"]

    groups = {}
    for item in items:
        w, d, h = item["mm"]
        # Skip items with 0 in 2 dimensions (points) or all 0
        zero_dims = sum(1 for v in [w, d, h] if v == 0)
        if zero_dims >= 2:
            continue
        # Skip very large items (> 10m) — these are building structure
        if max(w, d, h) > 10000:
            continue
        # Skip items smaller than 100mm — likely details/fasteners
        if max(w, d, h) < 100:
            continue

        # Build key from definition + size
        defn = item.get("definition", "") or "unknown"
        key = f"{defn}_{w}x{d}x{h}"
        if key not in groups:
            groups[key] = {
                "definition": defn,
                "name": item["name"],
                "mm": item["mm"],
                "count": 0,
            }
        groups[key]["count"] += 1

    return sorted(groups.values(), key=lambda g: -g["count"])


def categorize(groups):
    """Categorize unique items."""
    cats = {
        "huodongban": [], "zhanban": [], "gray_ban": [],
        "obj3d66": [], "material11": [], "other": [],
    }
    for g in groups:
        defn = g["definition"]
        name = g["name"]
        if "huodongban" in defn or "活动板" in defn:
            cats["huodongban"].append(g)
        elif "zhanban" in defn or "展板" in defn or "灰色" in defn or "gray" in defn:
            cats["gray_ban" if "灰色" in defn else "zhanban"].append(g)
        elif "obj3d66" in name.lower() or name.startswith("Obj3d66"):
            cats["obj3d66"].append(g)
        elif "材料11" in defn or g.get("material", "") == "材料11":
            cats["material11"].append(g)
        else:
            cats["other"].append(g)
    return cats


# ─── DRAWING GENERATORS ─────────────────────────────────

def draw_huodongban(sheet, ox, oy, w, d, h, label):
    """Draw movable panel: elevation + side + section."""
    # Elevation (front view)
    elev_y = oy + 120
    sheet.rect(ox, elev_y, w, h, layer="A-FURN-OUTL")

    # Panel frame indication (hidden lines for structure)
    margin = 30
    sheet.line(ox + margin, elev_y + margin,
               ox + w - margin, elev_y + margin,
               layer="A-FURN-HIDD")
    sheet.line(ox + margin, elev_y + h - margin,
               ox + w - margin, elev_y + h - margin,
               layer="A-FURN-HIDD")

    # Cross bracing indication
    cx, cy = ox + w // 2, elev_y + h // 2

    # Label
    sheet.text(cx, elev_y + h + 10, label, layer="A-ANNO-TEXT", size=3, align="center")
    sheet.text(cx, elev_y + h + 5, f"(x{g.get('count', 1)})" if 'count' in locals() else "",
               layer="A-ANNO-TEXT", size=2, align="center")

    # Overall dimension
    sheet.dim_horizontal(elev_y, ox, ox + w, str(w))
    sheet.dim_horizontal(elev_y - 12, ox + margin, ox + w - margin,
                         f"frame {w - 2*margin}", layer="A-DIMS")
    sheet.dim_vertical(ox - 10, elev_y, elev_y + h, str(h))

    # Side view
    side_x = ox + w + 60
    sheet.rect(side_x, elev_y, d, h, layer="A-FURN-OUTL")
    sheet.dim_horizontal(elev_y, side_x, side_x + d, str(d))
    sheet.text(side_x + d // 2, elev_y - 15, "SIDE 侧视",
               layer="A-ANNO-TEXT", size=2.5, align="center")

    # Section
    sec_x = ox
    sec_y = elev_y - 80
    sheet.text(ox + w // 2, sec_y + 30, "SECTION A-A 剖面",
               layer="A-ANNO-TEXT", size=2.5, align="center")

    sheet.line(ox, sec_y, ox, sec_y + 18, layer="A-FURN-OUTL")
    sheet.line(ox + w, sec_y, ox + w, sec_y + 18, layer="A-FURN-OUTL")

    # Frame section
    sheet.rect(ox, sec_y, w, 6, layer="A-FURN-OUTL")
    sheet.hatch_solid(ox, sec_y, w, 6, pattern="ANSI31", scale=0.5)

    # Panel section
    panel_thick = 12
    sheet.rect(ox + margin, sec_y + 6, w - 2 * margin, panel_thick,
               layer="A-FURN-OUTL")
    sheet.hatch_solid(ox + margin, sec_y + 6, w - 2 * margin, panel_thick,
                      pattern="ANSI31", scale=0.5)

    sheet.dim_vertical(ox + w + 10, sec_y, sec_y + 6 + panel_thick, "18+12mm")


def draw_zhanban(sheet, ox, oy, w, d, h, label):
    """Draw display board (thin panel)."""
    # Elevation
    sheet.rect(ox, oy + 60, w, h, layer="A-FURN-OUTL")

    # Content area
    margin = 20
    sheet.rect(ox + margin, oy + 60 + margin, w - 2 * margin, h - 2 * margin,
               layer="A-FURN-HIDD")

    sheet.text(ox + w // 2, oy + 60 + h + 10, label,
               layer="A-ANNO-TEXT", size=3, align="center")

    sheet.dim_horizontal(oy + 60, ox, ox + w, str(w))
    sheet.dim_vertical(ox - 10, oy + 60, oy + 60 + h, str(h))

    # Side view showing thickness
    sx = ox + w + 50
    sheet.rect(sx, oy + 60, d or 50, h, layer="A-FURN-OUTL")
    sheet.dim_horizontal(oy + 60, sx, sx + (d or 50), str(d or 50))
    sheet.text(sx + (d or 50) // 2, oy + 55, "SIDE 侧视",
               layer="A-ANNO-TEXT", size=2.5, align="center")


def draw_obj3d66(sheet, ox, oy, w, d, h, label):
    """Draw display case: front, side, plan views + section."""
    label_text = label or "Display Case 陈列柜"
    scale = min(1.0, 300 / max(w, h, 1))

    # Front elevation
    ew, eh = w * scale, h * scale
    sheet.rect(ox, oy, ew, eh, layer="A-FURN-OUTL")

    # Glass panel (display window)
    glass_m = 40 * scale
    sheet.rect(ox + glass_m, oy + glass_m, ew - 2 * glass_m, eh * 0.65,
               layer="A-FURN-HIDD")

    # Base
    base_h = 60 * scale
    sheet.rect(ox, oy, ew, base_h, layer="A-FURN-OUTL")
    sheet.hatch_solid(ox, oy, ew, base_h, pattern="ANSI31", scale=1.0)

    # Shelf line
    shelf_y = oy + eh * 0.7
    sheet.line(ox + glass_m, shelf_y, ox + ew - glass_m, shelf_y,
               layer="A-FURN-CNTR")

    sheet.text(ox + ew // 2, oy + eh + 5, label_text,
               layer="A-ANNO-TEXT", size=2.5, align="center")
    sheet.text(ox + ew // 2, oy + eh - 10, f"GLASS 玻璃",
               layer="A-ANNO-TEXT", size=2, align="center")
    sheet.text(ox + ew // 2, oy + base_h // 2 - 1, "MDF BASE 底座",
               layer="A-ANNO-TEXT", size=2, align="center")

    sheet.dim_horizontal(oy, ox, ox + ew, str(w))
    sheet.dim_vertical(ox - 10, oy, oy + eh, str(h))

    # Section A-A
    sec_x = ox + ew + 50
    sec_w = d * scale
    sheet.rect(sec_x, oy, sec_w, eh, layer="A-FURN-OUTL")

    # Glass in section
    glass_thick = 8 * scale
    sheet.rect(sec_x + 5 * scale, oy + glass_m, sec_w - 10 * scale, eh * 0.65,
               layer="A-FURN-HIDD")

    # Base in section
    sheet.rect(sec_x, oy, sec_w, base_h, layer="A-FURN-OUTL")
    sheet.hatch_solid(sec_x, oy, sec_w, base_h, pattern="ANSI31", scale=1.0)

    sheet.text(sec_x + sec_w // 2, oy - 10, "SECTION A-A 剖面",
               layer="A-ANNO-TEXT", size=2.5, align="center")
    sheet.text(sec_x + sec_w // 2, oy + base_h // 2 - 1, "BASE",
               layer="A-ANNO-TEXT", size=2, align="center")

    sheet.dim_horizontal(oy, sec_x, sec_x + sec_w, str(d))

    # Plan view (top)
    plan_x = ox
    plan_y = oy + eh + 50
    plan_w = w * scale * 0.8
    plan_d = d * scale * 0.8

    sheet.rect(plan_x, plan_y, plan_w, plan_d, layer="A-FURN-OUTL")
    sheet.text(plan_x + plan_w // 2, plan_y - 10, "PLAN 俯视",
               layer="A-ANNO-TEXT", size=2.5, align="center")
    sheet.dim_horizontal(plan_y + plan_d + 3, plan_x, plan_x + plan_w, str(w))
    sheet.dim_vertical(plan_x - 10, plan_y, plan_y + plan_d, str(d))


def draw_material11(sheet, ox, oy, w, d, h, label):
    """Draw material panel."""
    scale = min(1.0, 400 / max(w, h, 1))
    ew, eh = w * scale, h * scale

    # Front elevation
    sheet.rect(ox, oy, ew, eh, layer="A-FURN-OUTL")

    # Material pattern indication
    for ry in range(0, int(eh), int(100 * scale)):
        sheet.line(ox, oy + ry, ox + ew, oy + ry, layer="A-FURN-HIDD")

    sheet.text(ox + ew // 2, oy + eh // 2, f"MATERIAL PANEL\n{label}",
               layer="A-ANNO-TEXT", size=3, align="center")

    sheet.dim_horizontal(oy, ox, ox + ew, str(w))
    sheet.dim_vertical(ox - 10, oy, oy + eh, str(h))

    # Side view
    sx = ox + ew + 40
    sd = d * scale
    sheet.rect(sx, oy, sd, eh, layer="A-FURN-OUTL")
    sheet.dim_horizontal(oy, sx, sx + sd, str(d))
    sheet.text(sx + sd // 2, oy - 10, "SIDE 侧视",
               layer="A-ANNO-TEXT", size=2.5, align="center")

    # Note
    sheet.text(ox + ew // 2, oy - 20, "Finish: 材料11 (see finish schedule)",
               layer="A-ANNO-CALLOUT", size=2.5, align="center")


def draw_other_item(sheet, ox, oy, w, d, h, label, defn=""):
    """Generic item drawing."""
    scale = min(1.0, 300 / max(w, h, d, 1))

    # Front
    ew, eh = max(w, d) * scale, h * scale
    sheet.rect(ox, oy, ew, eh, layer="A-FURN-OUTL")

    center_label = defn if defn else (label or "ITEM")
    sheet.text(ox + ew // 2, oy + eh // 2, center_label,
               layer="A-ANNO-TEXT", size=2.5, align="center")

    sheet.dim_horizontal(oy, ox, ox + ew, str(round(max(w, d))))
    sheet.dim_vertical(ox - 10, oy, oy + eh, str(h))

    # Side
    sx = ox + ew + 40
    sd = min(w, d) * scale
    sheet.rect(sx, oy, sd, eh, layer="A-FURN-OUTL")
    sheet.dim_horizontal(oy, sx, sx + sd, str(round(min(w, d))))


# ─── MAIN ────────────────────────────────────────────────

def generate_all():
    data = load_data()
    groups = get_unique_items(data)
    cats = categorize(groups)

    print(f"Data loaded: {data['count']} items, {len(groups)} unique groups")
    for cat_name, cat_items in cats.items():
        print(f"  {cat_name}: {len(cat_items)} unique types")

    generated = []

    # 1. Huodongban (movable panels)
    if cats["huodongban"]:
        sheet = df.DXFDetailSheet(
            title="MOVABLE PARTITION PANELS 活动板",
            subtitle=f"香港文聯 Exhibition — {data['model']}",
            dwg_no="HKF_001",
            scale="1:10",
            date="2026.06.27",
            client="Hong Kong Federation 香港文聯",
            project="Echoes of the Sui & Tang",
            project_no="HKF-2026",
            drawn_by="TREE",
        )
        y = 250
        for i, g in enumerate(cats["huodongban"]):
            w, d_, h = g["mm"]
            label = f"HUODONGBAN 活动板 {i+1} ({g['count']}x)"
            draw_huodongban(sheet, 30, y - 180, w, d_, h, label)
            y -= 180

        path = os.path.join(OUTPUT_DIR, "HKF_001_huodongban.dxf")
        sheet.save(path)
        generated.append(("huodongban", path))

    # 2. Zhanban (display boards)
    for cat_key, prefix, dwg_no in [
        ("zhanban", "ZHANBAN", "HKF_002"),
        ("gray_ban", "GRAY_BAN", "HKF_003"),
    ]:
        if cats[cat_key]:
            sheet = df.DXFDetailSheet(
                title=f"DISPLAY BOARDS 展板 — {prefix}",
                subtitle=f"香港文聯 Exhibition",
                dwg_no=dwg_no,
                scale="1:10",
                date="2026.06.27",
                client="Hong Kong Federation",
                project="Echoes of the Sui & Tang",
                drawn_by="TREE",
            )
            y = 200
            for g in cats[cat_key]:
                w, d_, h = g["mm"]
                label = f"{g['definition'] or prefix} ({g['count']}x)"
                draw_zhanban(sheet, 30, y, w, max(d_, 50), h, label)
                y -= 120

            path = os.path.join(OUTPUT_DIR, f"{dwg_no}_{prefix.lower()}.dxf")
            sheet.save(path)
            generated.append((prefix, path))

    # 3. Obj3d66 display cases
    for i, g in enumerate(cats.get("obj3d66", [])):
        w, d_, h = g["mm"]
        sheet = df.DXFDetailSheet(
            title=f"DISPLAY CASE 陈列柜 Type-{i+1}",
            subtitle=f"{w} x {d_} x {h}mm  ({g['count']}x)",
            dwg_no=f"HKF_004_{i+1:02d}",
            scale="1:10",
            date="2026.06.27",
            client="Hong Kong Federation",
            project="Echoes of the Sui & Tang",
            drawn_by="TREE",
        )
        draw_obj3d66(sheet, 30, 30, w, d_, h, f"Type {i+1}")
        path = os.path.join(OUTPUT_DIR, f"HKF_004_Obj3d66_Type{i+1:02d}.dxf")
        sheet.save(path)
        generated.append((f"Obj3d66-T{i+1}", path))

    # 4. Material 11 panels
    if cats.get("material11"):
        sheet = df.DXFDetailSheet(
            title="MATERIAL PANELS 材料11",
            subtitle="Finish material specification",
            dwg_no="HKF_005",
            scale="1:20",
            date="2026.06.27",
            client="Hong Kong Federation",
            project="Echoes of the Sui & Tang",
            drawn_by="TREE",
        )
        y = 200
        for g in cats["material11"]:
            w, d_, h = g["mm"]
            draw_material11(sheet, 30, y, w, d_, h, "材料11 Panel")
            y -= 150

        path = os.path.join(OUTPUT_DIR, "HKF_005_material11.dxf")
        sheet.save(path)
        generated.append(("material11", path))

    # 5. Other items (filter non-building)
    if cats.get("other"):
        sheet = df.DXFDetailSheet(
            title="MISCELLANEOUS EXHIBITION ITEMS",
            subtitle="Other exhibition furniture",
            dwg_no="HKF_006",
            scale="1:20",
            date="2026.06.27",
            client="Hong Kong Federation",
            project="Echoes of the Sui & Tang",
            drawn_by="TREE",
        )
        y = 200
        drawn = 0
        for g in cats["other"][:8]:  # Limit to 8
            w, d_, h = g["mm"]
            # Skip if too large (>5m — likely structural)
            if max(w, d_, h) > 5000:
                continue
            draw_other_item(sheet, 30, y, w, d_, h, g["name"], g["definition"])
            y -= 100
            drawn += 1

        if drawn > 0:
            path = os.path.join(OUTPUT_DIR, "HKF_006_misc.dxf")
            sheet.save(path)
            generated.append(("misc", path))

    return generated


if __name__ == "__main__":
    generated = generate_all()
    print(f"\n{'='*60}")
    print(f"  Generated {len(generated)} DXF files")
    print(f"{'='*60}")
    for name, path in generated:
        size = os.path.getsize(path)
        print(f"  {name:20s}  {os.path.basename(path):40s}  {size/1024:.0f} KB")
    print(f"\nOutput directory: {OUTPUT_DIR}")
