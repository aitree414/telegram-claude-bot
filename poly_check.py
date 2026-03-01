"""Check wallet balance and Polymarket CLOB status."""
import os
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

load_dotenv()

client = ClobClient(
    host="https://clob.polymarket.com",
    key=os.getenv("POLY_PRIVATE_KEY"),
    chain_id=POLYGON,
    creds=type("C", (), {
        "api_key": os.getenv("POLY_API_KEY"),
        "api_secret": os.getenv("POLY_API_SECRET"),
        "api_passphrase": os.getenv("POLY_API_PASSPHRASE"),
    })(),
)

print(f"EOA 錢包地址：{client.get_address()}")

try:
    bal = client.get_balance()
    print(f"CLOB 餘額：{bal}")
except Exception as e:
    print(f"CLOB 餘額：{e}")

try:
    positions = client.get_positions()
    print(f"持倉數量：{len(positions)}")
except Exception as e:
    print(f"持倉：{e}")
