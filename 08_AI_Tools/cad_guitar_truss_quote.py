"""
Zoe/Taiwan — Guitar Truss Quotation Generator
===============================================
Generates XLSX quotation matching 08 Collective format
for the Guitar Truss project.

Uses quotation_generator.py's sc() style.
"""

import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from importlib import import_module
qg = import_module("08_AI_Tools.quotation_generator")

DATA = {
    "project": "Zoe Taiwan — Guitar Truss 吉他造型 Truss 燈光架",
    "client": "Zoe / Taiwan",
    "date": "2026.06.25",
    "ref_no": "ZOE-GT-2026-001",
    "revision": "v1",
    "categories": [
        {
            "name": "A. Truss 結構材料",
            "items": [
                {"qty": 42, "unit": "M", "description": "Truss 主桿 Ø50×3mm 6061-T6 鋁合金圓管", "rate": 1200},
                {"qty": 65, "unit": "M", "description": "Truss 斜撐 Ø12×2mm 6061-T6 鋁合金圓管", "rate": 480},
                {"qty": 30, "unit": "PCS", "description": "T 型鋁合金壓鑄接頭 (配 M8 螺絲孔)", "rate": 350},
                {"qty": 16, "unit": "PCS", "description": "L 型鋁合金壓鑄接頭 (配 M8 螺絲孔)", "rate": 280},
                {"qty": 8, "unit": "PCS", "description": "X 型十字鋁合金壓鑄接頭 (四向連接)", "rate": 450},
                {"qty": 200, "unit": "PCS", "description": "M8×25 SUS304 不鏽鋼連接螺絲", "rate": 18},
                {"qty": 120, "unit": "PCS", "description": "M8 SUS304 彈簧墊圈", "rate": 5},
                {"qty": 2, "unit": "PCS", "description": "補強板 3mm 6061-T6 鋁板 (琴頭)", "rate": 1200},
                {"qty": 4, "unit": "PCS", "description": "補強斜撐 3mm 6061-T6 鋁板折彎 (琴頸接合)", "rate": 1500},
            ]
        },
        {
            "name": "B. 吊掛五金",
            "items": [
                {"qty": 6, "unit": "PCS", "description": "電動葫蘆 250kg 110V 含限位開關 + 緊急停止", "rate": 8500},
                {"qty": 6, "unit": "SET", "description": "鍍鋅鋼索 Ø6mm×5m 7×19 + PVC 保護套 + 鋁壓頭", "rate": 1800},
                {"qty": 6, "unit": "PCS", "description": "馬達吊掛板 10mm 鋼板 熱浸鍍鋅", "rate": 3200},
                {"qty": 12, "unit": "PCS", "description": "卸扣 Shackle 5/8\" 鍍鋅", "rate": 350},
                {"qty": 6, "unit": "PCS", "description": "防墜安全索 (二次保護)", "rate": 2800},
            ]
        },
        {
            "name": "C. 加工製作",
            "items": [
                {"qty": 1, "unit": "LOT", "description": "Truss 結構加工製作 (切割、焊接、組裝)", "rate": 85000},
                {"qty": 1, "unit": "LOT", "description": "表面處理 — 黑色靜電粉體塗裝 60-80μm 砂面", "rate": 45000},
                {"qty": 1, "unit": "LOT", "description": "吉他造形 Truss 彎管/成型加工", "rate": 35000},
                {"qty": 1, "unit": "LOT", "description": "焊接檢驗 (Class B 焊道 + 100% 目視檢查)", "rate": 18000},
            ]
        },
        {
            "name": "D. 現場安裝",
            "items": [
                {"qty": 12, "unit": "MAN-DAY", "description": "現場安裝 — 4 人 × 3 天 (含 Load-in/Assembly/Test)", "rate": 8000},
                {"qty": 1, "unit": "LOT", "description": "載重測試 (1.5 倍額定, 30 分鐘)", "rate": 15000},
                {"qty": 1, "unit": "LOT", "description": "現場管理及技術監督", "rate": 25000},
                {"qty": 1, "unit": "LOT", "description": "安裝工具、吊車租用、安全設備", "rate": 35000},
            ]
        },
        {
            "name": "E. 運輸物流",
            "items": [
                {"qty": 1, "unit": "LOT", "description": "結構件運輸 (工廠→場地)", "rate": 28000},
                {"qty": 1, "unit": "LOT", "description": "包裝保護 (EPE 泡棉 + 木箱)", "rate": 15000},
            ]
        },
        {
            "name": "F. 管理及雜項",
            "items": [
                {"qty": 1, "unit": "LOT", "description": "品管及文件費用", "rate": 12000},
                {"qty": 1, "unit": "LOT", "description": "保險 (施工 + 產品責任險)", "rate": 18000},
                {"qty": 1, "unit": "LOT", "description": "雜項及不可預見費", "rate": 20000},
            ]
        },
    ],
    "payment_terms": "50% 訂金 (Deposit upon order)\n30% 交貨前 (Before delivery)\n20% 安裝驗收後 (After installation & acceptance)",
    "validity": "30 days / 30 天"
}


if __name__ == "__main__":
    output_dir = "/Volumes/Apollo Sync Folder/08collective/Zoe/Taiwan/"
    out = os.path.join(output_dir, f"Zoe_Taiwan_Guitar_Truss_Quotation_v2.xlsx")

    qg.generate_quotation(DATA, out)
    print(f"✓ Quotation: {out}")
