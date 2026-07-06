"""
08 Collective — Detail Fabrication Drawing Generator
======================================================
Produces component-level detail fabrication drawings (DETAIL 圖)
matching 08 Collective's actual production standard.

Based on reference:
  - G0304_1F_3000-00_SW.02-PLINTH DETAILS.pdf
  - G0304_1F_3001-01_SW.02-TABLE DETAILS REV A.pdf
  - G05_1F_3005-06b_SW.07-Photobooth walls REV A.pdf
  - G-03木榔分件门头祥图.pdf (CAD woodworking detail)

Features:
  - Multi-view sheets: Elevation A/B/C, Plan, Axo, Section, Detail
  - Component-level dimensioning with material thickness callouts
  - Finish specification references (FI_xx)
  - Professional title block: drawing number, stage, status, revision
  - Scale annotations (1:5, 1:10, 1:20, 1:50)
  - Section cut lines connecting views
  - Revision history table
  - Material hatch patterns and weld symbols
"""

import html
from datetime import datetime


def xml_escape(text):
    """Escape XML special characters in text content."""
    return html.escape(str(text), quote=False)


STYLE = {
    "bg": "#ffffff",
    "grid_major": "#d0d0d0",
    "grid_minor": "#e8e8e8",
    "geom": "#111111",
    "geom_fill": "#f7f5f0",
    "geom_thin": "#444444",
    "dim": "#0055cc",
    "dim_text": "#0055cc",
    "note": "#c00",
    "note_text": "#c00",
    "section": "#c00",
    "hidden": "#999999",
    "center": "#008844",
    "title_bg": "#1a1a2e",
    "title_text": "#ffffff",
    "bom_border": "#222222",
    "bom_alt": "#f0f2f5",
    "hatch": "#d0d0d0",
    "hatch_dense": "#bbbbbb",
    "weld": "#c00",
    "callout_fi": "#aa00cc",
    "material_fill_wood": "#f5e6d0",
    "material_fill_steel": "#dce6f0",
    "material_fill_mdf": "#ede4d3",
    "material_fill_acrylic": "#d8ecf5",
    "material_fill_fabric": "#e8d8e0",
}


# ─── VIEW TYPES ───────────────────────────────────────

ELEVATION = "elevation"
PLAN = "plan"
SECTION = "section"
DETAIL = "detail"
AXO = "axo"

VIEW_TYPE_LABELS = {
    ELEVATION: "Elevation",
    PLAN: "Plan",
    SECTION: "Section",
    DETAIL: "Detail",
    AXO: "Axonometric",
}


# ─── MAIN SHEET CLASS ─────────────────────────────────

class DetailSheet:
    """A3 detail fabrication drawing sheet (1190x841 viewBox).

    Layout:
        +--------------------------------------------------+
        |  Title Bar                                       |
        +----------+---------------------------------------+
        |          |                                        |
        |  Views   |   Views                               |
        |  (left)  |   (right)                             |
        |          |                                        |
        +----------+---------------------------+-----------+
        | Notes    | Detail / Axo View         | Title     |
        | Block    |                           | Block     |
        +----------+---------------------------+-----------+
    """

    def __init__(self, title="DETAIL DRAWING", subtitle="",
                 dwg_no="DW-001", revision="",
                 scale="1:10", date=None,
                 client="", project="", project_no="",
                 drawn_by="TREE", checked_by="", approved="",
                 project_stage="", drawing_status="",
                 cad_file="", designer_info=""):
        self.title = title
        self.subtitle = subtitle
        self.dwg_no = dwg_no
        self.revision = revision
        self.scale = scale
        self.date = date or datetime.now().strftime("%Y.%m.%d")
        self.client = client
        self.project = project
        self.project_no = project_no
        self.drawn_by = drawn_by
        self.checked_by = checked_by
        self.approved = approved
        self.project_stage = project_stage
        self.drawing_status = drawing_status
        self.cad_file = cad_file
        self.designer_info = designer_info

        self.views = []
        self.notes = []
        self.revisions = []
        self.finish_refs = []
        self.bom = []

    # ── Public API ──────────────────────────────────

    def add_view(self, view):
        """Add a FabView to the sheet."""
        self.views.append(view)

    def add_note(self, note):
        """Add a construction / general note."""
        self.notes.append(note)

    def add_revision(self, rev_no, rev_date, description):
        """Add a revision table entry."""
        self.revisions.append((rev_no, rev_date, description))

    def add_finish_ref(self, fi_ref, description, note=""):
        """Add a finish specification reference (FI_xx)."""
        self.finish_refs.append((fi_ref, description, note))

    def add_bom_item(self, item_no, qty, unit, description, spec=""):
        """Add a BOM item."""
        self.bom.append((item_no, qty, unit, description, spec))

    # ── SVG Generation ──────────────────────────────

    def generate(self):
        """Generate the full SVG string."""
        W, H = 1190, 841
        lines = []

        self._svg_header(lines, W, H)
        self._svg_defs(lines)

        # Background
        lines.append(f'<rect width="{W}" height="{H}" fill="{STYLE["bg"]}"/>')

        # Border
        lines.append(f'<rect x="25" y="25" width="{W-50}" height="{H-50}" '
                     f'fill="none" stroke="{STYLE["geom"]}" stroke-width="2"/>')
        lines.append(f'<rect x="28" y="28" width="{W-56}" height="{H-56}" '
                     f'fill="none" stroke="{STYLE["geom"]}" stroke-width="0.5"/>')

        # Grid in drawing area
        self._draw_grid(lines, 30, 55, 850, 540)

        # Title bar
        self._draw_title_bar(lines, W)

        # Views
        for view in self.views:
            lines.append(view.render())

        # Finish reference block
        if self.finish_refs:
            self._draw_finish_refs(lines)

        # Notes block
        if self.notes:
            self._draw_notes(lines)

        # BOM table
        if self.bom:
            self._draw_bom(lines)

        # Title block (bottom-right)
        self._draw_title_block(lines)

        # Revision block
        if self.revisions:
            self._draw_revision_block(lines)

        lines.append('</svg>')
        return '\n'.join(lines)

    def save(self, output_path):
        """Generate and save SVG to file."""
        svg = self.generate()
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(svg)
        return output_path

    # ── Internal: SVG structure ─────────────────────

    def _svg_header(self, lines, W, H):
        lines.extend([
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
            f'width="{W}px" height="{H}px">',
            '<style>',
            '  text { font-family: "Arial", "Microsoft JhengHei", "Helvetica Neue", sans-serif; }',
            f'  .dim-line {{ stroke: {STYLE["dim"]}; stroke-width: 0.6; fill: none; }}',
            f'  .dim-ext {{ stroke: {STYLE["dim"]}; stroke-width: 0.4; fill: none; }}',
            f'  .dim-text {{ fill: {STYLE["dim_text"]}; font-size: 6.5px; }}',
            f'  .dim-text-lg {{ fill: {STYLE["dim_text"]}; font-size: 8px; font-weight: 700; }}',
            f'  .geom {{ fill: none; stroke: {STYLE["geom"]}; stroke-width: 1.8; }}',
            f'  .geom-thin {{ fill: none; stroke: {STYLE["geom_thin"]}; stroke-width: 1; }}',
            f'  .geom-fill {{ fill: {STYLE["geom_fill"]}; stroke: {STYLE["geom"]}; stroke-width: 1.5; }}',
            f'  .geom-fill-solid {{ fill: {STYLE["geom_fill"]}; stroke: {STYLE["geom"]}; stroke-width: 1.8; }}',
            f'  .hidden {{ stroke: {STYLE["hidden"]}; stroke-width: 0.5; stroke-dasharray: 3,3; fill: none; }}',
            f'  .center {{ stroke: {STYLE["center"]}; stroke-width: 0.4; stroke-dasharray: 15,3,3,3; fill: none; }}',
            f'  .section {{ stroke: {STYLE["section"]}; stroke-width: 0.8; stroke-dasharray: 10,3,2,3; fill: none; }}',
            f'  .note-red {{ fill: {STYLE["note_text"]}; font-size: 6.5px; }}',
            f'  .note-red-lg {{ fill: {STYLE["note_text"]}; font-size: 7.5px; font-weight: 700; }}',
            f'  .grid-major {{ stroke: {STYLE["grid_major"]}; stroke-width: 0.4; fill: none; }}',
            f'  .grid-minor {{ stroke: {STYLE["grid_minor"]}; stroke-width: 0.2; fill: none; }}',
            f'  .weld {{ stroke: {STYLE["weld"]}; stroke-width: 1.2; fill: none; }}',
            f'  .bom-text {{ fill: {STYLE["geom"]}; font-size: 6px; }}',
            f'  .bom-hdr {{ fill: {STYLE["title_text"]}; font-size: 6.5px; font-weight: 700; }}',
            f'  .label {{ fill: {STYLE["geom_thin"]}; font-size: 6.5px; }}',
            f'  .label-bold {{ fill: {STYLE["geom"]}; font-size: 6.5px; font-weight: 700; }}',
            f'  .callout-fi {{ fill: {STYLE["callout_fi"]}; font-size: 6px; font-weight: 600; }}',
            f'  .callout-mat {{ fill: {STYLE["note"]}; font-size: 6.5px; font-weight: 600; }}',
            f'  .hatch {{ fill: url(#hatch45); }}',
            f'  .hatch-dense {{ fill: url(#hatch-dense); }}',
            f'  .hatch-cross {{ fill: url(#hatch-cross); }}',
            f'  .hatch-mdf {{ fill: url(#hatch-mdf); }}',
            '</style>',
        ])

    def _svg_defs(self, lines):
        lines.extend([
            '<defs>',
            # 45-degree hatch (general)
            '  <pattern id="hatch45" width="6" height="6" patternUnits="userSpaceOnUse" '
            'patternTransform="rotate(45)">',
            f'    <line x1="0" y1="0" x2="0" y2="6" stroke="{STYLE["hatch"]}" stroke-width="0.5"/>',
            '  </pattern>',
            # Dense hatch
            '  <pattern id="hatch-dense" width="4" height="4" patternUnits="userSpaceOnUse" '
            'patternTransform="rotate(45)">',
            f'    <line x1="0" y1="0" x2="0" y2="4" stroke="{STYLE["hatch_dense"]}" stroke-width="0.5"/>',
            '  </pattern>',
            # Cross-hatch
            '  <pattern id="hatch-cross" width="8" height="8" patternUnits="userSpaceOnUse">',
            f'    <line x1="0" y1="0" x2="8" y2="8" stroke="{STYLE["hatch"]}" stroke-width="0.4"/>',
            f'    <line x1="8" y1="0" x2="0" y2="8" stroke="{STYLE["hatch"]}" stroke-width="0.4"/>',
            '  </pattern>',
            # MDF-specific hatch (dots)
            '  <pattern id="hatch-mdf" width="6" height="6" patternUnits="userSpaceOnUse">',
            f'    <circle cx="1.5" cy="1.5" r="0.6" fill="{STYLE["hatch_dense"]}"/>',
            f'    <circle cx="4.5" cy="4.5" r="0.6" fill="{STYLE["hatch_dense"]}"/>',
            '  </pattern>',
            # Dimension arrows
            '  <marker id="arr-dim" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">',
            f'    <path d="M0,0 L8,3 L0,6 Z" fill="{STYLE["dim"]}"/>',
            '  </marker>',
            '  <marker id="arr-dim-start" markerWidth="8" markerHeight="6" refX="0" refY="3" orient="auto">',
            f'    <path d="M8,0 L0,3 L8,6 Z" fill="{STYLE["dim"]}"/>',
            '  </marker>',
            '  <marker id="dot-dim" markerWidth="4" markerHeight="4" refX="2" refY="2">',
            f'    <circle cx="2" cy="2" r="2" fill="{STYLE["dim"]}"/>',
            '  </marker>',
            '  <marker id="arr-section" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">',
            f'    <path d="M0,0 L10,3.5 L0,7 Z" fill="{STYLE["section"]}"/>',
            '  </marker>',
            '</defs>',
        ])

    def _draw_grid(self, lines, x_start, y_start, w, h):
        for gx in range(x_start, x_start + w, 20):
            lines.append(f'<line x1="{gx}" y1="{y_start}" x2="{gx}" y2="{y_start+h}" class="grid-minor"/>')
        for gy in range(y_start, y_start + h, 20):
            lines.append(f'<line x1="{x_start}" y1="{gy}" x2="{x_start+w}" y2="{gy}" class="grid-minor"/>')
        for gx in range(x_start, x_start + w, 100):
            lines.append(f'<line x1="{gx}" y1="{y_start}" x2="{gx}" y2="{y_start+h}" class="grid-major"/>')
        for gy in range(y_start, y_start + h, 100):
            lines.append(f'<line x1="{x_start}" y1="{gy}" x2="{x_start+w}" y2="{gy}" class="grid-major"/>')

    def _draw_title_bar(self, lines, W):
        mid = W // 2
        lines.append(
            f'<text x="{mid}" y="18" text-anchor="middle" font-size="10" '
            f'font-weight="700" fill="{STYLE["geom"]}">{xml_escape(self.title)}</text>')
        if self.subtitle:
            lines.append(
                f'<text x="{mid}" y="38" text-anchor="middle" font-size="8" '
                f'fill="{STYLE["geom_thin"]}">{xml_escape(self.subtitle)}</text>'
            )

    def _draw_finish_refs(self, lines):
        """Finish specification reference block (FI_xx)."""
        fx, fy = 30, 570
        fw = 250

        lines.extend([
            f'<rect x="{fx}" y="{fy-16}" width="{fw}" height="16" '
            f'fill="{STYLE["title_bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="1"/>',
            f'<text x="{fx+8}" y="{fy-4}" class="bom-hdr">FINISH SCHEDULE  飾面規格</text>',
        ])

        row_h = 15
        table_h = len(self.finish_refs) * row_h + 18
        lines.append(
            f'<rect x="{fx}" y="{fy}" width="{fw}" height="{table_h}" '
            f'fill="{STYLE["bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="1"/>'
        )

        # Headers
        hdrs = [("REF", 35), ("DESCRIPTION", 215)]
        xp = fx
        for hdr, w in hdrs:
            lines.extend([
                f'<rect x="{xp}" y="{fy}" width="{w}" height="18" '
                f'fill="{STYLE["bom_border"]}" stroke="{STYLE["bom_border"]}" stroke-width="0.3"/>',
                f'<text x="{xp+4}" y="{fy+12}" class="bom-hdr">{hdr}</text>',
            ])
            xp += w

        for ri, (fi_ref, desc, note) in enumerate(self.finish_refs):
            ry = fy + 18 + ri * row_h
            fill = STYLE["bom_alt"] if ri % 2 == 0 else STYLE["bg"]
            texts = [fi_ref, desc]
            xp = fx
            for ti, (val, (_, w)) in enumerate(zip(texts, hdrs)):
                cls = "callout-fi" if ti == 0 else "bom-text"
                lines.extend([
                    f'<rect x="{xp}" y="{ry}" width="{w}" height="{row_h}" '
                    f'fill="{fill}" stroke="{STYLE["bom_border"]}" stroke-width="0.3"/>',
                    f'<text x="{xp+4}" y="{ry+11}" class="{cls}">{xml_escape(val)}</text>',
                ])
                xp += w

    def _draw_notes(self, lines):
        """Notes block in bottom-left area."""
        ny = 570
        nx = 290
        note_w = 250
        note_h = max(len(self.notes) * 14 + 8, 30)

        lines.extend([
            f'<rect x="{nx}" y="{ny-16}" width="{note_w}" height="16" '
            f'fill="{STYLE["title_bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="1"/>',
            f'<text x="{nx+8}" y="{ny-4}" class="bom-hdr">GENERAL NOTES  一般註解</text>',
            f'<rect x="{nx}" y="{ny}" width="{note_w}" height="{note_h}" '
            f'fill="{STYLE["bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="1"/>',
        ])

        for i, note in enumerate(self.notes):
            is_warn = note.startswith("!")
            cls = "note-red" if is_warn else "bom-text"
            display_note = xml_escape(note.lstrip("!"))
            lines.append(
                f'<text x="{nx+6}" y="{ny+12+i*14}" class="{cls}">{display_note}</text>'
            )

    def _draw_bom(self, lines):
        """BOM table."""
        bx, by = 550, 570
        ncols = 5
        headers = ["ITEM", "QTY", "UNIT", "DESCRIPTION  描述", "SPEC  規格"]
        widths = [30, 30, 30, 150, 120]
        total_w = sum(widths)
        row_h = 15
        header_h = 16

        lines.extend([
            f'<rect x="{bx}" y="{by-16}" width="{total_w}" height="16" '
            f'fill="{STYLE["title_bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="1"/>',
            f'<text x="{bx+8}" y="{by-4}" class="bom-hdr">BILL OF MATERIALS  材料表</text>',
        ])

        xp = bx
        for hdr, w in zip(headers, widths):
            lines.extend([
                f'<rect x="{xp}" y="{by}" width="{w}" height="{header_h}" '
                f'fill="{STYLE["title_bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="0.5"/>',
                f'<text x="{xp+4}" y="{by+11}" class="bom-hdr">{hdr}</text>',
            ])
            xp += w

        for ri, row in enumerate(self.bom[:20]):
            ry = by + header_h + ri * row_h
            xp = bx
            fill = STYLE["bom_alt"] if ri % 2 == 0 else STYLE["bg"]
            for ci, val in enumerate(row[:ncols]):
                w = widths[ci]
                lines.extend([
                    f'<rect x="{xp}" y="{ry}" width="{w}" height="{row_h}" '
                    f'fill="{fill}" stroke="{STYLE["bom_border"]}" stroke-width="0.3"/>',
                    f'<text x="{xp+4}" y="{ry+10}" class="bom-text">{xml_escape(str(val))}</text>',
                ])
                xp += w

    def _draw_title_block(self, lines):
        """Professional title block matching reference format.

        Layout (bottom-right corner):
        ┌──────────────────────────────────────────────┐
        │  DRAWING TITLE  (dark header)                 │
        ├───────────┬──────────────────┬───────────────┤
        │ Stage     │ Status           │ Client        │
        ├───────────┼──────────────────┼───────────────┤
        │ Project   │ Project No.      │ CAD File      │
        ├───────────┼──────────────────┼───────────────┤
        │ Scale     │ Date             │ Drawn By      │
        ├───────────┼──────────────────┼───────────────┤
        │ Checked   │ Approved         │ Drawing No.   │
        ├───────────┴──────────────────┴───────────────┤
        │  Designer info / disclaimer / scale bar      │
        └──────────────────────────────────────────────┘
        """
        tb_x, tb_y = 760, 640
        tb_w, tb_h = 405, 176

        # Main border
        lines.append(
            f'<rect x="{tb_x}" y="{tb_y}" width="{tb_w}" height="{tb_h}" '
            f'fill="{STYLE["bg"]}" stroke="{STYLE["geom"]}" stroke-width="1.5"/>'
        )

        # Title row (dark header)
        lines.extend([
            f'<rect x="{tb_x}" y="{tb_y}" width="{tb_w}" height="22" '
            f'fill="{STYLE["title_bg"]}"/>',
            f'<text x="{tb_x+10}" y="{tb_y+15}" font-size="9" font-weight="700" '
            f'fill="{STYLE["title_text"]}">{xml_escape(self.title)}</text>',
        ])

        # Info grid
        grid = [
            ("Project Stage", self.project_stage, "Drawing Status", self.drawing_status),
            ("Client", self.client, "Project Title", self.project),
            ("Project No.", self.project_no, "CAD File", self.cad_file),
            ("Scale", self.scale, "Date", self.date),
            ("Drawn By", self.drawn_by, "Checked By", self.checked_by),
            ("Approved", self.approved, "DWG No.", self.dwg_no),
        ]

        row_h = 15
        label_w = 85
        value_w = (tb_w // 2) - label_w

        for ri, (k1, v1, k2, v2) in enumerate(grid):
            ry = tb_y + 22 + ri * row_h

            # Left group: label + value
            lines.extend([
                f'<rect x="{tb_x}" y="{ry}" width="{label_w}" height="{row_h}" '
                f'fill="{STYLE["bom_alt"]}" stroke="{STYLE["bom_border"]}" stroke-width="0.3"/>',
                f'<text x="{tb_x+4}" y="{ry+10}" class="label">{xml_escape(k1)}</text>',
                f'<rect x="{tb_x+label_w}" y="{ry}" width="{value_w}" height="{row_h}" '
                f'fill="{STYLE["bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="0.3"/>',
                f'<text x="{tb_x+label_w+4}" y="{ry+10}" class="bom-text">{xml_escape(str(v1))}</text>',
            ])

            # Right group
            rx = tb_x + tb_w // 2
            lines.extend([
                f'<rect x="{rx}" y="{ry}" width="{label_w}" height="{row_h}" '
                f'fill="{STYLE["bom_alt"]}" stroke="{STYLE["bom_border"]}" stroke-width="0.3"/>',
                f'<text x="{rx+4}" y="{ry+10}" class="label">{xml_escape(k2)}</text>',
                f'<rect x="{rx+label_w}" y="{ry}" width="{value_w}" height="{row_h}" '
                f'fill="{STYLE["bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="0.3"/>',
                f'<text x="{rx+label_w+4}" y="{ry+10}" class="bom-text">{xml_escape(str(v2))}</text>',
            ])

        # Bottom: revision line
        rev_y = tb_y + 22 + len(grid) * row_h
        lines.extend([
            f'<rect x="{tb_x}" y="{rev_y}" width="{tb_w}" height="16" '
            f'fill="{STYLE["title_bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="0.5"/>',
            f'<text x="{tb_x+8}" y="{rev_y+11}" class="bom-hdr">'
            f'Revision: {xml_escape(self.revision)}  |  {xml_escape(self.dwg_no)}</text>',
        ])

        # Footer / disclaimer
        foot_y = rev_y + 16
        lines.extend([
            f'<rect x="{tb_x}" y="{foot_y}" width="{tb_w}" height="16" '
            f'fill="{STYLE["bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="0.5"/>',
            f'<text x="{tb_x+6}" y="{foot_y+11}" font-size="5.5" '
            f'fill="{STYLE["hidden"]}">{xml_escape(self.designer_info or "08 Collective Ltd.  |  Do not scale from drawing")}</text>',
        ])

    def _draw_revision_block(self, lines):
        """Revision history table, positioned above title block."""
        rx, ry = 760, 590
        rw = 405

        lines.extend([
            f'<rect x="{rx}" y="{ry}" width="{rw}" height="16" '
            f'fill="{STYLE["title_bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="1"/>',
            f'<text x="{rx+8}" y="{ry+11}" class="bom-hdr">REVISIONS  修訂記錄</text>',
        ])

        hdr_y = ry + 16
        hdrs = [("No.", 35), ("Date", 60), ("Revision Notes", 310)]
        xp = rx
        for hdr, w in hdrs:
            lines.extend([
                f'<rect x="{xp}" y="{hdr_y}" width="{w}" height="14" '
                f'fill="{STYLE["title_bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="0.5"/>',
                f'<text x="{xp+4}" y="{hdr_y+10}" class="bom-hdr">{hdr}</text>',
            ])
            xp += w

        for ri, (rev_no, rev_date, desc) in enumerate(self.revisions[:6]):
            rrow_y = hdr_y + 14 + ri * 14
            xp = rx
            vals = [rev_no, rev_date, desc]
            for val, (_, w) in zip(vals, hdrs):
                lines.extend([
                    f'<rect x="{xp}" y="{rrow_y}" width="{w}" height="14" '
                    f'fill="{STYLE["bg"]}" stroke="{STYLE["bom_border"]}" stroke-width="0.3"/>',
                    f'<text x="{xp+4}" y="{rrow_y+10}" class="bom-text">{xml_escape(str(val))}</text>',
                ])
                xp += w


# ─── FABRICATION VIEW ─────────────────────────────────

class FabView:
    """A single fabrication view on a DetailSheet.

    Supports: elevation, plan, section, detail, axo
    Each view renders within its bounding box with a label + scale bar.
    """

    def __init__(self, label, view_type, x, y, width, height,
                 scale="", svg_content=None):
        self.label = label
        self.view_type = view_type
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.scale = scale
        self.svg_content = svg_content or []

    def render(self):
        """Render this view as SVG group string."""
        lines = [
            f'<g id="view-{self.label}" transform="translate({self.x}, {self.y})">',
        ]

        # View label
        type_label = VIEW_TYPE_LABELS.get(self.view_type, self.view_type)
        scale_str = f"  Scale: {self.scale}" if self.scale else ""
        lines.append(
            f'<text x="0" y="-6" font-size="7" font-weight="700" fill="#333">'
            f'{xml_escape(self.label)} — {type_label}{xml_escape(scale_str)}</text>'
        )

        # View border (light dashed)
        lines.append(
            f'<rect x="0" y="0" width="{self.width}" height="{self.height}" '
            f'fill="none" stroke="{STYLE["hidden"]}" stroke-width="0.3" stroke-dasharray="2,2"/>'
        )

        # View content
        for svg_line in self.svg_content:
            lines.append(svg_line)

        lines.append('</g>')
        return '\n'.join(lines)


# ─── ANNOTATION HELPERS ───────────────────────────────

def dim_horizontal(y, x1, x2, label, offset=12):
    """Horizontal dimension line with arrows."""
    arr = "arr-dim"
    return [
        f'<line x1="{x1}" y1="{y-offset}" x2="{x1}" y2="{y-offset+5}" class="dim-ext"/>',
        f'<line x1="{x2}" y1="{y-offset}" x2="{x2}" y2="{y-offset+5}" class="dim-ext"/>',
        f'<line x1="{x1}" y1="{y-offset}" x2="{x2}" y2="{y-offset}" '
        f'class="dim-line" marker-start="url(#arr-dim)" marker-end="url(#arr-dim)"/>',
        f'<text x="{(x1+x2)//2}" y="{y-offset-2}" text-anchor="middle" class="dim-text">{xml_escape(label)}</text>',
    ]


def dim_vertical(x, y1, y2, label, offset=12):
    """Vertical dimension line with arrows."""
    return [
        f'<line x1="{x-offset}" y1="{y1}" x2="{x-offset+5}" y2="{y1}" class="dim-ext"/>',
        f'<line x1="{x-offset}" y1="{y2}" x2="{x-offset+5}" y2="{y2}" class="dim-ext"/>',
        f'<line x1="{x-offset}" y1="{y1}" x2="{x-offset}" y2="{y2}" '
        f'class="dim-line" marker-start="url(#arr-dim)" marker-end="url(#arr-dim)"/>',
        f'<text x="{x-offset-2}" y="{(y1+y2)//2}" text-anchor="end" '
        f'class="dim-text" transform="rotate(-90,{x-offset-2},{(y1+y2)//2})">{xml_escape(label)}</text>',
    ]


def dim_stacked(y, segments, offset=12, gap=8):
    """Multiple stacked horizontal dimensions. segments = [(x1, x2, label), ...]."""
    result = []
    for i, (x1, x2, label) in enumerate(segments):
        result.extend(dim_horizontal(y, x1, x2, label, offset + i * gap))
    return result


def center_line(x1, y1, x2, y2):
    """Center line (long dash, short dash, short dash)."""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="center"/>'


def section_cut(x1, y1, x2, y2, label, arrow_pos="both"):
    """Section cut line with arrowhead markers and circled label."""
    lines = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="section"/>']

    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

    # Arrowheads
    if arrow_pos in ("start", "both"):
        lines.append(
            f'<use href="#arr-section" x="{x1}" y="{y1}" transform="rotate({_angle(x1,y1,x2,y2)},{x1},{y1})"/>'
        )
    if arrow_pos in ("end", "both"):
        lines.append(
            f'<use href="#arr-section" x="{x2}" y="{y2}" transform="rotate({_angle(x2,y2,x1,y1)},{x2},{y2})"/>'
        )

    # Label circles at both ends
    for ex, ey in [(x1, y1), (x2, y2)]:
        lines.extend([
            f'<circle cx="{ex}" cy="{ey}" r="7" fill="#fff" '
            f'stroke="{STYLE["section"]}" stroke-width="0.8"/>',
            f'<text x="{ex}" y="{ey+2.5}" text-anchor="middle" '
            f'font-size="7" font-weight="700" fill="{STYLE["section"]}">{xml_escape(label)}</text>',
        ])

    # Center label
    lines.append(
        f'<text x="{cx}" y="{cy-6}" text-anchor="middle" font-size="6.5" '
        f'fill="{STYLE["section"]}">SECTION {xml_escape(label)}</text>'
    )
    return '\n'.join(lines)


def _angle(x1, y1, x2, y2):
    """Angle in degrees from (x1,y1) pointing toward (x2,y2)."""
    import math
    return math.degrees(math.atan2(y2 - y1, x2 - x1))


def finish_callout(x, y, text, fi_ref, align="left"):
    """Finish specification callout (e.g. 'Painted MDF  —  FI_07')."""
    anchor = "start" if align == "left" else "end"
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
        f'class="callout-fi">{xml_escape(text)} — {xml_escape(fi_ref)}</text>'
    )


def material_label(x, y, text, thickness="", align="left"):
    """Material label (e.g. '12mm MDF face panel')."""
    anchor = "start" if align == "left" else "end"
    full = f'{thickness} {text}' if thickness else text
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
        f'class="callout-mat">{xml_escape(full)}</text>'
    )


def detail_marker(x, y, label, size=7):
    """Detail callout circle with label (e.g. 'B' for Detail B)."""
    lines = [
        f'<circle cx="{x}" cy="{y}" r="{size}" fill="#fff" '
        f'stroke="{STYLE["section"]}" stroke-width="0.8"/>',
        f'<text x="{x}" y="{y+2.5}" text-anchor="middle" font-size="7" '
        f'font-weight="700" fill="{STYLE["section"]}">{xml_escape(label)}</text>',
    ]
    return '\n'.join(lines)


def leader_line(x1, y1, x2, y2, text="", dot=False):
    """Leader line from point (x1,y1) to label at (x2,y2) with optional text."""
    lines = [
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
        f'stroke="{STYLE["geom"]}" stroke-width="0.6"/>',
    ]
    if dot:
        lines.append(
            f'<circle cx="{x1}" cy="{y1}" r="1.5" fill="{STYLE["geom"]}"/>'
        )
    if text:
        lines.append(
            f'<text x="{x2+3}" y="{y2+2}" font-size="6" fill="{STYLE["geom"]}">{xml_escape(text)}</text>'
        )
    return '\n'.join(lines)


def component_balloon(x, y, number, size=8):
    """Circular balloon callout for part numbering."""
    lines = [
        f'<circle cx="{x}" cy="{y}" r="{size}" fill="#fff" '
        f'stroke="{STYLE["geom"]}" stroke-width="0.8"/>',
        f'<text x="{x}" y="{y+2.5}" text-anchor="middle" font-size="7" '
        f'font-weight="700" fill="{STYLE["geom"]}">{number}</text>',
    ]
    return '\n'.join(lines)


def hatch_rect(x, y, w, h, hatch_class="hatch"):
    """Rectangle with hatch pattern fill."""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
        f'class="{hatch_class}" stroke="{STYLE["geom"]}" stroke-width="0.5"/>'
    )


def material_section(x, y, w, h, label="", fill_class="hatch-mdf"):
    """Draw a material section rectangle with hatch + optional center label."""
    lines = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" '
        f'fill="{STYLE["bg"]}" stroke="{STYLE["geom"]}" stroke-width="1.2"/>',
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" class="{fill_class}"/>',
    ]
    if label:
        lines.append(
            f'<text x="{x+w//2}" y="{y+h//2+2}" text-anchor="middle" '
            f'font-size="5.5" fill="{STYLE["geom"]}">{xml_escape(label)}</text>'
        )
    return '\n'.join(lines)


def dimension_overall(x1, y1, x2, y2, label, offset=16):
    """Overall dimension with extension lines from geometry corners."""
    lines = [
        f'<line x1="{x1}" y1="{y1}" x2="{x1}" y2="{y1-offset+5}" class="dim-ext"/>',
        f'<line x1="{x2}" y1="{y2}" x2="{x2}" y2="{y2-offset+5}" class="dim-ext"/>',
        f'<line x1="{x1}" y1="{y1-offset}" x2="{x2}" y2="{y2-offset}" '
        f'class="dim-line" marker-start="url(#arr-dim)" marker-end="url(#arr-dim)"/>',
        f'<text x="{(x1+x2)//2}" y="{min(y1,y2)-offset-2}" text-anchor="middle" '
        f'class="dim-text-lg">{xml_escape(label)}</text>',
    ]
    return '\n'.join(lines)


# ─── STANDARD TITLE BLOCK PRESETS ─────────────────────

def museum_studio_title_block():
    """Title block configuration matching Museum Studio format."""
    return {
        "project_stage": "4.0 Scheme Design",
        "drawing_status": "For Information",
        "designer_info": "+44 (0) 20 7378 9900  museumstudio.com  Museum Studio, India House, 45 Curlew Street London SE1 2ND",
    }


def collective_title_block():
    """Simpler title block for 08 Collective's own fabrication drawings."""
    return {
        "designer_info": "08 Collective Ltd.  |  All dimensions in mm  |  Do not scale from drawing",
    }


# ─── COMPONENT GENERATORS: PLINTH ─────────────────────

def generate_plinth_elevation(w, h, compartments=None, scale_factor=1.0):
    """Generate SVG for a plinth front elevation.

    Args:
        w: total plinth width in mm (will be scaled)
        h: total plinth height in mm
        compartments: list of (width_mm, label, fi_ref) for each compartment
        scale_factor: px per mm (e.g. 0.1 for 1:10 scale in a 1190x841 viewBox)

    Returns:
        List of SVG line strings (to be used as FabView.svg_content)
    """
    s = scale_factor
    svg = []

    # Plinth body
    pw, ph = w * s, h * s
    svg.append(f'<rect x="0" y="0" width="{pw}" height="{ph}" '
               f'class="geom-fill" stroke-width="1.5"/>')

    # Internal compartments
    if compartments:
        cx = 0
        for cw, label, fi_ref in compartments:
            cw_px = cw * s
            if cx + cw_px < pw - 1:
                svg.append(f'<line x1="{cx+cw_px}" y1="0" x2="{cx+cw_px}" y2="{ph}" '
                           f'class="geom-thin"/>')
            # Label inside compartment
            if label:
                svg.append(
                    f'<text x="{cx+cw_px//2}" y="{ph//2+2}" text-anchor="middle" '
                    f'font-size="5.5" fill="{STYLE["geom_thin"]}">{xml_escape(label)}</text>'
                )
            if fi_ref:
                svg.append(
                    f'<text x="{cx+cw_px//2}" y="{ph//2-6}" text-anchor="middle" '
                    f'class="callout-fi">{xml_escape(fi_ref)}</text>'
                )
            cx += cw_px

    # Overall dimension
    svg.extend(dim_horizontal(0, 0, pw, f"{w}", offset=10))
    svg.extend(dim_vertical(0, 0, ph, f"{h}", offset=10))

    return svg


def generate_plinth_section(w, h, layers=None, scale_factor=1.0):
    """Generate SVG for a plinth section cut (vertical).

    Args:
        w: section width (plinth depth) in mm
        h: section height in mm
        layers: list of (thickness_mm, label, fill_class) from top to bottom
        scale_factor: px per mm

    Returns:
        List of SVG line strings
    """
    s = scale_factor
    svg = []

    if layers:
        cy = 0
        for thick, label, fill_class in layers:
            th_px = thick * s
            if fill_class:
                svg.append(material_section(0, cy, w * s, th_px, label, fill_class))
            else:
                svg.append(
                    f'<rect x="0" y="{cy}" width="{w*s}" height="{th_px}" '
                    f'class="geom" stroke-width="1.2"/>'
                )
                if label:
                    svg.append(
                        f'<text x="{w*s//2}" y="{cy+th_px//2+2}" text-anchor="middle" '
                        f'font-size="5.5" fill="{STYLE["geom"]}">{xml_escape(label)}</text>'
                    )
            cy += th_px

        # Overall dimension
        svg.extend(dim_vertical(w * s + 5, 0, cy, f"{h}", offset=16))

    return svg


def generate_plinth_corner_detail(scale_factor=2.0):
    """Generate SVG for a plinth corner joint detail (1:2 scale)."""
    s = scale_factor
    svg = []

    # Vertical MDF frame
    frame_w = 18 * s
    face_w = 12 * s

    # Horizontal frame (top)
    svg.append(hatch_rect(0, 0, 80 * s, frame_w, "hatch-mdf"))
    svg.append(f'<text x="{40*s}" y="{frame_w//2+2}" text-anchor="middle" '
               f'font-size="6" fill="{STYLE["geom"]}">18mm MDF frame</text>')

    # Vertical frame (left)
    svg.append(hatch_rect(0, 0, frame_w, 60 * s, "hatch-mdf"))

    # Face panel (front, vertical)
    svg.append(hatch_rect(0, frame_w, face_w, 60 * s - frame_w, "hatch-mdf"))
    svg.append(f'<rect x="0" y="{frame_w}" width="{face_w}" height="{60*s-frame_w}" '
               f'fill="none" stroke="{STYLE["geom"]}" stroke-width="1.2"/>')

    # Face panel label
    svg.append(
        f'<text x="{face_w+4}" y="{35*s}" font-size="6" class="callout-mat">'
        f'12mm MDF face panel</text>'
    )

    # Corner roundover
    r = 5 * s
    svg.append(
        f'<path d="M{face_w},{frame_w} A{r},{r} 0 0,0 {face_w+r},{frame_w-r}" '
        f'fill="none" stroke="{STYLE["note"]}" stroke-width="0.8"/>'
    )
    svg.append(
        f'<text x="{face_w+r+4}" y="{frame_w-4}" font-size="5.5" '
        f'fill="{STYLE["note"]}">R5 corner round</text>'
    )

    # Screw indicator
    screw_x = face_w + 8 * s
    svg.extend([
        f'<line x1="{screw_x}" y1="{frame_w+10*s}" x2="{screw_x}" y2="{frame_w+16*s}" '
        f'stroke="{STYLE["geom"]}" stroke-width="0.8"/>',
        f'<line x1="{screw_x-3}" y1="{frame_w+13*s}" x2="{screw_x+3}" y2="{frame_w+13*s}" '
        f'stroke="{STYLE["geom"]}" stroke-width="0.8"/>',
        f'<text x="{screw_x+5}" y="{frame_w+15*s}" font-size="5.5" '
        f'fill="{STYLE["geom"]}">Screw M4 @300 c/c</text>',
    ])

    return svg


# ─── COMPONENT GENERATORS: BENCH ──────────────────────

def generate_bench_elevation(w, h, seat_h, cushion_h, scale_factor=1.0):
    """Generate SVG for a bench front elevation.

    Args:
        w: bench width mm
        h: bench total height mm
        seat_h: seat height from floor mm
        cushion_h: cushion thickness mm
        scale_factor: px per mm
    """
    s = scale_factor
    svg = []

    pw, ph = w * s, h * s

    # Legs (simplified - two vertical lines at each end)
    leg_w = 40 * s
    svg.append(f'<rect x="0" y="{seat_h*s}" width="{leg_w}" height="{ph-seat_h*s}" '
               f'class="geom-fill" stroke-width="1.2"/>')
    svg.append(f'<rect x="{pw-leg_w}" y="{seat_h*s}" width="{leg_w}" height="{ph-seat_h*s}" '
               f'class="geom-fill" stroke-width="1.2"/>')

    # Seat frame
    svg.append(f'<rect x="0" y="{seat_h*s-cushion_h*s-18*s}" width="{pw}" height="18" '
               f'fill="{STYLE["material_fill_mdf"]}" stroke="{STYLE["geom"]}" stroke-width="1.2"/>')

    # Cushion
    cushion_y = seat_h * s - cushion_h * s
    svg.append(f'<rect x="{leg_w//2}" y="{cushion_y}" width="{pw-leg_w}" height="{cushion_h*s}" '
               f'fill="{STYLE["material_fill_fabric"]}" stroke="{STYLE["geom"]}" stroke-width="1.2" rx="3"/>')
    svg.append(
        f'<text x="{pw//2}" y="{cushion_y+cushion_h*s//2+2}" text-anchor="middle" '
        f'font-size="6" fill="{STYLE["geom"]}">Cushion — FI_23</text>'
    )

    # Dimensions
    svg.extend(dim_horizontal(0, 0, pw, f"{w}", offset=10))
    svg.extend(dim_vertical(pw + 5, 0, ph, f"{h}", offset=12))

    return svg


def generate_bench_section(depth, h, seat_h, cushion_h, scale_factor=1.0):
    """Generate SVG for a bench side/section view."""
    s = scale_factor
    svg = []

    pd, ph = depth * s, h * s

    # Floor
    svg.append(f'<line x1="0" y1="{ph}" x2="{pd}" y2="{ph}" '
               f'stroke="{STYLE["geom"]}" stroke-width="1.5"/>')

    # Leg
    svg.append(f'<rect x="{pd//2-10*s}" y="{seat_h*s}" width="{20*s}" height="{ph-seat_h*s}" '
               f'class="geom-fill" stroke-width="1.2"/>')

    # Timber frame
    frame_y = seat_h * s - 18 * s - cushion_h * s
    svg.append(material_section(0, frame_y, pd, 18 * s, "18mm MDF", "hatch-mdf"))

    # Cushion
    svg.append(f'<rect x="5" y="{frame_y- cushion_h*s}" width="{pd-10}" height="{cushion_h*s}" '
               f'fill="{STYLE["material_fill_fabric"]}" stroke="{STYLE["geom"]}" stroke-width="1.2" rx="3"/>')

    # Cushion label
    svg.append(
        f'<text x="{pd//2}" y="{frame_y-cushion_h*s//2+2}" text-anchor="middle" '
        f'font-size="6" fill="{STYLE["geom"]}">Cushion — FI_23</text>'
    )

    # Dimensions
    svg.extend(dim_horizontal(ph + 5, 0, pd, f"{depth}", offset=10))

    return svg


# ─── COMPONENT GENERATORS: TABLE ──────────────────────

def generate_table_elevation(w, h, top_thick=18, scale_factor=1.0):
    """Generate SVG for a table front elevation."""
    s = scale_factor
    svg = []

    pw, ph = w * s, h * s

    # Table top
    svg.append(material_section(0, 0, pw, top_thick * s, f"{top_thick}mm MDF — FI_07", "hatch-mdf"))

    # Legs or trestles
    leg_positions = [60 * s, pw - 60 * s]
    for lx in leg_positions:
        svg.append(f'<rect x="{lx-8*s}" y="{top_thick*s}" width="{16*s}" height="{ph-top_thick*s}" '
                   f'class="geom-fill" stroke-width="1.2"/>')
        svg.append(f'<text x="{lx}" y="{ph//2+top_thick*s//2+2}" text-anchor="middle" '
                   f'font-size="5.5" fill="{STYLE["geom"]}">Trestle FI_20</text>')

    # AV housing (below table)
    av_w = 300 * s
    av_x = (pw - av_w) // 2
    svg.append(hatch_rect(av_x, top_thick * s + 20 * s, av_w, 80 * s, "hatch-dense"))
    svg.append(
        f'<text x="{av_x+av_w//2}" y="{top_thick*s+60*s}" text-anchor="middle" '
        f'font-size="5.5" fill="{STYLE["geom"]}">AV Housing — AV-03-A</text>'
    )

    # Dimensions
    svg.extend(dim_horizontal(0, 0, pw, f"{w}", offset=10))
    svg.extend(dim_vertical(pw + 5, 0, ph, f"{h}", offset=12))

    return svg
