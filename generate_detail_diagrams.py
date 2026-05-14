#!/usr/bin/env python3
"""
Generate detailed technical diagrams for 香港文聯 Central Library
Exhibition Structure - 20260507 阶段性尺寸说明
"""
import svgwrite
import os

OUTPUT_DIR = "/Users/aitree414/Documents/08/香港文聯CentralLibrary/20260507阶段性尺寸说明/詳圖"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def create_diagram_01_plan_layout():
    """Item 01: 平面佈置圖 - Plan Layout"""
    dwg = svgwrite.Drawing(os.path.join(OUTPUT_DIR, "ITEM01_平面佈置圖.svg"),
                           size=("900px", "600px"))

    # Title
    dwg.add(dwg.text("ITEM 01 — 平面佈置圖 PLAN LAYOUT (1:100)",
                     insert=(450, 30), text_anchor="middle",
                     font_size=18, font_weight="bold", font_family="Arial"))

    # Main plan outline - three bay structure
    # Bay 1: 5450, Bay 2: 1500, Bay 3: 5850
    # Total: 13600, scale ~ 1:15 (900/13600*1000 ≈ 66px/m)
    scale = 0.048  # 48px per 1000mm

    x0, y0 = 60, 100

    # Function to convert mm to px
    def mm(val): return val * scale

    # Overall outline
    total_w = mm(13600)
    total_h = mm(4000)
    dwg.add(dwg.rect(insert=(x0, y0), size=(total_w, total_h),
                      fill="none", stroke="black", stroke_width=2))

    # Bay divisions
    x1 = x0 + mm(5450)
    x2 = x1 + mm(1500)
    dwg.add(dwg.line(start=(x1, y0), end=(x1, y0+total_h),
                      stroke="black", stroke_width=1.5, stroke_dasharray="8,4"))
    dwg.add(dwg.line(start=(x2, y0), end=(x2, y0+total_h),
                      stroke="black", stroke_width=1.5, stroke_dasharray="8,4"))

    # Bay labels
    for label, x, w in [("展區一", x0, mm(5450)), ("通道", x1, mm(1500)), ("展區二", x2, mm(5850))]:
        dwg.add(dwg.text(label, insert=(x + w/2, y0+total_h+25),
                         text_anchor="middle", font_size=12, font_family="Arial"))

    # Dimensions - horizontal
    dwg.add(dwg.text("5450", insert=(x0 + mm(5450)/2, y0-10),
                     text_anchor="middle", font_size=10, font_family="Arial"))
    dwg.add(dwg.text("1500", insert=(x1 + mm(1500)/2, y0-10),
                     text_anchor="middle", font_size=10, font_family="Arial"))
    dwg.add(dwg.text("5850", insert=(x2 + mm(5850)/2, y0-10),
                     text_anchor="middle", font_size=10, font_family="Arial"))
    dwg.add(dwg.text("13600 (全長)", insert=(x0 + total_w/2, y0-30),
                     text_anchor="middle", font_size=11, font_weight="bold", font_family="Arial"))

    # Dimension lines (top)
    dwg.add(dwg.line(start=(x0, y0-5), end=(x0, y0-20), stroke="black", stroke_width=1))
    dwg.add(dwg.line(start=(x0+total_w, y0-5), end=(x0+total_w, y0-20), stroke="black", stroke_width=1))
    dwg.add(dwg.line(start=(x0, y0-18), end=(x0+total_w, y0-18), stroke="black", stroke_width=1))

    # Internal elements - Bay 1 (Left exhibition area)
    # LED Screen wall
    wall_x = x0 + mm(500)
    wall_y = y0 + mm(500)
    wall_w = mm(300)
    wall_h = mm(2500)
    dwg.add(dwg.rect(insert=(wall_x, wall_y), size=(wall_w, wall_h),
                      fill="#FFE0E0", stroke="red", stroke_width=1.5))
    dwg.add(dwg.text("LED屏幕牆", insert=(wall_x+wall_w/2, wall_y+wall_h/2),
                     text_anchor="middle", font_size=9, fill="red", font_family="Arial"))

    # Display platforms
    for i, (px, pw) in enumerate([(x0+mm(1200), mm(1200)), (x0+mm(2800), mm(1000)),
                                    (x0+mm(4200), mm(800))]):
        py = y0 + mm(3200)
        ph = mm(400)
        dwg.add(dwg.rect(insert=(px, py), size=(pw, ph),
                          fill="#E0FFE0", stroke="green", stroke_width=1.5))
        dwg.add(dwg.text(f"展台{i+1}", insert=(px+pw/2, py+ph/2),
                         text_anchor="middle", font_size=9, fill="green", font_family="Arial"))

    # Column positions
    for cx in [x0, x0+mm(5450), x0+mm(5450+1500), x0+mm(13600)]:
        dwg.add(dwg.rect(insert=(cx-mm(50), y0+mm(200)), size=(mm(100), mm(600)),
                          fill="#CCCCCC", stroke="black", stroke_width=1))

    # Column spacing dimensions
    col_spacing = [3005, 3005, 3005]
    cx = x0
    for i, sp in enumerate(col_spacing):
        cx_next = cx + mm(sp)
        if cx_next <= x0 + total_w:
            y_dim = y0 + mm(900)
            dwg.add(dwg.text(f"{sp}", insert=((cx+cx_next)/2, y_dim),
                             text_anchor="middle", font_size=9, font_family="Arial"))
            cx = cx_next

    # Scale bar
    sb_x, sb_y = x0, y0 + total_h + 60
    sb_len = mm(2000)
    dwg.add(dwg.line(start=(sb_x, sb_y), end=(sb_x+sb_len, sb_y),
                      stroke="black", stroke_width=2))
    dwg.add(dwg.line(start=(sb_x, sb_y-4), end=(sb_x, sb_y+4), stroke="black", stroke_width=1.5))
    dwg.add(dwg.line(start=(sb_x+sb_len, sb_y-4), end=(sb_x+sb_len, sb_y+4),
                      stroke="black", stroke_width=1.5))
    dwg.add(dwg.text("2000mm", insert=(sb_x+sb_len/2, sb_y+15),
                     text_anchor="middle", font_size=9, font_family="Arial"))

    # Notes
    notes_y = y0 + total_h + 100
    dwg.add(dwg.text("備註：", insert=(x0, notes_y), font_size=11, font_weight="bold", font_family="Arial"))
    dwg.add(dwg.text("1. 整體展區長度 13600mm，分為三個區域", insert=(x0+20, notes_y+20), font_size=10, font_family="Arial"))
    dwg.add(dwg.text("2. 柱間距 3005mm，共4根柱子", insert=(x0+20, notes_y+38), font_size=10, font_family="Arial"))
    dwg.add(dwg.text("3. 中央通道寬度 1500mm", insert=(x0+20, notes_y+56), font_size=10, font_family="Arial"))
    dwg.add(dwg.text("4. LED屏幕牆尺寸：300x2500mm", insert=(x0+20, notes_y+74), font_size=10, font_family="Arial"))

    dwg.save()
    print(f"Created: {os.path.join(OUTPUT_DIR, 'ITEM01_平面佈置圖.svg')}")

def create_diagram_02_front_elevation():
    """Item 02: 正立面圖 - Front Elevation (from ELC Model)"""
    dwg = svgwrite.Drawing(os.path.join(OUTPUT_DIR, "ITEM02_正立面圖.svg"),
                           size=("900px", "650px"))

    dwg.add(dwg.text("ITEM 02 — 正立面圖 FRONT ELEVATION (1:100)",
                     insert=(450, 30), text_anchor="middle",
                     font_size=18, font_weight="bold", font_family="Arial"))

    scale = 0.048
    x0, y0 = 60, 80

    def mm(val): return val * scale

    total_w = mm(13600)
    total_h = mm(4000)

    # Outer frame
    dwg.add(dwg.rect(insert=(x0, y0), size=(total_w, total_h),
                      fill="#FAFAFA", stroke="black", stroke_width=2))

    # Top beam
    beam_h = mm(400)
    dwg.add(dwg.rect(insert=(x0, y0), size=(total_w, beam_h),
                      fill="#E8E8E8", stroke="black", stroke_width=1))
    dwg.add(dwg.text("頂部橫樑 400mm", insert=(x0+total_w/2, y0+beam_h/2),
                     text_anchor="middle", font_size=10, font_family="Arial"))

    # Columns
    col_w = mm(100)
    col_positions = [x0, x0+mm(3005), x0+mm(6010), x0+mm(9015)]
    for cx in col_positions:
        # Column
        dwg.add(dwg.rect(insert=(cx, y0+beam_h), size=(col_w, total_h-beam_h),
                          fill="#D0D0D0", stroke="black", stroke_width=1))
        # Column label
        dwg.add(dwg.text("柱", insert=(cx+col_w/2, y0+beam_h+mm(300)),
                         text_anchor="middle", font_size=8, font_family="Arial"))

    # Bay 1 - LED Screen Area (5450mm)
    bay1_x = x0 + col_w
    bay1_w = mm(5450) - col_w
    # LED Screen panel
    led_y = y0 + beam_h + mm(200)
    led_h = mm(2500)
    dwg.add(dwg.rect(insert=(bay1_x, led_y), size=(bay1_w, led_h),
                      fill="#FFCCCC", stroke="red", stroke_width=1.5, rx=3))
    # LED grid pattern
    for i in range(0, int(bay1_w), 20):
        if (i // 20) % 2 == 0:
            dwg.add(dwg.line(start=(bay1_x+i, led_y), end=(bay1_x+i, led_y+led_h),
                              stroke="#FF9999", stroke_width=0.5))
    for i in range(0, int(led_h), 20):
        if (i // 20) % 2 == 0:
            dwg.add(dwg.line(start=(bay1_x, led_y+i), end=(bay1_x+bay1_w, led_y+i),
                              stroke="#FF9999", stroke_width=0.5))

    dwg.add(dwg.text("LED 大屏幕", insert=(bay1_x+bay1_w/2, led_y+led_h/2-10),
                     text_anchor="middle", font_size=12, font_weight="bold", fill="red", font_family="Arial"))
    dwg.add(dwg.text("7.57m x 2.5m", insert=(bay1_x+bay1_w/2, led_y+led_h/2+12),
                     text_anchor="middle", font_size=10, fill="#CC0000", font_family="Arial"))

    # Display structure below LED
    disp_y = led_y + led_h + mm(50)
    disp_h = mm(600)
    dwg.add(dwg.rect(insert=(bay1_x+mm(200), disp_y), size=(bay1_w-mm(400), disp_h),
                      fill="#E0FFE0", stroke="green", stroke_width=1.5))
    dwg.add(dwg.text("展示台 / 陳列區", insert=(bay1_x+bay1_w/2, disp_y+disp_h/2),
                     text_anchor="middle", font_size=10, fill="green", font_family="Arial"))

    # Bay 2 - Corridor/Passage (1500mm)
    bay2_x = x0 + mm(5450)
    bay2_w = mm(1500)
    dwg.add(dwg.rect(insert=(bay2_x, y0+beam_h), size=(bay2_w, total_h-beam_h),
                      fill="#FFFFE0", stroke="#999900", stroke_width=1))
    dwg.add(dwg.text("通道", insert=(bay2_x+bay2_w/2, y0+beam_h+total_h/3),
                     text_anchor="middle", font_size=12, fill="#999900", font_family="Arial"))
    dwg.add(dwg.text("1500mm", insert=(bay2_x+bay2_w/2, y0+beam_h+total_h/3+20),
                     text_anchor="middle", font_size=10, fill="#999900", font_family="Arial"))

    # Bay 3 - Right Exhibition Area (5850mm)
    bay3_x = x0 + mm(5450+1500) + col_w
    bay3_w = mm(5850) - col_w

    # LED screens - right side (smaller)
    led2_x = bay3_x + mm(200)
    led2_w = mm(2500)
    led2_h = mm(2000)
    dwg.add(dwg.rect(insert=(led2_x, y0+beam_h+mm(200)), size=(led2_w, led2_h),
                      fill="#FFDDDD", stroke="red", stroke_width=1.5, rx=3))
    dwg.add(dwg.text("LED屏幕", insert=(led2_x+led2_w/2, y0+beam_h+mm(200)+led2_h/2),
                     text_anchor="middle", font_size=10, fill="red", font_family="Arial"))
    dwg.add(dwg.text("1.36m x 2.5m", insert=(led2_x+led2_w/2, y0+beam_h+mm(200)+led2_h/2+15),
                     text_anchor="middle", font_size=9, fill="#CC0000", font_family="Arial"))

    # Wooden structure panels
    wood_x = led2_x + led2_w + mm(200)
    wood_w = mm(1800)
    wood_h = mm(2000)
    dwg.add(dwg.rect(insert=(wood_x, y0+beam_h+mm(200)), size=(wood_w, wood_h),
                      fill="#E8DCC8", stroke="#8B6914", stroke_width=1.5, rx=2))
    # Wood grain lines
    for i in range(0, int(wood_w), 15):
        if (i // 15) % 2 == 0:
            dwg.add(dwg.line(start=(wood_x+i, y0+beam_h+mm(200)),
                              end=(wood_x+i, y0+beam_h+mm(200)+wood_h),
                              stroke="#D4C4A8", stroke_width=0.5))
    dwg.add(dwg.text("木質造型結構", insert=(wood_x+wood_w/2, y0+beam_h+mm(200)+wood_h/2-10),
                     text_anchor="middle", font_size=11, font_weight="bold", fill="#8B6914", font_family="Arial"))
    dwg.add(dwg.text("烤漆", insert=(wood_x+wood_w/2, y0+beam_h+mm(200)+wood_h/2+10),
                     text_anchor="middle", font_size=9, fill="#8B6914", font_family="Arial"))

    # Bottom platforms
    bot_y = y0 + total_h - mm(300)
    dwg.add(dwg.rect(insert=(x0+mm(200), bot_y), size=(total_w-mm(400), mm(300)),
                      fill="#E0E0E0", stroke="black", stroke_width=1))
    dwg.add(dwg.text("地台 / 基座", insert=(x0+total_w/2, bot_y+mm(150)),
                     text_anchor="middle", font_size=10, font_family="Arial"))

    # Overall height annotation
    h_label_x = x0 + total_w + 30
    dwg.add(dwg.line(start=(h_label_x, y0), end=(h_label_x, y0+total_h),
                      stroke="black", stroke_width=1))
    dwg.add(dwg.line(start=(h_label_x-5, y0), end=(h_label_x+5, y0), stroke="black", stroke_width=1))
    dwg.add(dwg.line(start=(h_label_x-5, y0+total_h), end=(h_label_x+5, y0+total_h),
                      stroke="black", stroke_width=1))
    dwg.add(dwg.text("4000mm", insert=(h_label_x+15, y0+total_h/2),
                     font_size=10, font_family="Arial"))

    # Section labels on top
    dwg.add(dwg.text("Section A", insert=(x0+mm(5450)/2, y0-8),
                     text_anchor="middle", font_size=9, font_family="Arial"))
    dwg.add(dwg.text("Section B/C/D", insert=(x0+mm(5450)+mm(1500)+mm(5850)/2, y0-8),
                     text_anchor="middle", font_size=9, font_family="Arial"))

    dwg.save()
    print(f"Created: {os.path.join(OUTPUT_DIR, 'ITEM02_正立面圖.svg')}")

def create_diagram_03_led_screens():
    """Item 03: LED屏幕配置圖 - LED Screen Configuration"""
    dwg = svgwrite.Drawing(os.path.join(OUTPUT_DIR, "ITEM03_LED屏幕配置圖.svg"),
                           size=("700px", "500px"))

    dwg.add(dwg.text("ITEM 03 — LED 屏幕配置圖 (1:50)",
                     insert=(350, 30), text_anchor="middle",
                     font_size=18, font_weight="bold", font_family="Arial"))

    scale = 0.08  # px per mm

    # LED Panel A - Main (7.57m x 2.5m)
    x0, y0 = 80, 80
    wa, ha = 7570 * scale, 2500 * scale

    dwg.add(dwg.rect(insert=(x0, y0), size=(wa, ha),
                      fill="#FFE0E0", stroke="red", stroke_width=2, rx=5))
    dwg.add(dwg.text("LED 屏幕 A (主屏)", insert=(x0+wa/2, y0+30),
                     text_anchor="middle", font_size=12, font_weight="bold", fill="#CC0000", font_family="Arial"))
    dwg.add(dwg.text("7,570mm (寬) × 2,500mm (高)", insert=(x0+wa/2, y0+ha/2),
                     text_anchor="middle", font_size=11, fill="#CC0000", font_family="Arial"))
    dwg.add(dwg.text("LED-RRB-EE 274", insert=(x0+wa/2, y0+ha/2+20),
                     text_anchor="middle", font_size=9, fill="#CC0000", font_family="Arial"))

    # Dimension arrows for A
    dwg.add(dwg.line(start=(x0, y0+ha+5), end=(x0+wa, y0+ha+5), stroke="red", stroke_width=1))
    dwg.add(dwg.text("7570mm", insert=(x0+wa/2, y0+ha+18),
                     text_anchor="middle", font_size=10, fill="red", font_family="Arial"))
    dwg.add(dwg.line(start=(x0-5, y0), end=(x0-5, y0+ha), stroke="red", stroke_width=1))
    dwg.add(dwg.text("2500mm", insert=(x0-25, y0+ha/2),
                     text_anchor="middle", font_size=10, fill="red", font_family="Arial"))

    # LED Panel B - Right (1.36m x 2.5m)
    x1, y1 = x0 + wa + 80, y0 + ha - 2000 * scale
    wb, hb = 1367 * scale, 2500 * scale

    dwg.add(dwg.rect(insert=(x1, y1), size=(wb, hb),
                      fill="#FFDDEE", stroke="#CC0066", stroke_width=2, rx=5))
    dwg.add(dwg.text("LED 屏幕 B", insert=(x1+wb/2, y1+30),
                     text_anchor="middle", font_size=12, font_weight="bold", fill="#CC0066", font_family="Arial"))
    dwg.add(dwg.text("1,367mm (寬) × 2,500mm (高)", insert=(x1+wb/2, y1+hb/2),
                     text_anchor="middle", font_size=11, fill="#CC0066", font_family="Arial"))
    dwg.add(dwg.text("LED-RRB-EE 分屏", insert=(x1+wb/2, y1+hb/2+20),
                     text_anchor="middle", font_size=9, fill="#CC0066", font_family="Arial"))

    # Specs box
    sx, sy = 80, y0 + ha + 80
    dwg.add(dwg.rect(insert=(sx, sy), size=(550, 130),
                      fill="#F5F5F5", stroke="#999", stroke_width=1, rx=5))
    dwg.add(dwg.text("技術規格：", insert=(sx+15, sy+25),
                     font_size=12, font_weight="bold", font_family="Arial"))
    specs = [
        "• 類型：LED顯示屏（室內型）",
        "• 分辨率：P2.5 / P3 規格",
        "• 亮度：≥1200cd/m²",
        "• 安裝方式：嵌入式安裝於結構框架",
        "• 控制系統：同步播放系統",
        "• 電源：AC 220V 50Hz"
    ]
    for i, spec in enumerate(specs):
        dwg.add(dwg.text(spec, insert=(sx+15, sy+50+i*18),
                         font_size=10, font_family="Arial"))

    # Notes
    nx, ny = 80, sy + 160
    dwg.add(dwg.text("備註：LED 屏幕 A（主屏）面積約 18.93m²，屏幕 B 面積約 3.42m²",
                     insert=(nx, ny), font_size=10, font_family="Arial"))

    dwg.save()
    print(f"Created: {os.path.join(OUTPUT_DIR, 'ITEM03_LED屏幕配置圖.svg')}")

def create_diagram_04_section_a():
    """Item 04: 剖面圖A - SEC1"""
    dwg = svgwrite.Drawing(os.path.join(OUTPUT_DIR, "ITEM04_剖面圖A_SEC1.svg"),
                           size=("700px", "900px"))

    dwg.add(dwg.text("ITEM 04 — 剖面圖 A SECTION A-A (1:50)",
                     insert=(350, 30), text_anchor="middle",
                     font_size=18, font_weight="bold", font_family="Arial"))

    scale = 0.12
    x0, y0 = 200, 100

    def mm(val): return val * scale

    h_total = mm(4000)
    w_total = mm(5450)

    # Ground line
    ground_y = y0 + h_total
    dwg.add(dwg.line(start=(x0-50, ground_y), end=(x0+w_total+50, ground_y),
                      stroke="black", stroke_width=3))
    dwg.add(dwg.text("地面", insert=(x0-30, ground_y+5),
                     text_anchor="end", font_size=10, font_family="Arial"))

    # Floor platform
    plat_h = mm(200)
    dwg.add(dwg.rect(insert=(x0, ground_y-plat_h), size=(w_total, plat_h),
                      fill="#D0D0D0", stroke="black", stroke_width=1))
    dwg.add(dwg.text("地台基座", insert=(x0+w_total/2, ground_y-plat_h/2),
                     text_anchor="middle", font_size=9, font_family="Arial"))

    # Main structure - vertical columns
    col_w = mm(80)
    col_positions = [x0, x0+w_total-col_w]
    for cx in col_positions:
        dwg.add(dwg.rect(insert=(cx, y0), size=(col_w, ground_y-plat_h-y0),
                          fill="#CCC", stroke="black", stroke_width=1.5))

    # Cross beam at top
    beam_h = mm(300)
    dwg.add(dwg.rect(insert=(x0, y0), size=(w_total, beam_h),
                      fill="#BBB", stroke="black", stroke_width=1.5))
    dwg.add(dwg.text("頂部橫樑", insert=(x0+w_total/2, y0+beam_h/2),
                     text_anchor="middle", font_size=9, font_family="Arial"))

    # LED Screen in section
    led_x = x0 + mm(400)
    led_y = y0 + beam_h + mm(100)
    led_w = mm(3700)
    led_th = mm(80)  # thickness
    dwg.add(dwg.rect(insert=(led_x, led_y), size=(led_w, led_th),
                      fill="#FF8888", stroke="red", stroke_width=1.5))
    dwg.add(dwg.text("LED 屏幕 (厚80mm)", insert=(led_x+led_w/2, led_y+led_th/2),
                     text_anchor="middle", font_size=9, fill="red", font_family="Arial"))

    # Support structure behind LED
    supp_x = led_x
    supp_y = led_y + led_th
    supp_w = led_w
    supp_h = mm(80)
    dwg.add(dwg.rect(insert=(supp_x, supp_y), size=(supp_w, supp_h),
                      fill="#E0E0E0", stroke="#666", stroke_width=1))
    dwg.add(dwg.text("支撐結構", insert=(supp_x+supp_w/2, supp_y+supp_h/2),
                     text_anchor="middle", font_size=8, font_family="Arial"))

    # Display shelf
    shelf_y = supp_y + supp_h + mm(200)
    shelf_h = mm(50)
    dwg.add(dwg.rect(insert=(x0+mm(300), shelf_y), size=(w_total-mm(600), shelf_h),
                      fill="#C8A96E", stroke="#8B6914", stroke_width=1))
    dwg.add(dwg.text("展示層板 (木質)", insert=(x0+w_total/2, shelf_y+shelf_h/2),
                     text_anchor="middle", font_size=9, fill="#8B6914", font_family="Arial"))

    # Lower display platform
    lower_y = ground_y - plat_h - mm(300)
    lower_h = mm(100)
    dwg.add(dwg.rect(insert=(x0+mm(200), lower_y), size=(w_total-mm(400), lower_h),
                      fill="#C8A96E", stroke="#8B6914", stroke_width=1))
    dwg.add(dwg.text("底部展示台", insert=(x0+w_total/2, lower_y+lower_h/2),
                     text_anchor="middle", font_size=9, fill="#8B6914", font_family="Arial"))

    # Overall dimensions
    # Height
    dim_x = x0 + w_total + 30
    dwg.add(dwg.line(start=(dim_x, y0), end=(dim_x, ground_y), stroke="black", stroke_width=1))
    dwg.add(dwg.text("4000mm", insert=(dim_x+15, y0+h_total/2),
                     font_size=10, font_family="Arial"))

    # Width
    dim_y = ground_y + 30
    dwg.add(dwg.line(start=(x0, dim_y), end=(x0+w_total, dim_y), stroke="black", stroke_width=1))
    dwg.add(dwg.text("5450mm", insert=(x0+w_total/2, dim_y+15),
                     text_anchor="middle", font_size=10, font_family="Arial"))

    # Section label
    dwg.add(dwg.text("A", insert=(x0+w_total/2, y0-10),
                     text_anchor="middle", font_size=14, font_weight="bold", font_family="Arial"))
    dwg.add(dwg.text("A", insert=(x0+w_total/2, ground_y+50),
                     text_anchor="middle", font_size=14, font_weight="bold", font_family="Arial"))

    dwg.save()
    print(f"Created: {os.path.join(OUTPUT_DIR, 'ITEM04_剖面圖A_SEC1.svg')}")

def create_diagram_05_wooden_structure():
    """Item 05: 木質造型結構詳圖"""
    dwg = svgwrite.Drawing(os.path.join(OUTPUT_DIR, "ITEM05_木質造型結構詳圖.svg"),
                           size=("700px", "600px"))

    dwg.add(dwg.text("ITEM 05 — 木質造型結構 DETAIL (1:30)",
                     insert=(350, 30), text_anchor="middle",
                     font_size=18, font_weight="bold", font_family="Arial"))

    scale = 0.15
    x0, y0 = 200, 100

    def mm(val): return val * scale

    # Main wooden panel
    pw = mm(1800)
    ph = mm(3500)

    dwg.add(dwg.rect(insert=(x0, y0), size=(pw, ph),
                      fill="#F0E6D3", stroke="#8B6914", stroke_width=2, rx=3))

    # Wood grain texture
    for i in range(0, int(ph), 25):
        dwg.add(dwg.line(start=(x0+5, y0+i), end=(x0+pw-5, y0+i),
                          stroke="#E0D4BC", stroke_width=0.5))

    # Panel divisions
    panel_count = 4
    panel_w = pw / panel_count
    for i in range(1, panel_count):
        px = x0 + panel_w * i
        dwg.add(dwg.line(start=(px, y0+5), end=(px, y0+ph-5),
                          stroke="#C8B896", stroke_width=1))

    # Decorative elements
    for i, (label, color) in enumerate([("雕刻紋理區", "#D4A76A"), ("烤漆面層", "#C8B896"),
                                          ("LED開槽", "#FF8888"), ("掛畫區", "#A8D8A8")]):
        ey = y0 + ph / 4 * i + ph / 8
        ew = pw * 0.7
        ex = x0 + (pw - ew) / 2
        eh = ph / 6
        if "LED" in label:
            dwg.add(dwg.rect(insert=(ex, ey-eh/2), size=(ew, eh),
                              fill="#FFCCCC", stroke="red", stroke_width=1.5))
        elif "掛畫" in label:
            dwg.add(dwg.rect(insert=(ex, ey-eh/2), size=(ew, eh),
                              fill="#D0F0D0", stroke="green", stroke_width=1.5))
        else:
            dwg.add(dwg.rect(insert=(ex, ey-eh/2), size=(ew, eh),
                              fill=color, stroke="#8B6914", stroke_width=1))
        dwg.add(dwg.text(label, insert=(ex+ew/2, ey+3),
                         text_anchor="middle", font_size=10, font_weight="bold",
                         fill="#5C4014" if "LED" not in label and "掛畫" not in label else "white",
                         font_family="Arial"))

    # Dimension annotations
    dwg.add(dwg.text("1800mm", insert=(x0+pw/2, y0+ph+20),
                     text_anchor="middle", font_size=10, font_family="Arial"))
    dwg.add(dwg.line(start=(x0, y0+ph+5), end=(x0+pw, y0+ph+5), stroke="black", stroke_width=1))

    dwg.add(dwg.text("3500mm", insert=(x0-30, y0+ph/2),
                     text_anchor="middle", font_size=10, font_family="Arial"))

    # Cross-section detail (right side)
    dx = x0 + pw + 80
    dwg.add(dwg.text("剖面詳圖", insert=(dx+60, y0), font_size=11, font_weight="bold", font_family="Arial"))

    # Section layers
    layers = [
        ("烤漆面層 (0.5mm)", 10, "#D4C4A8"),
        ("木質基板 (18mm)", 30, "#C8B060"),
        ("龍骨框架 (50mm)", 40, "#A08850"),
        ("隔音層 (10mm)", 15, "#D0D0D0"),
        ("安裝龍骨 (50mm)", 40, "#888060"),
    ]

    ly = y0 + 30
    for label, thick, color in layers:
        dwg.add(dwg.rect(insert=(dx, ly), size=(120, thick),
                          fill=color, stroke="#666", stroke_width=1))
        dwg.add(dwg.text(label, insert=(dx+130, ly+thick/2+3),
                         font_size=8, font_family="Arial"))
        ly += thick

    dwg.add(dwg.text("總厚度: 168mm", insert=(dx+60, ly+15),
                     text_anchor="middle", font_size=9, font_weight="bold", font_family="Arial"))

    # Notes
    ny = y0 + ph + 60
    dwg.add(dwg.text("備註：", insert=(x0, ny), font_size=11, font_weight="bold", font_family="Arial"))
    dwg.add(dwg.text("1. 材質：多層板 + 烤漆面層", insert=(x0+15, ny+20), font_size=10, font_family="Arial"))
    dwg.add(dwg.text("2. 局部開槽嵌入LED屏幕", insert=(x0+15, ny+38), font_size=10, font_family="Arial"))
    dwg.add(dwg.text("3. 可掛畫及安裝展示配件", insert=(x0+15, ny+56), font_size=10, font_family="Arial"))
    dwg.add(dwg.text("4. 高度 3.5m，含頂部安裝件", insert=(x0+15, ny+74), font_size=10, font_family="Arial"))

    dwg.save()
    print(f"Created: {os.path.join(OUTPUT_DIR, 'ITEM05_木質造型結構詳圖.svg')}")

def create_diagram_06_truss_stage():
    """Item 06: 框架舞台 TRUSS 詳圖"""
    dwg = svgwrite.Drawing(os.path.join(OUTPUT_DIR, "ITEM06_框架舞台詳圖.svg"),
                           size=("700px", "500px"))

    dwg.add(dwg.text("ITEM 06 — 框架舞台 TRUSS 結構詳圖",
                     insert=(350, 30), text_anchor="middle",
                     font_size=18, font_weight="bold", font_family="Arial"))

    scale = 0.15
    x0, y0 = 150, 80

    def mm(val): return val * scale

    # TRUSS frame - side view
    truss_w = mm(3500)
    truss_h = mm(200)

    # Draw TRUSS front view
    dwg.add(dwg.rect(insert=(x0, y0), size=(truss_w, truss_h),
                      fill="#E8E8E8", stroke="#333", stroke_width=2, rx=5))

    # TRUSS internal pattern
    for i in range(0, int(truss_w), 25):
        dwg.add(dwg.line(start=(x0+i, y0+5), end=(x0+i+12, y0+truss_h-5),
                          stroke="#999", stroke_width=0.8))
        dwg.add(dwg.line(start=(x0+i+12, y0+5), end=(x0+i, y0+truss_h-5),
                          stroke="#999", stroke_width=0.8))

    dwg.add(dwg.text("TRUSS 主框架 200mm (H) × 200mm (W)", insert=(x0+truss_w/2, y0+truss_h/2),
                     text_anchor="middle", font_size=11, font_weight="bold", font_family="Arial"))

    # TRUSS span
    dwg.add(dwg.text("3500mm", insert=(x0+truss_w/2, y0+truss_h+20),
                     text_anchor="middle", font_size=10, font_family="Arial"))
    dwg.add(dwg.line(start=(x0, y0+truss_h+5), end=(x0+truss_w, y0+truss_h+5), stroke="black", stroke_width=1))

    # Support legs
    leg_y = y0 + truss_h + 40
    leg_h = mm(2500)

    for lx in [x0+mm(200), x0+truss_w-mm(200), x0+truss_w/2]:
        dwg.add(dwg.rect(insert=(lx-mm(25), leg_y), size=(mm(50), leg_h),
                          fill="#D0D0D0", stroke="#666", stroke_width=1.5))

    dwg.add(dwg.text("支撐立柱 200×200mm", insert=(x0+truss_w/2, leg_y+leg_h/2),
                     text_anchor="middle", font_size=10, font_family="Arial"))

    # Overall stage diagram (below)
    stage_y = y0 + 320
    stage_w = mm(5000)
    stage_h = mm(300)

    dwg.add(dwg.rect(insert=(x0-stage_w/2+truss_w/2, stage_y), size=(stage_w, stage_h),
                      fill="#E0E0E0", stroke="#333", stroke_width=2, rx=3))
    dwg.add(dwg.text("舞 台 台 面 (STAGE DECK)", insert=(x0+truss_w/2, stage_y+stage_h/2),
                     text_anchor="middle", font_size=12, font_weight="bold", font_family="Arial"))

    dwg.add(dwg.text("5000mm", insert=(x0+truss_w/2, stage_y+stage_h+20),
                     text_anchor="middle", font_size=10, font_family="Arial"))

    # Notes
    ny = stage_y + stage_h + 50
    dwg.add(dwg.text("備註：", insert=(x0-100, ny), font_size=11, font_weight="bold", font_family="Arial"))
    dwg.add(dwg.text("1. TRUSS 規格：200mm 標準鋁合金桁架", insert=(x0-85, ny+20), font_size=10, font_family="Arial"))
    dwg.add(dwg.text("2. 舞台高度 3.5m（TRUSS 頂部至地面）", insert=(x0-85, ny+38), font_size=10, font_family="Arial"))
    dwg.add(dwg.text("3. 承重：≥500kg/m²", insert=(x0-85, ny+56), font_size=10, font_family="Arial"))
    dwg.add(dwg.text("4. 含 LED 屏幕安裝結構", insert=(x0-85, ny+74), font_size=10, font_family="Arial"))

    dwg.save()
    print(f"Created: {os.path.join(OUTPUT_DIR, 'ITEM06_框架舞台詳圖.svg')}")

def create_diagram_07_display_platforms():
    """Item 07: 展台與人台配置圖"""
    dwg = svgwrite.Drawing(os.path.join(OUTPUT_DIR, "ITEM07_展台與人台配置圖.svg"),
                           size=("800px", "500px"))

    dwg.add(dwg.text("ITEM 07 — 展台與模特人台配置圖 (1:20)",
                     insert=(400, 30), text_anchor="middle",
                     font_size=18, font_weight="bold", font_family="Arial"))

    scale = 0.20
    x0, y0 = 80, 80

    def mm(val): return val * scale

    # Platform 1 - Main display (1200x400)
    px, py, pw, ph = x0, y0, mm(1200), mm(400)
    dwg.add(dwg.rect(insert=(px, py), size=(pw, ph),
                      fill="#E8FFE8", stroke="#006600", stroke_width=2, rx=5))
    dwg.add(dwg.text("展台 1 (主展台)", insert=(px+pw/2, py+ph/2-8),
                     text_anchor="middle", font_size=11, font_weight="bold",
                     fill="#006600", font_family="Arial"))
    dwg.add(dwg.text("1200×400×100mm", insert=(px+pw/2, py+ph/2+12),
                     text_anchor="middle", font_size=9, fill="#006600", font_family="Arial"))

    # Mannequin on platform 1
    mnq_x = px + pw/2 - mm(50)
    mnq_y = py - mm(1500)
    # Mannequin body
    dwg.add(dwg.circle(center=(mnq_x+mm(50), mnq_y+mm(100)), r=mm(100),
                        fill="#FFD5D5", stroke="#CC6666", stroke_width=1.5))
    dwg.add(dwg.rect(insert=(mnq_x+mm(10), mnq_y+mm(200)), size=(mm(80), mm(500)),
                      fill="#FFD5D5", stroke="#CC6666", stroke_width=1.5, rx=10))
    dwg.add(dwg.text("模特人台", insert=(mnq_x+mm(50), mnq_y+mm(450)),
                     text_anchor="middle", font_size=9, fill="#CC6666", font_family="Arial"))

    # Platform 2
    px2 = x0 + pw + mm(200)
    pw2 = mm(1000)
    dwg.add(dwg.rect(insert=(px2, py), size=(pw2, ph),
                      fill="#E8FFE8", stroke="#006600", stroke_width=2, rx=5))
    dwg.add(dwg.text("展台 2", insert=(px2+pw2/2, py+ph/2-8),
                     text_anchor="middle", font_size=11, font_weight="bold",
                     fill="#006600", font_family="Arial"))
    dwg.add(dwg.text("1000×400×100mm", insert=(px2+pw2/2, py+ph/2+12),
                     text_anchor="middle", font_size=9, fill="#006600", font_family="Arial"))

    # Mannequin 2
    mnq2_x = px2 + pw2/2 - mm(50)
    dwg.add(dwg.circle(center=(mnq2_x+mm(50), mnq_y+mm(100)), r=mm(100),
                        fill="#FFD5D5", stroke="#CC6666", stroke_width=1.5))
    dwg.add(dwg.rect(insert=(mnq2_x+mm(10), mnq_y+mm(200)), size=(mm(80), mm(500)),
                      fill="#FFD5D5", stroke="#CC6666", stroke_width=1.5, rx=10))
    dwg.add(dwg.text("模特人台", insert=(mnq2_x+mm(50), mnq_y+mm(450)),
                     text_anchor="middle", font_size=9, fill="#CC6666", font_family="Arial"))

    # Platform 3 - smaller
    px3 = px2 + pw2 + mm(200)
    pw3 = mm(800)
    dwg.add(dwg.rect(insert=(px3, py), size=(pw3, ph),
                      fill="#E8FFE8", stroke="#006600", stroke_width=2, rx=5))
    dwg.add(dwg.text("展台 3", insert=(px3+pw3/2, py+ph/2-8),
                     text_anchor="middle", font_size=11, font_weight="bold",
                     fill="#006600", font_family="Arial"))
    dwg.add(dwg.text("800×400×100mm", insert=(px3+pw3/2, py+ph/2+12),
                     text_anchor="middle", font_size=9, fill="#006600", font_family="Arial"))

    # Wall mounting detail (wooden结构 behind)
    wall_x = x0 - mm(50)
    wall_w = mm(50)
    wall_y = mnq_y - mm(50)
    wall_h = py + ph - wall_y + mm(50)
    dwg.add(dwg.rect(insert=(wall_x, wall_y), size=(wall_w, wall_h),
                      fill="#E8DCC8", stroke="#8B6914", stroke_width=1))
    dwg.add(dwg.text("木質背板", insert=(wall_x-25, wall_y+wall_h/2),
                     text_anchor="middle", font_size=9, fill="#8B6914", font_family="Arial"))

    # Section B detail callout
    dwg.add(dwg.text("B", insert=(x0+pw+pw2+pw3+mm(300), py-mm(200)),
                     font_size=14, font_weight="bold", font_family="Arial"))
    dwg.add(dwg.circle(center=(x0+pw+pw2+pw3+mm(300), py-mm(200)), r=8,
                        fill="none", stroke="black", stroke_width=1.5))

    dwg.save()
    print(f"Created: {os.path.join(OUTPUT_DIR, 'ITEM07_展台與人台配置圖.svg')}")

def create_diagram_08_section_bcd():
    """Item 08-10: 剖面圖 B/C/D - SEC2/3/4"""
    dwg = svgwrite.Drawing(os.path.join(OUTPUT_DIR, "ITEM08_剖面圖BCD_SEC2-4.svg"),
                           size=("900px", "700px"))

    dwg.add(dwg.text("ITEM 08-10 — 剖面圖 B/C/D SECTIONS (1:50)",
                     insert=(450, 30), text_anchor="middle",
                     font_size=18, font_weight="bold", font_family="Arial"))

    scale = 0.08
    x0, y0 = 80, 80

    def mm(val): return val * scale

    # Three sections side by side
    sections = [
        {"name": "SEC-B 剖面 B-B (通道)", "w": 2500, "h": 4000, "x": 0,
         "label": "通道上方結構\n1500mm寬通道\n兩側LED屏幕"},
        {"name": "SEC-C 剖面 C-C", "w": 3000, "h": 4000, "x": 2800,
         "label": "展示區剖面\n木質結構+LED\n高度3500mm"},
        {"name": "SEC-D 剖面 D-D", "w": 2500, "h": 4000, "x": 6100,
         "label": "展示區剖面\n雙面展板\n高度4000mm"},
    ]

    for sec in sections:
        sx = x0 + mm(sec["x"])
        sy = y0
        sw = mm(sec["w"])
        sh = mm(sec["h"])

        dwg.add(dwg.rect(insert=(sx, sy), size=(sw, sh),
                          fill="#FAFAFA", stroke="black", stroke_width=2))

        # Title
        dwg.add(dwg.text(sec["name"], insert=(sx+sw/2, sy-10),
                         text_anchor="middle", font_size=11, font_weight="bold", font_family="Arial"))

        # Ground
        dwg.add(dwg.line(start=(sx, sy+sh), end=(sx+sw, sy+sh), stroke="black", stroke_width=3))
        dwg.add(dwg.text("地面", insert=(sx+sw/2, sy+sh+15),
                         text_anchor="middle", font_size=9, font_family="Arial"))

        # Section specific content
        if "SEC-B" in sec["name"]:
            # Passage section - two side walls
            col_w = mm(100)
            dwg.add(dwg.rect(insert=(sx, sy), size=(col_w, sh),
                              fill="#CCC", stroke="black", stroke_width=1))
            dwg.add(dwg.rect(insert=(sx+sw-col_w, sy), size=(col_w, sh),
                              fill="#CCC", stroke="black", stroke_width=1))
            # Top beam
            dwg.add(dwg.rect(insert=(sx, sy), size=(sw, mm(300)),
                              fill="#BBB", stroke="black", stroke_width=1))
            dwg.add(dwg.text("頂樑", insert=(sx+sw/2, sy+mm(150)),
                             text_anchor="middle", font_size=9, font_family="Arial"))
            # LED on walls
            dwg.add(dwg.rect(insert=(sx+col_w, sy+mm(400)), size=(mm(80), mm(2000)),
                              fill="#FFCCCC", stroke="red", stroke_width=1))
            dwg.add(dwg.rect(insert=(sx+sw-col_w-mm(80), sy+mm(400)), size=(mm(80), mm(2000)),
                              fill="#FFCCCC", stroke="red", stroke_width=1))
            dwg.add(dwg.text("LED", insert=(sx+col_w+mm(40), sy+mm(1400)),
                             text_anchor="middle", font_size=8, fill="red", font_family="Arial"))
            dwg.add(dwg.text("LED", insert=(sx+sw-col_w-mm(40), sy+mm(1400)),
                             text_anchor="middle", font_size=8, fill="red", font_family="Arial"))

        elif "SEC-C" in sec["name"]:
            # Display section
            wood_w = mm(100)
            wood_x = sx + sw/2 - mm(150)
            dwg.add(dwg.rect(insert=(wood_x, sy+mm(200)), size=(mm(300), sh-mm(200)),
                              fill="#E8DCC8", stroke="#8B6914", stroke_width=1.5))
            # Wood texture
            for wi in range(0, 300, 20):
                dwg.add(dwg.line(start=(wood_x+wi*scale, sy+mm(200)),
                                  end=(wood_x+wi*scale, sy+sh-mm(200)),
                                  stroke="#D4C4A8", stroke_width=0.5))
            dwg.add(dwg.text("木質結構", insert=(wood_x+mm(150), sy+sh/2),
                             text_anchor="middle", font_size=9, fill="#8B6914", font_family="Arial"))
            # LED screen on one side
            dwg.add(dwg.rect(insert=(sx+mm(50), sy+mm(400)), size=(mm(60), mm(2000)),
                              fill="#FFCCCC", stroke="red", stroke_width=1))
            dwg.add(dwg.text("LED", insert=(sx+mm(80), sy+mm(1400)),
                             text_anchor="middle", font_size=8, fill="red", font_family="Arial"))

        elif "SEC-D" in sec["name"]:
            # Double-sided panel
            panel_w = mm(80)
            panel_x = sx + sw/2 - panel_w/2
            dwg.add(dwg.rect(insert=(panel_x, sy+mm(200)), size=(panel_w, sh-mm(200)),
                              fill="#E8E0D0", stroke="#8B6914", stroke_width=1.5))
            dwg.add(dwg.text("雙面展板", insert=(panel_x+panel_w/2, sy+sh/2),
                             text_anchor="middle", font_size=9, fill="#8B6914", font_family="Arial"))
            # Display shelves
            for shelf_i in range(2):
                sy2 = sy + mm(600) + shelf_i * mm(1200)
                dwg.add(dwg.rect(insert=(sx+mm(200), sy2), size=(panel_x-sx-mm(200), mm(30)),
                                  fill="#C8A96E", stroke="#8B6914", stroke_width=1))
                dwg.add(dwg.rect(insert=(panel_x+panel_w, sy2), size=(sx+sw-panel_x-panel_w-mm(200), mm(30)),
                                  fill="#C8A96E", stroke="#8B6914", stroke_width=1))

        # Center description
        dwg.add(dwg.text(sec["label"], insert=(sx+sw/2, sy+sh/2+mm(200)),
                         text_anchor="middle", font_size=9, fill="#666", font_family="Arial"))

    dwg.save()
    print(f"Created: {os.path.join(OUTPUT_DIR, 'ITEM08_剖面圖BCD_SEC2-4.svg')}")

# Generate all diagrams
create_diagram_01_plan_layout()
create_diagram_02_front_elevation()
create_diagram_03_led_screens()
create_diagram_04_section_a()
create_diagram_05_wooden_structure()
create_diagram_06_truss_stage()
create_diagram_07_display_platforms()
create_diagram_08_section_bcd()

print(f"\n=== All diagrams generated in: {OUTPUT_DIR} ===")
print("Items:")
for f in sorted(os.listdir(OUTPUT_DIR)):
    if f.endswith(".svg"):
        print(f"  📐 {f}")
