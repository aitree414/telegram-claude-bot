"""
Polymarket CLOB API Login Script
Run: ./venv_poly/bin/python3 polymarket_login.py

需要先填入 .env:
  POLY_PRIVATE_KEY=0x你的私鑰
"""
import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

load_dotenv()

PRIVATE_KEY = os.getenv("POLY_PRIVATE_KEY")
if not PRIVATE_KEY:
    print("錯誤：請在 .env 加入 POLY_PRIVATE_KEY=0x你的私鑰")
    exit(1)

HOST = "https://clob.polymarket.com"

print("連接 Polymarket CLOB...")
client = ClobClient(host=HOST, key=PRIVATE_KEY, chain_id=POLYGON)

print(f"錢包地址：{client.get_address()}")

# 生成 L2 API 憑證（第一次執行後存起來）
print("\n生成 API 憑證...")
creds = client.create_or_derive_api_creds()
print(f"API Key:        {creds.api_key}")
print(f"API Secret:     {creds.api_secret}")
print(f"API Passphrase: {creds.api_passphrase}")

print("\n請把以上三個值加入 .env：")
print(f"POLY_API_KEY={creds.api_key}")
print(f"POLY_API_SECRET={creds.api_secret}")
print(f"POLY_API_PASSPHRASE={creds.api_passphrase}")

# 測試：查詢開放市場
print("\n測試連線 - 查詢熱門市場...")
client_with_creds = ClobClient(
    host=HOST,
    key=PRIVATE_KEY,
    chain_id=POLYGON,
    creds=creds,
)
markets = client_with_creds.get_markets()
print(f"成功取得 {len(markets.get('data', []))} 個市場")
print("Login 成功！")
