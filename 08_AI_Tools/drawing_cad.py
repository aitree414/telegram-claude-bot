"""
08 Collective — CAD-style Production Drawing Generator
=========================================================
Generates production drawings matching 08 Collective's actual
fabrication standard: white background, black linework, precise mm
dimensions, multi-view projections, title block, grid refs.

Based on reference: G-03木榔分件门头祥图.pdf (CAD woodworking detail)
and Truss plan.pdf (truss layout with gusset plate details).

Usage:
    from drawing_cad import CADDrawing, View, Dimension, BOM

    dwg = CADDrawing(title="PRODUCTION DRAWING", dwg_no="DW-001")
    dwg.add_view(View("FRONT", x=50, y=100, svg_content=...))
    dwg.add_bom([...])
    dwg.add_notes([...])
    dwg.save("output.svg")

IMPORTANT: For SVG generation, all coordinates in the drawing area
use the viewBox coordinate system (0 0 1190 841 for A3 landscape).
"""

import html
from datetime import datetime


def xml_escape(text):
    """Escape XML special characters in text content."""
    return html.escape(str(text), quote=False)


class CADDrawing:
    """A white-background CAD-style production drawing matching 08 Collective standard.

    Layout (A3 landscape, 1190x841 viewBox):
        - Top: drawing title + info bar
        - Left/Center: drawing views (main, sections, details)
        - Bottom-left: notes block
        - Bottom-right: title block + revision table
        - Optional: BOM table, grid references
    """

    # Style tokens matching their production CAD standard
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
        "weld": "#c00",
        "hatch": "#d0d0d0",
    }

    def __init__(self, title="PRODUCTION DRAWING", subtitle="",
                 dwg_no="DW-001", revision="v1", scale="NTS",
                 date=None, client="", project="",
                 designer="TREE", checker="", approved=""):
        self.title = title
        self.subtitle = subtitle
        self.dwg_no = dwg_no
        self.revision = revision
        self.scale = scale
        self.date = date or datetime.now().strftime("%Y.%m.%d")
        self.client = client
        self.project = project
        self.designer = designer
        self.checker = checker
        self.approved = approved

        self.views = []
        self.notes = []
        self.bom = []
        self.revisions = []
        self.grid_refs = []  # [(label, x, y), ...]
        self.custom_svg_before = []
        self.custom_svg_after = []

        # Track bottom of drawing area for notes/title block placement
        self._drawing_bottom = 720

    # ── Public API ──────────────────────────────────────────

    def add_view(self, view):
        """Add a View object to the drawing."""
        self.views.append(view)

    def add_bom(self, bom_items):
        """Add BOM items. Each item: [no, qty, unit, description, spec] or dict."""
        self.bom.extend(bom_items)

    def add_notes(self, notes):
        """Add general notes (list of strings)."""
        self.notes.extend(notes)

    def add_revision(self, rev, date, description):
        """Add a revision entry."""
        self.revisions.append((rev, date, description))

    def add_grid_ref(self, label, x, y):
        """Add a grid reference marker (e.g. 'B-3', 'D-5')."""
        self.grid_refs.append((label, x, y))

    # ── SVG Generation ─────────────────────────────────────

    def generate(self):
        """Generate the full SVG string."""
        W, H = 1190, 841
        lines = []

        # ── Prolog ──
        self._svg_header(lines, W, H)
        self._svg_defs(lines)

        # ── Background ──
        lines.append(f'<rect width="{W}" height="{H}" fill="{self.STYLE["bg"]}"/>')

        # ── Border ──
        lines.append(f'<rect x="25" y="25" width="{W-50}" height="{H-50}" '
                     f'fill="none" stroke="{self.STYLE["geom"]}" stroke-width="2"/>')
        lines.append(f'<rect x="28" y="28" width="{W-56}" height="{H-56}" '
                     f'fill="none" stroke="{self.STYLE["geom"]}" stroke-width="0.5"/>')

        # ── Grid ──
        self._draw_grid(lines, 30, 55, 850, 730)

        # ── Custom SVG before views ──
        for svg in self.custom_svg_before:
            lines.append(svg)

        # ── Title / Info bar ──
        self._draw_title_bar(lines, W)

        # ── Views ──
        for view in self.views:
            lines.append(view.render())

        # ── Grid references ──
        self._draw_grid_refs(lines)

        # ── BOM table ──
        if self.bom:
            self._draw_bom(lines)

        # ── Notes block ──
        if self.notes:
            self._draw_notes(lines)

        # ── Title block ──
        self._draw_title_block(lines)

        # ── Revision block ──
        if self.revisions:
            self._draw_revision_block(lines)

        # ── Custom SVG after ──
        for svg in self.custom_svg_after:
            lines.append(svg)

        lines.append('</svg>')
        return '\n'.join(lines)

    def save(self, output_path):
        """Generate and save SVG to file."""
        svg = self.generate()
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(svg)
        return output_path

    # ── Internal: SVG structure ────────────────────────────

    def _svg_header(self, lines, W, H):
        lines.extend([
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
            f'width="{W}px" height="{H}px">',
            '<style>',
            '  text { font-family: "Arial", "Microsoft JhengHei", "Helvetica Neue", sans-serif; }',
            f'  .dim-line {{ stroke: {self.STYLE["dim"]}; stroke-width: 0.6; fill: none; }}',
            f'  .dim-ext {{ stroke: {self.STYLE["dim"]}; stroke-width: 0.4; fill: none; }}',
            f'  .dim-text {{ fill: {self.STYLE["dim_text"]}; font-size: 6.5px; }}',
            f'  .dim-text-lg {{ fill: {self.STYLE["dim_text"]}; font-size: 8px; font-weight: 700; }}',
            f'  .geom {{ fill: none; stroke: {self.STYLE["geom"]}; stroke-width: 1.8; }}',
            f'  .geom-thin {{ fill: none; stroke: {self.STYLE["geom_thin"]}; stroke-width: 1; }}',
            f'  .geom-fill {{ fill: {self.STYLE["geom_fill"]}; stroke: {self.STYLE["geom"]}; stroke-width: 1.5; }}',
            f'  .geom-fill-solid {{ fill: {self.STYLE["geom_fill"]}; stroke: {self.STYLE["geom"]}; stroke-width: 1.8; }}',
            f'  .hidden {{ stroke: {self.STYLE["hidden"]}; stroke-width: 0.5; stroke-dasharray: 3,3; fill: none; }}',
            f'  .center {{ stroke: {self.STYLE["center"]}; stroke-width: 0.4; stroke-dasharray: 15,3,3,3; fill: none; }}',
            f'  .section {{ stroke: {self.STYLE["section"]}; stroke-width: 0.8; stroke-dasharray: 10,3,2,3; fill: none; }}',
            f'  .note-red {{ fill: {self.STYLE["note_text"]}; font-size: 6.5px; }}',
            f'  .note-red-lg {{ fill: {self.STYLE["note_text"]}; font-size: 7.5px; font-weight: 700; }}',
            f'  .grid-major {{ stroke: {self.STYLE["grid_major"]}; stroke-width: 0.4; fill: none; }}',
            f'  .grid-minor {{ stroke: {self.STYLE["grid_minor"]}; stroke-width: 0.2; fill: none; }}',
            f'  .weld {{ stroke: {self.STYLE["weld"]}; stroke-width: 1.2; fill: none; }}',
            f'  .bom-text {{ fill: {self.STYLE["geom"]}; font-size: 6px; }}',
            f'  .bom-hdr {{ fill: {self.STYLE["title_text"]}; font-size: 6.5px; font-weight: 700; }}',
            f'  .label {{ fill: {self.STYLE["geom_thin"]}; font-size: 6.5px; }}',
            f'  .hatch {{ fill: url(#hatch45); }}',
            '</style>',
        ])

    def _svg_defs(self, lines):
        lines.extend([
            '<defs>',
            '  <pattern id="hatch45" width="6" height="6" patternUnits="userSpaceOnUse" '
            'patternTransform="rotate(45)">',
            f'    <line x1="0" y1="0" x2="0" y2="6" stroke="{self.STYLE["hatch"]}" stroke-width="0.5"/>',
            '  </pattern>',
            '  <marker id="arr-dim" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">',
            f'    <path d="M0,0 L8,3 L0,6 Z" fill="{self.STYLE["dim"]}"/>',
            '  </marker>',
            '  <marker id="arr-dim-start" markerWidth="8" markerHeight="6" refX="0" refY="3" orient="auto">',
            f'    <path d="M8,0 L0,3 L8,6 Z" fill="{self.STYLE["dim"]}"/>',
            '  </marker>',
            '  <marker id="dot-dim" markerWidth="4" markerHeight="4" refX="2" refY="2">',
            f'    <circle cx="2" cy="2" r="2" fill="{self.STYLE["dim"]}"/>',
            '  </marker>',
            '  <marker id="arr-section" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">',
            f'    <path d="M0,0 L8,3 L0,6 Z" fill="{self.STYLE["section"]}"/>',
            '  </marker>',
            '</defs>',
        ])

    def _draw_grid(self, lines, x_start, y_start, w, h):
        """Draw minor + major grid within the drawing area."""
        # Vertical minor (every 20px = 200mm at 1:10 scale approx)
        for gx in range(x_start, x_start + w, 20):
            lines.append(f'<line x1="{gx}" y1="{y_start}" x2="{gx}" y2="{y_start+h}" class="grid-minor"/>')
        # Horizontal minor
        for gy in range(y_start, y_start + h, 20):
            lines.append(f'<line x1="{x_start}" y1="{gy}" x2="{x_start+w}" y2="{gy}" class="grid-minor"/>')
        # Vertical major (every 100px)
        for gx in range(x_start, x_start + w, 100):
            lines.append(f'<line x1="{gx}" y1="{y_start}" x2="{gx}" y2="{y_start+h}" class="grid-major"/>')
        # Horizontal major
        for gy in range(y_start, y_start + h, 100):
            lines.append(f'<line x1="{x_start}" y1="{gy}" x2="{x_start+w}" y2="{gy}" class="grid-major"/>')

    def _draw_title_bar(self, lines, W):
        """Top info bar with drawing title and metadata."""
        mid = W // 2
        lines.extend([
            f'<text x="{mid}" y="18" text-anchor="middle" font-size="10" '
            f'font-weight="700" fill="{self.STYLE["geom"]}">{self.title}</text>',
        ])
        if self.subtitle:
            lines.append(
                f'<text x="{mid}" y="38" text-anchor="middle" font-size="8" '
                f'fill="{self.STYLE["geom_thin"]}">{xml_escape(self.subtitle)}</text>'
            )

    def _draw_grid_refs(self, lines):
        """Draw grid reference labels at zone boundaries."""
        for label, x, y in self.grid_refs:
            lines.extend([
                f'<text x="{x}" y="{y}" text-anchor="middle" font-size="6" '
                f'fill="{self.STYLE["grid_major"]}" font-weight="700">{label}</text>',
            ])

    def _draw_bom(self, lines):
        """BOM table positioned above notes on left side."""
        bx, by = 30, 545  # bottom-left of BOM area
        ncols = 5
        headers = ["ITEM", "QTY", "UNIT", "DESCRIPTION / 描述", "SPEC / 規格"]
        widths = [40, 35, 40, 220, 180]
        total_w = sum(widths)
        row_h = 16
        header_h = 18

        # Table title
        lines.extend([
            f'<rect x="{bx}" y="{by-18}" width="{total_w}" height="18" '
            f'fill="{self.STYLE["title_bg"]}" stroke="{self.STYLE["bom_border"]}" stroke-width="1"/>',
            f'<text x="{bx+8}" y="{by-5}" class="bom-hdr">BILL OF MATERIALS  材料表</text>',
        ])

        xp = bx
        for hdr, w in zip(headers, widths):
            lines.extend([
                f'<rect x="{xp}" y="{by}" width="{w}" height="{header_h}" '
                f'fill="{self.STYLE["title_bg"]}" stroke="{self.STYLE["bom_border"]}" stroke-width="0.5"/>',
                f'<text x="{xp+4}" y="{by+12}" class="bom-hdr">{hdr}</text>',
            ])
            xp += w

        for ri, row in enumerate(self.bom[:25]):  # max 25 rows
            ry = by + header_h + ri * row_h
            xp = bx
            fill = self.STYLE.get("bom_alt", "#f0f2f5") if ri % 2 == 0 else self.STYLE["bg"]
            for ci, val in enumerate(row[:ncols]):
                w = widths[ci]
                lines.extend([
                    f'<rect x="{xp}" y="{ry}" width="{w}" height="{row_h}" '
                    f'fill="{fill}" stroke="{self.STYLE["bom_border"]}" stroke-width="0.3"/>',
                    f'<text x="{xp+4}" y="{ry+11}" class="bom-text">{xml_escape(val)}</text>',
                ])
                xp += w

    def _draw_notes(self, lines):
        """Notes block in bottom-left area."""
        ny = 575
        nx = 30
        note_w = 515

        lines.extend([
            f'<rect x="{nx}" y="{ny-16}" width="{note_w}" height="16" '
            f'fill="{self.STYLE["title_bg"]}" stroke="{self.STYLE["bom_border"]}" stroke-width="1"/>',
            f'<text x="{nx+8}" y="{ny-4}" class="bom-hdr">GENERAL NOTES  一般註解</text>',
        ])

        # Calculate needed height
        note_h = max(len(self.notes) * 14 + 8, 30)
        lines.append(
            f'<rect x="{nx}" y="{ny}" width="{note_w}" height="{note_h}" '
            f'fill="{self.STYLE["bg"]}" stroke="{self.STYLE["bom_border"]}" stroke-width="1"/>'
        )

        for i, note in enumerate(self.notes):
            # Check if it's a warning/red note
            is_warn = note.startswith("!")
            cls = "note-red" if is_warn else "bom-text"
            display_note = xml_escape(note.lstrip("!"))
            lines.append(
                f'<text x="{nx+6}" y="{ny+12+i*14}" class="{cls}">{display_note}</text>'
            )

    def _draw_title_block(self, lines):
        """Professional title block at bottom-right, matching CAD standard."""
        tb_x, tb_y = 830, 696
        tb_w, tb_h = 335, 120

        # Main border
        lines.append(
            f'<rect x="{tb_x}" y="{tb_y}" width="{tb_w}" height="{tb_h}" '
            f'fill="{self.STYLE["bg"]}" stroke="{self.STYLE["geom"]}" stroke-width="1.5"/>'
        )

        # Title row
        lines.extend([
            f'<rect x="{tb_x}" y="{tb_y}" width="{tb_w}" height="24" '
            f'fill="{self.STYLE["title_bg"]}"/>',
            f'<text x="{tb_x+tb_w//2}" y="{tb_y+16}" text-anchor="middle" '
            f'font-size="11" font-weight="700" fill="{self.STYLE["title_text"]}">{self.title}</text>',
        ])

        # Info grid (3 columns × 4 rows)
        fields = [
            ("DWG NO.", self.dwg_no, "SCALE", self.scale),
            ("REVISION", self.revision, "DATE", self.date),
            ("CLIENT", self.client, "PROJECT", self.project),
            ("DESIGNED", self.designer, "CHECKED", self.checker),
        ]
        col_w = tb_w // 2
        row_h = 18

        for ri, (k1, v1, k2, v2) in enumerate(fields):
            ry = tb_y + 24 + ri * row_h
            # Left field
            lines.extend([
                f'<text x="{tb_x+8}" y="{ry+12}" class="label">{k1}</text>',
                f'<text x="{tb_x+65}" y="{ry+12}" class="bom-text">{xml_escape(v1)}</text>',
            ])
            # Right field
            lines.extend([
                f'<text x="{tb_x+col_w+8}" y="{ry+12}" class="label">{k2}</text>',
                f'<text x="{tb_x+col_w+65}" y="{ry+12}" class="bom-text">{xml_escape(v2)}</text>',
            ])
            # Horizontal separator
            if ri < len(fields) - 1:
                lines.append(
                    f'<line x1="{tb_x}" y1="{ry+row_h}" x2="{tb_x+tb_w}" y2="{ry+row_h}" '
                    f'stroke="{self.STYLE["geom"]}" stroke-width="0.3"/>'
                )

        # Vertical divider
        lines.append(
            f'<line x1="{tb_x+col_w}" y1="{tb_y+24}" x2="{tb_x+col_w}" y2="{tb_y+tb_h}" '
            f'stroke="{self.STYLE["geom"]}" stroke-width="0.5"/>'
        )

        # Bottom right: approval
        approved_y = tb_y + 24 + 3 * row_h
        lines.extend([
            f'<text x="{tb_x+col_w+8}" y="{approved_y+12}" class="label">APPROVED</text>',
            f'<text x="{tb_x+col_w+65}" y="{approved_y+12}" class="bom-text">{self.approved or "—"}</text>',
        ])
        lines.append(
            f'<line x1="{tb_x}" y1="{approved_y+row_h}" x2="{tb_x+tb_w}" y2="{approved_y+row_h}" '
            f'stroke="{self.STYLE["geom"]}" stroke-width="0.5"/>'
        )

        # Footer
        lines.extend([
            f'<text x="{tb_x+8}" y="{tb_y+tb_h-4}" font-size="5" '
            f'fill="{self.STYLE["hidden"]}">© 08 Collective Ltd.  |  All dimensions in mm  |  Do not scale from drawing</text>',
        ])

    def _draw_revision_block(self, lines):
        """Revision table above title block or beside it."""
        rx, ry = 830, 650
        rw, rh = 335, 40

        lines.extend([
            f'<rect x="{rx}" y="{ry}" width="{rw}" height="16" '
            f'fill="{self.STYLE["title_bg"]}" stroke="{self.STYLE["bom_border"]}" stroke-width="1"/>',
            f'<text x="{rx+8}" y="{ry+12}" class="bom-hdr">REVISIONS  修訂記錄</text>',
        ])

        # Header row
        hdr_y = ry + 16
        hdrs = [("REV", 35), ("DATE", 55), ("DESCRIPTION", 245)]
        xp = rx
        for hdr, w in hdrs:
            lines.extend([
                f'<rect x="{xp}" y="{hdr_y}" width="{w}" height="14" '
                f'fill="{self.STYLE["title_bg"]}" stroke="{self.STYLE["bom_border"]}" stroke-width="0.5"/>',
                f'<text x="{xp+4}" y="{hdr_y+10}" class="bom-hdr">{hdr}</text>',
            ])
            xp += w

        # Revision rows (max 4)
        for ri, (rev, rdate, desc) in enumerate(self.revisions[:4]):
            rrow_y = hdr_y + 14 + ri * 14
            xp = rx
            vals = [rev, rdate, desc]
            for val, (_, w) in zip(vals, hdrs):
                lines.extend([
                    f'<rect x="{xp}" y="{rrow_y}" width="{w}" height="14" '
                    f'fill="{self.STYLE["bg"]}" stroke="{self.STYLE["bom_border"]}" stroke-width="0.3"/>',
                    f'<text x="{xp+4}" y="{rrow_y+10}" class="bom-text">{xml_escape(val)}</text>',
                ])
                xp += w


class View:
    """A drawing viewport: front, side, section, or detail view.

    Each view renders SVG content within its bounding box, with
    a view label and scale indicator.
    """

    def __init__(self, label, x, y, width, height, scale="",
                 svg_content=None, view_type="front"):
        self.label = label
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.scale = scale
        self.svg_content = svg_content or []
        self.view_type = view_type

    def render(self):
        """Render this view as SVG group string."""
        lines = [
            f'<g id="view-{self.label}" transform="translate({self.x}, {self.y})">',
        ]

        # View label
        scale_str = f"  S: {self.scale}" if self.scale else ""
        lines.append(
            f'<text x="0" y="-6" font-size="7" font-weight="700" '
            f'fill="#333">視圖: {self.label}{scale_str}</text>'
        )

        # View content
        for svg_line in self.svg_content:
            lines.append(svg_line)

        lines.append('</g>')
        return '\n'.join(lines)


def dim_horizontal(y, x1, x2, label, offset=12, style="dim"):
    """Generate horizontal dimension lines. Returns SVG lines."""
    arr = "arr-dim"
    return [
        f'<line x1="{x1}" y1="{y-offset}" x2="{x1}" y2="{y-offset+6}" class="dim-ext"/>',
        f'<line x1="{x2}" y1="{y-offset}" x2="{x2}" y2="{y-offset+6}" class="dim-ext"/>',
        f'<line x1="{x1}" y1="{y-offset}" x2="{x2}" y2="{y-offset}" '
        f'class="dim-line" marker-start="url(#{arr})" marker-end="url(#{arr})"/>',
        f'<text x="{(x1+x2)//2}" y="{y-offset-2}" text-anchor="middle" class="dim-text">{label}</text>',
    ]


def dim_vertical(x, y1, y2, label, offset=12, style="dim"):
    """Generate vertical dimension lines. Returns SVG lines."""
    arr = "arr-dim"
    return [
        f'<line x1="{x-offset}" y1="{y1}" x2="{x-offset+6}" y2="{y1}" class="dim-ext"/>',
        f'<line x1="{x-offset}" y1="{y2}" x2="{x-offset+6}" y2="{y2}" class="dim-ext"/>',
        f'<line x1="{x-offset}" y1="{y1}" x2="{x-offset}" y2="{y2}" '
        f'class="dim-line" marker-start="url(#{arr})" marker-end="url(#{arr})"/>',
        f'<text x="{x-offset-2}" y="{(y1+y2)//2}" text-anchor="end" '
        f'class="dim-text" transform="rotate(-90,{x-offset-2},{(y1+y2)//2})">{label}</text>',
    ]


def center_line(x1, y1, x2, y2):
    """Generate a center line."""
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="center"/>'


def section_line(x1, y1, x2, y2, label=""):
    """Generate a section cut line with labels."""
    lines = [
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="section"/>',
    ]
    if label:
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        lines.extend([
            f'<circle cx="{x1}" cy="{y1}" r="7" fill="#fff" '
            f'stroke="{CADDrawing.STYLE["section"]}" stroke-width="0.8"/>',
            f'<text x="{x1}" y="{y1+2.5}" text-anchor="middle" '
            f'font-size="7" font-weight="700" fill="{CADDrawing.STYLE["section"]}">{label}</text>',
            f'<circle cx="{x2}" cy="{y2}" r="7" fill="#fff" '
            f'stroke="{CADDrawing.STYLE["section"]}" stroke-width="0.8"/>',
            f'<text x="{x2}" y="{y2+2.5}" text-anchor="middle" '
            f'font-size="7" font-weight="700" fill="{CADDrawing.STYLE["section"]}">{label}</text>',
        ])
    return '\n'.join(lines)


def material_callout(x, y, text, align="left"):
    """Material label with leader line."""
    anchor = "start" if align == "left" else "end"
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" '
        f'font-size="6" fill="#c00" font-weight="600">{text}</text>'
    )
