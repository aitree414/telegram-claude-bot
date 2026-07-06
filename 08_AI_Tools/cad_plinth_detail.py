"""
08 Collective — Plinth Detail Fabrication Drawing
==================================================
Generates a production detail drawing for the Prelude Plinth
(00_SW.02) matching 08 Collective's actual detail drawing standard.

Based on reference: G0304_1F_3000-00_SW.02-PLINTH DETAILS.pdf

Sheet layout (A3 landscape):
  - Elevation A (1:10) — Front view with compartment dimensions
  - Plan (1:10) — Top view
  - Section A-A (1:5) — Vertical cut through plinth construction
  - Detail B (1:2) — Corner joint detail
  - Finish schedule (FI_xx references)
  - General notes
  - Professional title block with revision history
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
        title="PLINTH DETAILS  —  00_SW.02  —  PRELUDE PLINTH",
        subtitle="Typical detail  G03&04  |  典型細部  G03&04 區",
        dwg_no="G0304_1F_3000",
        revision="v1",
        scale="1:10 / 1:5 / 1:2",
        date="2026.06.25",
        client="Hong Kong Heritage Museum  香港文化博物館",
        project="Meet Mona Lisa  |  一見鍾情",
        project_no="8105",
        drawn_by="TREE",
        checked_by="AL",
        approved="",
        project_stage="4.0  Scheme Design  方案設計",
        drawing_status="For Information  供參考",
        cad_file="Mona Lisa_I_3D_G03&04_Details.vwx",
        designer_info="08 Collective Ltd.  |  All dimensions in mm  |  Do not scale from drawing",
    )

    # ── Finish references ────────────────────────────
    sheet.add_finish_ref("FI_07", "Painted MDF plinth  - painted MDF 髹漆")
    sheet.add_finish_ref("FI_19", "Paper labels  - paper label 紙標籤")
    sheet.add_finish_ref("FI_08", "Painted MDF (alternate)  - painted MDF 髹漆")

    # ── Revisions ────────────────────────────────────
    sheet.add_revision("v1", "2026.06.25", "Initial issue for fabrication  初版發行")

    # ── Notes ────────────────────────────────────────
    sheet.add_note("1. All dimensions in mm. Verify on site before fabrication.")
    sheet.add_note("2. All MDF to be 18mm FR grade unless noted otherwise.")
    sheet.add_note("3. All surfaces and joints must be neat, cleaned and smoothed.")
    sheet.add_note("4. All corners and edges to be rounded R5 minimum.")
    sheet.add_note("5. Contractor to survey all basebuild interface elements prior to production.")
    sheet.add_note("6. All cabling to be fed through structure and connected to floor supply.")
    sheet.add_note("7. Fixings: M4 screws @ 300 c/c through face panel into frame.")
    sheet.add_note("! CONTRACTOR MUST VERIFY ALL DIMENSIONS ON SITE BEFORE FABRICATION.")

    # ── ELEVATION A (1:10) — Front View ──────────────
    compartments = [
        (550, "", "FI_19"),
        (760, "", "FI_07"),
        (430, "", ""),
        (640, "", ""),
        (60, "", ""),
    ]

    elev_svg = df.generate_plinth_elevation(880, 120, compartments, scale_factor=0.6)
    elev_svg.extend(df.dim_horizontal(135, 0, 528, "880", offset=18))
    elev_svg.append(df.section_cut(264, 0, 264, 72, "A"))
    elev_svg.append(df.detail_marker(528, 72, "B"))

    sheet.add_view(df.FabView(
        label="Elevation A", view_type=df.ELEVATION,
        x=40, y=60, width=530, height=140, scale="1:10",
        svg_content=elev_svg,
    ))

    # ── PLAN (1:10) — Top View ───────────────────────
    plan_svg = []
    pw, pd = 880, 430
    ps = 0.25  # plan scale factor (smaller to fit)
    pw_s, pd_s = pw * ps, pd * ps

    plan_svg.append(f'<rect x="0" y="0" width="{pw_s}" height="{pd_s}" '
                    f'class="geom-fill" stroke-width="1.5"/>')
    plan_svg.append(f'<line x1="{120*ps}" y1="0" x2="{120*ps}" y2="{pd_s}" class="hidden"/>')
    plan_svg.append(f'<line x1="{pw_s-60*ps}" y1="0" x2="{pw_s-60*ps}" y2="{pd_s}" class="hidden"/>')
    plan_svg.append(f'<line x1="0" y1="{pd_s/2}" x2="{pw_s}" y2="{pd_s/2}" class="center"/>')
    plan_svg.append(f'<line x1="{pw_s/2}" y1="0" x2="{pw_s/2}" y2="{pd_s}" class="center"/>')
    plan_svg.extend(df.dim_horizontal(-5, 0, pw_s, "880", offset=8))
    plan_svg.extend(df.dim_vertical(pw_s+5, 0, pd_s, "430", offset=8))
    plan_svg.append(df.finish_callout(10, pd_s+15, "Painted MDF plinth", "FI_07"))

    sheet.add_view(df.FabView(
        label="Plan", view_type=df.PLAN,
        x=40, y=220, width=530, height=pd_s+30, scale="1:10",
        svg_content=plan_svg,
    ))

    # ── SECTION A-A (1:5) — Vertical Cut ─────────────
    layers = [
        (12, "12mm MDF face  FI_07", "hatch-mdf"),
        (18, "18mm MDF frame", "hatch-cross"),
        (60, "Void  (cabling)", ""),
        (18, "18mm MDF base", "hatch-mdf"),
        (12, "12mm MDF bottom", "hatch-mdf"),
    ]

    sec_svg = df.generate_plinth_section(430, 120, layers, scale_factor=1.2)
    sec_svg.insert(0, f'<text x="0" y="-10" font-size="7" font-weight="700" '
                      f'fill="{df.STYLE["section"]}">SECTION A-A</text>')
    sec_svg.append(df.material_label(540, 15, "MDF face panel", "12mm"))
    sec_svg.append(df.leader_line(516, 7, 540, 15))
    sec_svg.append(df.material_label(540, 37, "MDF frame", "18mm"))
    sec_svg.append(df.leader_line(516, 22, 540, 37))
    sec_svg.append(df.material_label(540, 90, "MDF base panel", "18mm"))
    sec_svg.append(df.leader_line(516, 85, 540, 90))
    sec_svg.append(df.finish_callout(10, 130, "Painted finish", "FI_07"))

    sheet.add_view(df.FabView(
        label="Section A-A", view_type=df.SECTION,
        x=600, y=60, width=550, height=140, scale="1:5",
        svg_content=sec_svg,
    ))

    # ── DETAIL B (1:2) — Corner Joint ────────────────
    detail_svg = df.generate_plinth_corner_detail(scale_factor=2.5)
    detail_svg.insert(0, f'<text x="0" y="-10" font-size="7" font-weight="700" '
                         f'fill="{df.STYLE["section"]}">DETAIL B  —  Corner Joint 角落接合</text>')
    detail_svg.append(df.material_label(5, 160, "MDF face panel", "12mm"))
    detail_svg.append(df.material_label(5, 175, "MDF frame", "18mm"))
    detail_svg.append(df.finish_callout(5, 190, "Painted finish to all exposed surfaces", "FI_07"))

    sheet.add_view(df.FabView(
        label="Detail B", view_type=df.DETAIL,
        x=600, y=220, width=350, height=200, scale="1:2",
        svg_content=detail_svg,
    ))

    # ── BOM ──────────────────────────────────────────
    sheet.add_bom_item(1, "1", "LOT", "Plinth structure MDF frame", "18mm FR MDF")
    sheet.add_bom_item(2, "1", "LOT", "Plinth face panels", "12mm MDF - FI_07")
    sheet.add_bom_item(3, "1", "LOT", "Paper label inserts", "FI_19")
    sheet.add_bom_item(4, "30", "PCS", "Screw M4 x 25mm SS", "M4 @300 c/c")
    sheet.add_bom_item(5, "1", "LOT", "Primer & paint system", "FI_07 matt finish")
    sheet.add_bom_item(6, "1", "LOT", "Cabling access void", "As per AV spec")

    # ── Generate ─────────────────────────────────────
    output_path = os.path.join(output_dir, "G0304_1F_3000-00_SW.02-PLINTH DETAILS_v2.svg")
    sheet.save(output_path)
    print(f"Plinth detail drawing: {output_path}")

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
