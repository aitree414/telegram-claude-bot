"""
08 Collective — Curve Bench Detail Fabrication Drawing
=======================================================
Generates a production detail drawing for the Curve Bench
(05_SW.11) matching 08 Collective's actual detail drawing standard.

Based on reference: G05_1F_3003-05_SW.11 - Curve Bench.pdf

Sheet layout (A3 landscape):
  - Elevation A (1:10) — Front view
  - Plan (1:20) — Top view showing curvature
  - Section A-A (1:5) — Cut through construction
  - Detail B (1:2) — Cushion/joint detail
  - Finish schedule
  - General notes
  - Professional title block
"""

import sys, os, html
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from importlib import import_module
df = import_module("08_AI_Tools.drawing_detail_fab")


def main():
    output_dir = "/Volumes/Apollo Sync Folder/08collective/XCEL/FrenchMay/Layout/Final/Furniture/"
    os.makedirs(output_dir, exist_ok=True)

    # ── Sheet setup ──────────────────────────────────
    sheet = df.DetailSheet(
        title="CURVE BENCH  —  05_SW.11  —  G05 Gallery 5",
        subtitle="Gallery Typical Details  G05  |  展廳典型細部  G05",
        dwg_no="G05_1F_3003",
        revision="v1",
        scale="1:10 / 1:20 / 1:5 / 1:2",
        date="2026.06.25",
        client="Hong Kong Heritage Museum  香港文化博物館",
        project="Meet Mona Lisa — Immersive Experience",
        project_no="8105",
        drawn_by="TREE",
        checked_by="AL",
        approved="",
        project_stage="4.0  Detailed Design  詳細設計",
        drawing_status="For Information  供參考",
        cad_file="Mona Lisa_I_3D_G05_Details.vwx",
        designer_info="08 Collective Ltd.  |  All dimensions in mm  |  Do not scale from drawing",
    )

    # ── Finish references ────────────────────────────
    sheet.add_finish_ref("FI_25", "Cushion fabric  —   cushion fabric 坐墊布料")
    sheet.add_finish_ref("FI_08", "Painted MDF  —   painted MDF 髹漆")
    sheet.add_finish_ref("FI_07", "Painted MDF (alternate)  —   painted MDF 髹漆")

    # ── Revisions ────────────────────────────────────
    sheet.add_revision("v1", "2026.06.25", "Initial issue for fabrication  初版發行")

    # ── Notes ────────────────────────────────────────
    sheet.add_note("1. All dimensions in mm. Verify on site before fabrication.")
    sheet.add_note("2. All MDF to be 18mm FR grade unless noted otherwise.")
    sheet.add_note("3. All surfaces and joints must be neat, cleaned and smoothed.")
    sheet.add_note("4. All corners and edges to be rounded R5 minimum.")
    sheet.add_note("5. Contractor to survey all basebuild interface elements prior to production.")
    sheet.add_note("6. Cushion to be fixed with Velcro tape for removable access.")
    sheet.add_note("7. Timber frame clad in FR MDF. All joints glued and screwed.")
    sheet.add_note("! CONTRACTOR MUST VERIFY ALL DIMENSIONS ON SITE BEFORE FABRICATION.")

    # ── ELEVATION A (1:10) — Front View ──────────────
    # Bench dimensions: 3720w x ~400h (280 seat + 50 cushion + frame)
    s = 0.15  # scale factor for 1:10-ish in viewBox
    bw, bh = 3720, 400
    bw_s, bh_s = bw * s, bh * s

    elev_svg = []

    # Floor line
    elev_svg.append(f'<line x1="-20" y1="{bh_s}" x2="{bw_s+20}" y2="{bh_s}" '
                    f'stroke="{df.STYLE["geom"]}" stroke-width="2"/>')

    # Legs / supports (3 sets)
    leg_positions = [bw_s * 0.08, bw_s * 0.5, bw_s * 0.92]
    leg_w = 8
    for lx in leg_positions:
        elev_svg.append(f'<rect x="{lx-leg_w//2}" y="{bh_s-60*s}" width="{leg_w}" height="{60*s}" '
                        f'class="geom-fill" stroke-width="1.2"/>')

    # Timber frame (seat structure)
    frame_y = bh_s - 60*s - 30*s
    elev_svg.append(df.hatch_rect(0, frame_y, bw_s, 12*s, "hatch-mdf"))
    elev_svg.append(
        f'<rect x="0" y="{frame_y}" width="{bw_s}" height="{12*s}" '
        f'fill="none" stroke="{df.STYLE["geom"]}" stroke-width="1.5"/>'
    )
    mid_frame_y = frame_y + 12*s
    elev_svg.append(
        f'<text x="{bw_s//2}" y="{mid_frame_y+2*s}" text-anchor="middle" font-size="5.5" '
        f'fill="{df.STYLE["geom"]}">12mm MDF  —  FI_08</text>'
    )

    # Cross bracing (hidden lines)
    for lx in leg_positions:
        if lx != leg_positions[-1]:
            next_lx = leg_positions[leg_positions.index(lx) + 1]
            elev_svg.append(
                f'<line x1="{lx}" y1="{bh_s-20*s}" x2="{next_lx}" y2="{bh_s-20*s}" class="hidden"/>'
            )

    # Cushion
    cushion_y = bh_s - 60*s - 30*s - 50*s
    elev_svg.append(
        f'<rect x="{bw_s*0.02}" y="{cushion_y}" width="{bw_s*0.96}" height="{50*s}" '
        f'fill="{df.STYLE["material_fill_fabric"]}" stroke="{df.STYLE["geom"]}" '
        f'stroke-width="1.2" rx="3"/>'
    )
    elev_svg.append(
        f'<text x="{bw_s//2}" y="{cushion_y+25*s+1}" text-anchor="middle" font-size="6" '
        f'fill="{df.STYLE["geom"]}">Cushion  —  FI_25</text>'
    )

    # Dimensions
    elev_svg.extend(df.dim_horizontal(bh_s+5, 0, bw_s, "3720", offset=10))
    elev_svg.extend(df.dim_vertical(-10, cushion_y, bh_s, "350", offset=10))
    elev_svg.extend(df.dim_vertical(-10, cushion_y, cushion_y+50*s, "50", offset=22))

    # Finish callouts
    elev_svg.append(df.finish_callout(10, cushion_y-5, "Cushion fabric", "FI_25"))
    elev_svg.append(df.material_label(10, bh_s-5, "MDF frame", "12mm"))

    # Section cut
    cx = bw_s // 2
    elev_svg.append(df.section_cut(cx, cushion_y, cx, bh_s, "A"))

    # Detail marker
    elev_svg.append(df.detail_marker(bw_s, 0, "B"))

    sheet.add_view(df.FabView(
        label="Elevation A", view_type=df.ELEVATION,
        x=40, y=60, width=580, height=bh_s+30, scale="1:10",
        svg_content=elev_svg,
    ))

    # ── PLAN (1:20) — Top View Showing Curve ─────────
    plan_svg = []
    ps = 0.12
    inner_r, outer_r = 2466.6 * ps, 2966.6 * ps
    arc_angle = 85  # degrees (approximate)
    import math
    arc_sweep = math.radians(arc_angle)

    # Draw curved bench as two arcs
    cx_plan, cy_plan = 80, 300  # center of arcs
    # Inner arc
    inner_path = (
        f'M {cx_plan+inner_r} {cy_plan} '
        f'A {inner_r} {inner_r} 0 0 1 '
        f'{cx_plan+inner_r*math.cos(arc_sweep)} {cy_plan-inner_r*math.sin(arc_sweep)}'
    )
    # Outer arc
    outer_path = (
        f'M {cx_plan+outer_r} {cy_plan} '
        f'A {outer_r} {outer_r} 0 0 1 '
        f'{cx_plan+outer_r*math.cos(arc_sweep)} {cy_plan-outer_r*math.sin(arc_sweep)}'
    )

    plan_svg.append(
        f'<path d="{inner_path}" fill="none" stroke="{df.STYLE["geom"]}" stroke-width="1.5"/>'
    )
    plan_svg.append(
        f'<path d="{outer_path}" fill="none" stroke="{df.STYLE["geom"]}" stroke-width="1.5"/>'
    )
    # End caps
    end1 = (
        f'M {cx_plan+inner_r} {cy_plan} '
        f'L {cx_plan+outer_r} {cy_plan}'
    )
    end2 = (
        f'M {cx_plan+inner_r*math.cos(arc_sweep)} {cy_plan-inner_r*math.sin(arc_sweep)} '
        f'L {cx_plan+outer_r*math.cos(arc_sweep)} {cy_plan-outer_r*math.sin(arc_sweep)}'
    )
    plan_svg.append(f'<path d="{end1}" stroke="{df.STYLE["geom"]}" stroke-width="1.5"/>')
    plan_svg.append(f'<path d="{end2}" stroke="{df.STYLE["geom"]}" stroke-width="1.5"/>')

    # Seat division lines (4 seats)
    for i in range(1, 4):
        angle = arc_sweep * i / 4
        sx = cx_plan + inner_r * math.cos(angle)
        sy = cy_plan - inner_r * math.sin(angle)
        ex = cx_plan + outer_r * math.cos(angle)
        ey = cy_plan - outer_r * math.sin(angle)
        plan_svg.append(
            f'<line x1="{sx}" y1="{sy}" x2="{ex}" y2="{ey}" '
            f'class="hidden"/>'
        )

    # Center line
    mid_r = (inner_r + outer_r) / 2
    plan_svg.append(f'<line x1="{cx_plan}" y1="{cy_plan}" x2="{cx_plan+mid_r*math.cos(arc_sweep/2)}" '
                    f'y2="{cy_plan-mid_r*math.sin(arc_sweep/2)}" class="center"/>')

    # Dimensions
    plan_svg.append(
        f'<text x="{cx_plan+mid_r*math.cos(arc_sweep/2)}" y="{cy_plan-20}" '
        f'text-anchor="middle" class="dim-text">ARC LENGTH 3720</text>'
    )
    plan_svg.append(
        f'<text x="{cx_plan+outer_r+15}" y="{cy_plan-10}" class="dim-text">'
        f'R{outer_r/ps:.0f}</text>'
    )

    # Finish callout
    plan_svg.append(df.finish_callout(cx_plan+10, cy_plan+15, "Painted MDF bench top", "FI_08"))

    sheet.add_view(df.FabView(
        label="Plan", view_type=df.PLAN,
        x=40, y=300, width=600, height=200, scale="1:20",
        svg_content=plan_svg,
    ))

    # ── SECTION A-A (1:5) — Vertical Cut ─────────────
    sec_svg = []
    sec_s = 0.6
    bench_depth = 500  # mm (approx depth of curved bench)
    bd_s = bench_depth * sec_s

    # Floor
    sec_svg.append(f'<line x1="0" y1="{200}" x2="{bd_s}" y2="{200}" '
                   f'stroke="{df.STYLE["geom"]}" stroke-width="2"/>')

    # Timber frame
    frame_base = 200 - 30*sec_s
    sec_svg.append(df.material_section(0, frame_base-12*sec_s, bd_s, 12*sec_s,
                                        "12mm MDF  FI_08", "hatch-mdf"))

    # Frame support
    sec_svg.append(df.material_section(bd_s//2-30*sec_s, frame_base, 60*sec_s, 30*sec_s,
                                        "18mm MDF", "hatch-mdf"))

    # Cushion
    cushion_bottom = frame_base - 12*sec_s - 50*sec_s
    sec_svg.append(
        f'<rect x="10" y="{cushion_bottom}" width="{bd_s-20}" height="{50*sec_s}" '
        f'fill="{df.STYLE["material_fill_fabric"]}" stroke="{df.STYLE["geom"]}" '
        f'stroke-width="1.2" rx="2"/>'
    )
    sec_svg.append(
        f'<text x="{bd_s//2}" y="{cushion_bottom+25*sec_s+1}" text-anchor="middle" '
        f'font-size="6" fill="{df.STYLE["geom"]}">Cushion  FI_25</text>'
    )

    # Dimensions
    sec_svg.extend(df.dim_horizontal(200+10, 0, bd_s, "500", offset=10))
    sec_svg.extend(df.dim_vertical(-10, cushion_bottom, 200, "350", offset=10))
    sec_svg.extend(df.dim_vertical(-10, cushion_bottom, cushion_bottom+50*sec_s, "50", offset=22))

    # Callouts
    sec_svg.append(df.material_label(bd_s+10, frame_base-5, "MDF seat panel", "12mm"))
    sec_svg.append(df.leader_line(bd_s, frame_base-6*sec_s, bd_s+10, frame_base-5))
    sec_svg.append(df.material_label(bd_s+10, frame_base+10, "MDF support frame", "18mm"))
    sec_svg.append(df.leader_line(bd_s, frame_base+15*sec_s, bd_s+10, frame_base+10))
    sec_svg.append(df.finish_callout(10, cushion_bottom-8, "Cushion fabric", "FI_25"))

    sheet.add_view(df.FabView(
        label="Section A-A", view_type=df.SECTION,
        x=660, y=60, width=450, height=210, scale="1:5",
        svg_content=sec_svg,
    ))

    # ── DETAIL B (1:2) — Cushion Fixing Detail ───────
    det_svg = []
    ds = 2.0

    # Top of bench frame
    det_svg.append(f'<rect x="0" y="{30}" width="{120*ds}" height="{12*ds}" '
                   f'class="hatch-mdf" stroke="{df.STYLE["geom"]}" stroke-width="1.2"/>')
    det_svg.append(
        f'<text x="{60*ds}" y="{30+6*ds+1}" text-anchor="middle" font-size="6" '
        f'fill="{df.STYLE["geom"]}">12mm MDF bench top  FI_08</text>'
    )

    # Velcro tape
    velcro_y = 30 - 4
    det_svg.append(
        f'<rect x="{30*ds}" y="{velcro_y}" width="{10}" height="4" '
        f'fill="#888" stroke="#333" stroke-width="0.5"/>'
    )
    det_svg.append(
        f'<text x="{30*ds+15}" y="{velcro_y+3}" font-size="5.5" '
        f'fill="{df.STYLE["geom"]}">Velcro tape</text>'
    )

    # Cushion base
    cushion_y = velcro_y - 50*ds
    det_svg.append(
        f'<rect x="{10*ds}" y="{cushion_y}" width="{100*ds}" height="{50*ds}" '
        f'fill="{df.STYLE["material_fill_fabric"]}" stroke="{df.STYLE["geom"]}" '
        f'stroke-width="1.2" rx="3"/>'
    )
    # Fabric texture lines
    for i in range(3):
        fy = cushion_y + 10 + i*15
        det_svg.append(
            f'<line x1="{15*ds}" y1="{fy}" x2="{105*ds}" y2="{fy}" '
            f'stroke="{df.STYLE["hidden"]}" stroke-width="0.4" stroke-dasharray="1,4"/>'
        )

    # Labels
    det_svg.append(
        f'<text x="{60*ds}" y="{cushion_y+25*ds+1}" text-anchor="middle" font-size="6" '
        f'fill="{df.STYLE["geom"]}">Cushion  FI_25</text>'
    )
    det_svg.append(
        f'<text x="0" y="{cushion_y-5}" font-size="6" class="callout-fi">'
        f'Cushion — FI_25  |  Velcro removable</text>'
    )

    # Corner roundover
    det_svg.append(
        f'<path d="M0,{30+12*ds} A{5*ds},{5*ds} 0 0,0 {5*ds},{30+12*ds-5*ds}" '
        f'fill="none" stroke="{df.STYLE["note"]}" stroke-width="0.8"/>'
    )
    det_svg.append(
        f'<text x="{8*ds}" y="{30+12*ds-5*ds-2}" font-size="5.5" '
        f'fill="{df.STYLE["note"]}">R5 round</text>'
    )

    # Dimension
    det_svg.extend(df.dim_vertical(-8, cushion_y, 30, "50", offset=10))

    sheet.add_view(df.FabView(
        label="Detail B", view_type=df.DETAIL,
        x=660, y=290, width=300, height=200, scale="1:2",
        svg_content=det_svg,
    ))

    # ── BOM ──────────────────────────────────────────
    sheet.add_bom_item(1, "1", "LOT", "Bench timber frame clad in FR MDF", "18mm MDF — FI_08")
    sheet.add_bom_item(2, "1", "LOT", "Bench seat panel", "12mm MDF — FI_08")
    sheet.add_bom_item(3, "1", "LOT", "Cushion set (4 seats)", "FI_25 fabric")
    sheet.add_bom_item(4, "4", "M", "Velcro tape (hook & loop)", "25mm wide")
    sheet.add_bom_item(5, "1", "LOT", "Primer & paint system", "FI_08 — matt finish")
    sheet.add_bom_item(6, "1", "LOT", "Metal leg brackets", "Custom fabricated")

    # ── Generate ─────────────────────────────────────
    output_path = os.path.join(output_dir, "G05_1F_3003-05_SW.11-CURVE BENCH_v2.svg")
    sheet.save(output_path)
    print(f"Bench detail drawing: {output_path}")

    html_path = output_path.replace(".svg", ".html")
    _write_html_wrapper(sheet, html_path)
    print(f"HTML view: {html_path}")


def _write_html_wrapper(sheet, html_path):
    svg = sheet.generate()
    title = html.escape(sheet.title, quote=False)
    h = f"""<!DOCTYPE html>
<html lang="zh-HK">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: #666; display: flex; flex-direction: column; align-items: center; padding: 20px; }}
  .sheet {{ background: #fff; box-shadow: 0 2px 20px rgba(0,0,0,0.3); margin-bottom: 20px; }}
  svg {{ display: block; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .sheet {{ box-shadow: none; margin: 0; }}
    @page {{ margin: 0; size: A3 landscape; }}
  }}
</style>
</head>
<body>
<div class="sheet">
{svg}
</div>
</body>
</html>"""
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(h)


if __name__ == "__main__":
    main()
