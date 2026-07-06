"""
08 Collective — DXF Detail Fabrication Drawing Generator
==========================================================
Generates DXF files for furniture/joinery detail drawings
that can be imported directly into Trimble SketchUp Layout.

Layers (standard naming):
  - 0                    (default)
  - A-FURN-OUTL          Outline / visible lines (white, continuous)
  - A-FURN-HIDD          Hidden lines (gray, dashed)
  - A-FURN-CNTR          Center lines (green, center)
  - A-FURN-HATCH         Section hatch (gray, continuous)
  - A-DIMS               Dimensions (blue)
  - A-ANNO-TEXT          Text annotations (white)
  - A-ANNO-CALLOUT       Callout / notes (red)
  - A-ANNO-SYMB          Symbols / markers (red)
  - A-FURN-SECT          Section cut lines (red, phantom)
  - TITLE-BLOCK          Title block elements (white)

Usage:
    from dxf_detail_fab import DXFDetailSheet

    sheet = DXFDetailSheet(
        title="PLINTH DETAILS - 00_SW.02",
        dwg_no="G0304_1F_3000",
    )
    sheet.add_elevation("Elevation A", x, y, svg_func)
    sheet.save("output.dxf")
"""

import ezdxf
from ezdxf import colors
from ezdxf.enums import TextEntityAlignment
from ezdxf.math import Vec2
import math
from datetime import datetime


# ── Layer Definitions ────────────────────────────────

LAYERS = {
    "A-FURN-OUTL":    {"color": colors.WHITE,  "ltype": "CONTINUOUS", "lw": 0.50},
    "A-FURN-HIDD":    {"color": colors.CYAN,   "ltype": "DASHED2",    "lw": 0.25},
    "A-FURN-CNTR":    {"color": colors.GREEN,  "ltype": "CENTER2",    "lw": 0.18},
    "A-FURN-HATCH":   {"color": colors.GRAY,   "ltype": "CONTINUOUS", "lw": 0.13},
    "A-DIMS":         {"color": colors.BLUE,   "ltype": "CONTINUOUS", "lw": 0.18},
    "A-ANNO-TEXT":    {"color": colors.WHITE,  "ltype": "CONTINUOUS", "lw": 0.13},
    "A-ANNO-CALLOUT": {"color": colors.RED,    "ltype": "CONTINUOUS", "lw": 0.18},
    "A-ANNO-SYMB":    {"color": colors.RED,    "ltype": "CONTINUOUS", "lw": 0.25},
    "A-FURN-SECT":    {"color": colors.RED,    "ltype": "PHANTOM2",   "lw": 0.35},
    "TITLE-BLOCK":    {"color": colors.WHITE,  "ltype": "CONTINUOUS", "lw": 0.35},
}

MM_PER_UNIT = 1.0  # 1 DXF unit = 1 mm


class DXFDetailSheet:
    """A DXF-based detail fabrication drawing.

    All geometry is drawn in model space at 1:1 scale (mm).
    The Layout/Paper Space tile is configured for A3 (420x297mm)
    with a viewport centered in the title block area.
    """

    def __init__(self, title="DETAIL DRAWING", subtitle="",
                 dwg_no="DW-001", revision="",
                 scale="1:10", date=None,
                 client="", project="", project_no="",
                 drawn_by="TREE", checked_by="",
                 approved="", project_stage="",
                 drawing_status="", cad_file="",
                 designer_info="08 Collective Ltd."):
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

        self.doc = ezdxf.new("R2010")
        self.msp = self.doc.modelspace()
        self._setup_layers()
        self._setup_dim_style()

        # Track views for layout
        self.views = []

    # ── Layer Setup ──────────────────────────────────

    def _setup_layers(self):
        for name, cfg in LAYERS.items():
            layer = self.doc.layers.add(name)
            layer.color = cfg["color"]
            layer.linetype = cfg["ltype"]
            layer.lineweight = int(cfg["lw"] * 100)  # ezdxf uses 1/100 mm

    def _setup_dim_style(self):
        dimstyle = self.doc.dimstyles.new("FAB-DIM")
        dimstyle.dimtxt = 2.5
        dimstyle.dimscale = 1.0
        dimstyle.dimasz = 2.0
        dimstyle.dimexe = 1.0
        dimstyle.dimexo = 1.0
        dimstyle.dimclrd = colors.BLUE
        dimstyle.dimclre = colors.BLUE
        dimstyle.dimclrt = colors.BLUE
        dimstyle.dimgap = 0.5
        dimstyle.dimdec = 0
        dimstyle.dimtdec = 0

    # ── Drawing Primitives (thin wrappers) ───────────

    def line(self, x1, y1, x2, y2, layer="A-FURN-OUTL"):
        self.msp.add_line((x1, y1), (x2, y2), dxfattribs={"layer": layer})

    def rect(self, x, y, w, h, layer="A-FURN-OUTL"):
        self.msp.add_lwpolyline([
            (x, y), (x+w, y), (x+w, y+h), (x, y+h), (x, y)
        ], dxfattribs={"layer": layer})

    def circle(self, x, y, r, layer="A-ANNO-SYMB"):
        self.msp.add_circle((x, y), r, dxfattribs={"layer": layer})

    def text(self, x, y, text, layer="A-ANNO-TEXT", size=2.5,
             align="left", angle=0):
        """Add text at (x,y). align: left|center|right."""
        attr = {"layer": layer, "height": size}
        if angle:
            attr["rotation"] = angle
        t = self.msp.add_text(text, dxfattribs=attr)
        if align == "center":
            t.set_placement((x, y), align=TextEntityAlignment.CENTER)
        elif align == "right":
            t.set_placement((x, y), align=TextEntityAlignment.RIGHT)
        else:
            t.set_placement((x, y), align=TextEntityAlignment.LEFT)

    def hatch_solid(self, x, y, w, h, layer="A-FURN-HATCH",
                    pattern="ANSI31", scale=1.0):
        """Add a hatch pattern within a rectangular boundary."""
        hatch = self.msp.add_hatch(color=LAYERS[layer]["color"],
                                    dxfattribs={"layer": layer})
        hatch.paths.add_polyline_path(
            [(x, y), (x+w, y), (x+w, y+h), (x, y+h), (x, y)],
            is_closed=True
        )
        try:
            # ezdxf >= 1.4
            from ezdxf.hatch import HatchPattern
            hatch.set_pattern(HatchPattern(name=pattern, angle=0, scale=scale))
        except (ImportError, AttributeError):
            # Fallback: load pattern from acad.pat
            try:
                hatch.load_pattern(pattern)
                hatch.pattern_scale = scale
            except Exception:
                pass  # skip hatch if pattern fails
        return hatch

    def dim_horizontal(self, y, x1, x2, label, offset=8, layer="A-DIMS"):
        """Aligned horizontal dimension."""
        dim = self.msp.add_linear_dim(
            base=(x1, y - offset),
            p1=(x1, y),
            p2=(x2, y),
            dimstyle="FAB-DIM",
            dxfattribs={"layer": layer},
        )
        dim.render()
        # Add text override
        if label:
            dim.dimension.dimtext = str(label)
        return dim

    def dim_vertical(self, x, y1, y2, label, offset=8, layer="A-DIMS"):
        """Aligned vertical dimension."""
        dim = self.msp.add_linear_dim(
            base=(x - offset, y1),
            p1=(x, y1),
            p2=(x, y2),
            dimstyle="FAB-DIM",
            dxfattribs={"layer": layer},
            angle=90,
        )
        dim.render()
        if label:
            dim.dimension.dimtext = str(label)
        return dim

    def leader(self, x1, y1, x2, y2, text="", layer="A-ANNO-CALLOUT"):
        """Simple leader line with optional text."""
        self.line(x1, y1, x2, y2, layer=layer)
        if text:
            self.text(x2 + 1, y2 - 1, text, layer=layer, size=2)

    def section_cut(self, x1, y1, x2, y2, label, layer="A-FURN-SECT"):
        """Section cut line with arrows and labels."""
        self.line(x1, y1, x2, y2, layer=layer)
        self.circle(x1, y1, 3, layer=layer)
        self.text(x1, y1, label, layer=layer, size=3, align="center")
        self.circle(x2, y2, 3, layer=layer)
        self.text(x2, y2, label, layer=layer, size=3, align="center")

    # ── View Management ─────────────────────────────

    def add_view(self, name, x, y, draw_func):
        """Add a view. draw_func(msp) draws geometry at origin (0,0)
        within the view. The view is then offset by (x, y)."""
        self.views.append((name, x, y, draw_func))

    def generate(self):
        """Draw all views and title block."""
        for name, vx, vy, draw_func in self.views:
            # Use a transformation to offset the view
            draw_func(self, vx, vy)

        self._draw_title_block()

    def save(self, output_path):
        """Generate and save DXF."""
        self.generate()
        self.doc.saveas(output_path)
        return output_path

    # ── Title Block ─────────────────────────────────

    def _draw_title_block(self):
        """Draw title block at bottom-right of A3 sheet."""
        tb_x = 420 - 210
        tb_y = 0
        tb_w, tb_h = 210, 60

        self.rect(tb_x, tb_y, tb_w, tb_h, layer="TITLE-BLOCK")

        # Header
        self.rect(tb_x, tb_y + tb_h - 10, tb_w, 10, layer="TITLE-BLOCK")
        self.text(tb_x + 5, tb_y + tb_h - 7, self.title, layer="TITLE-BLOCK", size=3.5)

        # Info grid (simplified)
        info = [
            ("DWG No.", self.dwg_no, "Scale", self.scale),
            ("Date", self.date, "Revision", self.revision),
            ("Client", self.client, "Project", self.project),
            ("Drawn", self.drawn_by, "Checked", self.checked_by),
        ]

        row_h = 10
        col_w = tb_w // 2
        label_w = 30

        for ri, (k1, v1, k2, v2) in enumerate(info):
            ry = tb_y + tb_h - 10 - (ri + 1) * row_h
            self.line(tb_x, ry, tb_x + tb_w, ry, layer="TITLE-BLOCK")
            self.line(tb_x + col_w, ry, tb_x + col_w, ry + row_h, layer="TITLE-BLOCK")

            self.text(tb_x + 2, ry + 1, k1, layer="TITLE-BLOCK", size=2)
            self.text(tb_x + label_w, ry + 1, str(v1), layer="TITLE-BLOCK", size=2)
            self.text(tb_x + col_w + 2, ry + 1, k2, layer="TITLE-BLOCK", size=2)
            self.text(tb_x + col_w + label_w, ry + 1, str(v2), layer="TITLE-BLOCK", size=2)


# ─── PLINTH COMPONENT GENERATORS ──────────────────────

def plinth_elevation(sheet, ox, oy):
    """Draw plinth elevation (880w x 120h)."""
    pw, ph = 880, 120
    layer = "A-FURN-OUTL"

    sheet.rect(ox, oy, pw, ph, layer=layer)

    # Compartment divisions
    divs = [550, 760, 430, 640, 60]
    cx = 0
    for d in divs:
        cx += d
        if cx < pw - 1:
            sheet.line(ox + cx, oy, ox + cx, oy + ph, layer="A-FURN-HIDD")

    # Dimensions
    sheet.dim_horizontal(oy, ox, ox + pw, "880")
    sheet.dim_vertical(ox, oy, oy + ph, "120")


def plinth_section(sheet, ox, oy):
    """Draw plinth section through construction layers."""
    pw, ph = 430, 120
    layers = [
        (12, "12mm MDF face"),
        (18, "18mm MDF frame"),
        (60, "Void"),
        (18, "18mm MDF base"),
        (12, "12mm MDF bottom"),
    ]
    cy = oy
    for thick, label in layers:
        sheet.rect(ox, cy, pw, thick, layer="A-FURN-OUTL")
        sheet.hatch_solid(ox, cy, pw, thick, pattern="ANSI31", scale=1.0)
        sheet.text(ox + pw // 2, cy + thick // 2 - 1, label,
                   layer="A-ANNO-TEXT", size=2, align="center")
        cy += thick

    sheet.dim_vertical(ox + pw + 10, oy, oy + ph, "120")


# ─── BENCH COMPONENT GENERATORS ───────────────────────

def bench_elevation(sheet, ox, oy):
    """Draw curve bench elevation."""
    bw, bh = 3720, 400

    # Floor line
    sheet.line(ox - 100, oy + bh, ox + bw + 100, oy + bh, layer="A-FURN-OUTL")

    # Legs
    leg_pos = [bw * 0.08, bw * 0.5, bw * 0.92]
    for lx in leg_pos:
        sheet.rect(ox + lx - 40, oy + bh - 90, 80, 90, layer="A-FURN-OUTL")

    # Seat frame
    frame_y = oy + bh - 120
    sheet.rect(ox, frame_y, bw, 18, layer="A-FURN-OUTL")

    # Cushion
    cushion_y = frame_y - 50
    sheet.rect(ox + 50, cushion_y, bw - 100, 50, layer="A-FURN-OUTL")

    # Dimensions
    sheet.dim_horizontal(oy + bh + 5, ox, ox + bw, "3720")
    sheet.dim_vertical(ox - 15, cushion_y, oy + bh, "350")
    sheet.dim_vertical(ox - 15, cushion_y, cushion_y + 50, "50")

    # Text
    sheet.text(ox + bw // 2, frame_y + 9, "12mm MDF  FI_08",
               layer="A-ANNO-TEXT", size=3, align="center")
    sheet.text(ox + bw // 2, cushion_y + 25, "Cushion  FI_25",
               layer="A-ANNO-TEXT", size=3, align="center")


def bench_section(sheet, ox, oy):
    """Draw bench section through construction."""
    bd = 500
    bh = 350

    # Floor
    sheet.line(ox - 20, oy, ox + bd + 20, oy, layer="A-FURN-OUTL")

    # Frame
    frame_y = oy - 18
    sheet.rect(ox, frame_y, bd, 18, layer="A-FURN-OUTL")
    sheet.hatch_solid(ox, frame_y, bd, 18, pattern="ANSI31", scale=1.0)

    # Support
    sheet.rect(ox + bd // 2 - 30, oy - 90, 60, 90, layer="A-FURN-OUTL")

    # Cushion
    cushion_y = frame_y - 50
    sheet.rect(ox + 20, cushion_y, bd - 40, 50, layer="A-FURN-OUTL")

    # Dimensions
    sheet.dim_horizontal(oy + 5, ox, ox + bd, "500")
    sheet.dim_vertical(ox - 15, cushion_y, oy, "350")
    sheet.dim_vertical(ox - 15, cushion_y, cushion_y + 50, "50")


# ─── TABLE COMPONENT GENERATORS ───────────────────────

def table_elevation(sheet, ox, oy):
    """Draw detail table elevation."""
    tw, th = 4025, 700  # from reference: 4025w x 700h mm

    # Table top
    sheet.rect(ox, oy + th - 30, tw, 30, layer="A-FURN-OUTL")
    sheet.hatch_solid(ox, oy + th - 30, tw, 30, pattern="ANSI31", scale=1.0)
    sheet.text(ox + tw // 2, oy + th - 15, "18mm MDF  FI_07",
               layer="A-ANNO-TEXT", size=3, align="center")

    # Trestles
    trestle_positions = [tw * 0.05, tw * 0.95]
    for tx in trestle_positions:
        sheet.rect(ox + tx - 30, oy + 100, 60, th - 130, layer="A-FURN-OUTL")
        sheet.text(ox + tx, oy + th // 2, "Trestle  FI_20",
                   layer="A-ANNO-TEXT", size=2.5, align="center")

    # AV housing below table
    av_w, av_h = 800, 200
    av_x = (tw - av_w) // 2
    sheet.rect(ox + av_x, oy + 100, av_w, av_h, layer="A-FURN-OUTL")
    sheet.text(ox + av_x + av_w // 2, oy + 200, "AV Housing  AV-03-A",
               layer="A-ANNO-TEXT", size=2.5, align="center")

    # Dimensions
    sheet.dim_horizontal(oy + th + 5, ox, ox + tw, "4025")
    sheet.dim_vertical(ox - 15, oy, oy + th, "700")

    # Access panel note
    sheet.text(ox + av_x + av_w // 2, oy + 150, "Access panel for CPU",
               layer="A-ANNO-CALLOUT", size=2.5, align="center")


# ─── DEMO SCRIPTS ─────────────────────────────────────

def generate_plinth_dxf(output_path):
    """Generate plinth detail DXF."""
    sheet = DXFDetailSheet(
        title="PLINTH DETAILS - 00_SW.02 - PRELUDE PLINTH",
        subtitle="Typical detail G03&04",
        dwg_no="G0304_1F_3000",
        revision="v1",
        scale="1:10 / 1:5",
        date="2026.06.25",
        client="Hong Kong Heritage Museum",
        project="Meet Mona Lisa",
        project_no="8105",
        drawn_by="TREE",
        checked_by="AL",
    )

    # View 1: Elevation A at origin
    sheet.add_view("Elevation A", 50, 300, plinth_elevation)
    # View 2: Section A-A
    sheet.add_view("Section A-A", 50, 100, plinth_section)

    sheet.save(output_path)
    return output_path


def generate_bench_dxf(output_path):
    """Generate bench detail DXF."""
    sheet = DXFDetailSheet(
        title="CURVE BENCH - 05_SW.11 - G05 Gallery 5",
        subtitle="Gallery Typical Details G05",
        dwg_no="G05_1F_3003",
        revision="v1",
        scale="1:10 / 1:5",
        date="2026.06.25",
        client="Hong Kong Heritage Museum",
        project="Meet Mona Lisa - Immersive Experience",
        project_no="8105",
        drawn_by="TREE",
        checked_by="AL",
    )

    sheet.add_view("Elevation A", 50, 400, bench_elevation)
    sheet.add_view("Section A-A", 50, 100, bench_section)

    sheet.save(output_path)
    return output_path


def generate_table_dxf(output_path):
    """Generate table detail DXF."""
    sheet = DXFDetailSheet(
        title="TABLE DETAILS - 01_SW.02 - TIMELINE TABLE",
        subtitle="Typical detail G03&G04",
        dwg_no="G0304_1F_3001",
        revision="v1",
        scale="1:20",
        date="2026.06.25",
        client="Hong Kong Heritage Museum",
        project="Meet Mona Lisa",
        project_no="8105",
        drawn_by="TREE",
        checked_by="AL",
    )

    sheet.add_view("Elevation A", 50, 300, table_elevation)

    sheet.save(output_path)
    return output_path
