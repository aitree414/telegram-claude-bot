"""
Portfolio Dashboard + Daytrade Dashboard Server
Serves on port 8890 with auto-refresh.
"""
import json, logging, os, urllib.parse, urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DAYTRADE_FILE = BASE_DIR / "daytrade_sim.json"

# ── Wife Portfolio HTML (loaded from file) ─────────────────────────

WIFE_HTML_PATH = BASE_DIR / "web-apps" / "wife_portfolio.html"

def _load_wife_html() -> str:
    try:
        if WIFE_HTML_PATH.exists():
            return WIFE_HTML_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to load wife portfolio: %s", e)
    return "<html><body><h1>Error loading portfolio</h1></body></html>"

WIFE_HTML = _load_wife_html()

QUOTATION_HTML_PATH = BASE_DIR / "quotation_event.html"

def _load_quotation_html() -> str:
    try:
        if QUOTATION_HTML_PATH.exists():
            return QUOTATION_HTML_PATH.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to load quotation: %s", e)
    return "<html><body><h1>Error</h1></body></html>"

QUOTATION_HTML = _load_quotation_html()

# ── HTML Templates ─────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text()) if path.exists() else {}
    except Exception:
        return {}

def _load_daytrade_data() -> dict:
    """Load daytrade_sim.json and inject live prices."""
    raw = _load_json(DAYTRADE_FILE)
    if not raw:
        return {"error": "no data", "initial_capital": 100000, "cash": 100000}

    positions_raw = raw.get("positions", [])
    live_prices = _fetch_prices(list({p["symbol"] for p in positions_raw}))

    enriched = []
    for p in positions_raw:
        sym = p["symbol"]
        entry = float(p["entry_price_usd"])
        shares = int(p["shares"])
        live = live_prices.get(sym)
        if live and live > 0:
            cp = round(live, 2)
            upnl = round((live - entry) * shares, 2)
            upct = round((live - entry) / entry * 100, 2) if entry else 0
        else:
            cp = entry
            upnl = 0.0
            upct = 0.0
        enriched.append({
            "id": p["id"],
            "symbol": sym,
            "shares": shares,
            "entry_price_usd": entry,
            "entry_price_twd": round(entry * 33.0, 2),
            "entry_date": p.get("entry_date", ""),
            "entry_time": p.get("entry_time", ""),
            "note": p.get("note", ""),
            "current_price_usd": cp,
            "unrealized_pnl_usd": upnl,
            "unrealized_pnl_pct": upct,
        })

    return {
        "initial_capital": float(raw.get("initial_capital", 100000)),
        "cash": float(raw.get("cash", 100000)),
        "usd_twd_rate": float(raw.get("usd_twd_rate", 33.0)),
        "total_realized_pnl": float(raw.get("total_realized_pnl", 0.0)),
        "next_id": int(raw.get("next_id", 1)),
        "positions": enriched,
        "trade_history": raw.get("trade_history", []),
        "daily_pnl": raw.get("daily_pnl", {}),
    }

def _fetch_prices(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    try:
        import yfinance as yf
    except ImportError:
        return {}
    prices = {}
    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            h = t.history(period="2d")
            if h is not None and len(h) >= 1:
                prices[sym] = float(h["Close"].iloc[-1])
        except Exception:
            pass
    return prices


# ── TWSE Direct Price API ─────────────────────────────────────────────

import re as _re

def _fetch_twse_prices(codes: list[str]) -> dict[str, dict]:
    """Fetch live prices from TWSE/TPEx official API (no auth needed)."""
    if not codes:
        return {}

    # Group by exchange
    tse = []
    otc = []
    for c in codes:
        c = c.strip().upper().replace(".TW", "")
        if c == "TWD=X":
            continue  # skip forex
        tse.append(c)  # try TSE first, OTC fallback

    if not tse:
        return {}

    import urllib.request as _ur
    import json as _json

    result: dict[str, dict] = {}
    today = ""

    # Build query params: tse_2330.tw|tse_2317.tw (up to ~50 per call)
    def _query(ex_ch_list: list[str]) -> None:
        nonlocal today
        if not ex_ch_list:
            return
        ch_str = "|".join(ex_ch_list)
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={ch_str}"
        try:
            req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = _ur.urlopen(req, timeout=10)
            raw = resp.read().decode("utf-8")
            # JSONP: jsonpCallback({...})
            m = _re.search(r"\{.*\}", raw)
            if not m:
                return
            data = _json.loads(m.group(0))
            today = data.get("queryTime", {}).get("sysDate", "")
            for msg in data.get("msgArray", []):
                code = msg.get("c", "")
                if not code:
                    continue
                raw_z = msg.get("z", "-")
                raw_y = msg.get("y", "0")
                y_close = float(raw_y) if raw_y not in ("-", "") else 0
                if raw_z not in ("-", ""):
                    price = float(raw_z)
                else:
                    price = y_close
                # Calculate change from current vs yesterday close
                if y_close and price:
                    change_f = round(price - y_close, 2)
                    change_pct_f = round((price / y_close - 1) * 100, 2)
                else:
                    change_f = 0.0
                    change_pct_f = 0.0
                result[code] = {
                    "price": round(price, 2),
                    "change": change_f,
                    "change_pct": change_pct_f,
                    "date": today or "",
                    "source": "twse",
                }
        except Exception as e:
            logger.debug("TWSE fetch failed for %s: %s", "|".join(ex_ch_list), e)

    # Batch TSE stocks (up to 50 per call)
    tse_ch = [f"tse_{c}.tw" for c in tse]
    _query(tse_ch)

    # For codes not found in TSE, try OTC
    found = set(result.keys())
    missing = [c for c in tse if c not in found]
    if missing:
        otc_ch = [f"otc_{c}.tw" for c in missing]
        _query(otc_ch)

    # Fill in any unfetchable codes with zeros
    for c in codes:
        c = c.strip().upper().replace(".TW", "")
        if c not in result and c != "TWD=X":
            result[c] = {
                "price": 0,
                "change": 0,
                "change_pct": 0,
                "date": today,
                "source": "twse",
            }

    return result


# ── HTML Template ───────────────────────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>彭筱雅 台股投資組合</title>
    <style>
        /* ... existing styles ... */
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; }
        body { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); min-height: 100vh; padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        h1 { color: white; margin-bottom: 20px; }
        .error { color: #ef4444; text-align: center; padding: 40px; }
        .loading { color: rgba(255,255,255,0.4); text-align: center; padding: 40px; }
    </style>
</head>
<body>
    <div class="container">
        <h1>彭筱雅 台股投資組合</h1>
        <div id="content" class="loading">載入中...</div>
    </div>
    <script>
        async function load() {
            try {
                const r = await fetch('/api/portfolio');
                if (!r.ok) throw new Error('HTTP ' + r.status);
                const d = await r.json();
                document.getElementById('content').innerHTML =
                    '<pre style="color:rgba(255,255,255,0.8)">' + JSON.stringify(d, null, 2) + '</pre>';
            } catch(e) {
                document.getElementById('content').innerHTML =
                    '<div class="error">無法載入: ' + e.message + '</div>';
            }
        }
        load();
        setInterval(load, 30000);
    </script>
</body>
</html>"""

DAYTRADE_HTML = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>當沖模擬</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif; }
        body { background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); min-height: 100vh; padding: 20px; }
        .container { max-width: 1000px; margin: 0 auto; }
        .header {
            background: linear-gradient(135deg, #d97706 0%, #f59e0b 100%);
            color: white; padding: 24px 30px; border-radius: 16px; margin-bottom: 20px;
            display: flex; justify-content: space-between; align-items: center;
        }
        .header h1 { font-size: 1.6rem; font-weight: 700; }
        .header .subtitle { opacity: 0.9; margin-top: 4px; font-size: 0.9rem; }
        .header .nav-link {
            background: rgba(255,255,255,0.2); padding: 8px 16px; border-radius: 50px;
            color: white; text-decoration: none; font-size: 0.85rem;
            backdrop-filter: blur(10px); transition: background 0.2s;
        }
        .header .nav-link:hover { background: rgba(255,255,255,0.35); }
        .summary-grid {
            display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px;
        }
        .summary-card {
            background: rgba(255,255,255,0.05); backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 20px;
            text-align: center; color: white;
        }
        .summary-card .label { font-size: 0.8rem; opacity: 0.6; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 1px; }
        .summary-card .value { font-size: 1.6rem; font-weight: 700; }
        .summary-card .value.green { color: #10b981; }
        .summary-card .value.red { color: #ef4444; }
        .section {
            background: rgba(255,255,255,0.05); backdrop-filter: blur(10px);
            border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 24px; margin-bottom: 24px;
        }
        .section h2 { color: white; font-size: 1.2rem; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
        .section h2 span { opacity: 0.5; font-size: 0.85rem; font-weight: 400; }
        table { width: 100%; border-collapse: separate; border-spacing: 0; }
        th {
            text-align: left; padding: 10px 14px; font-size: 0.78rem;
            color: rgba(255,255,255,0.5); text-transform: uppercase; letter-spacing: 1px;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        td { padding: 10px 14px; color: rgba(255,255,255,0.9); font-size: 0.88rem; border-bottom: 1px solid rgba(255,255,255,0.05); }
        tr:last-child td { border-bottom: none; }
        tr:hover td { background: rgba(255,255,255,0.03); }
        .symbol { font-weight: 600; color: #60a5fa; }
        .green { color: #10b981; }
        .red { color: #ef4444; }
        .loading { text-align: center; padding: 40px; color: rgba(255,255,255,0.4); font-size: 1rem; }
        .error { text-align: center; padding: 40px; color: #ef4444; }
        .note { color: rgba(255,255,255,0.4); font-size: 0.78rem; }
        .empty { text-align: center; padding: 30px; color: rgba(255,255,255,0.35); }
        .badge-dt { display: inline-block; background: rgba(255,255,255,0.1); padding: 4px 12px; border-radius: 50px; font-size: 0.75rem; color: rgba(255,255,255,0.7); margin-left: 8px; }
        .refresh-note { text-align: right; padding: 8px 0; color: rgba(255,255,255,0.3); font-size: 0.75rem; }

        @media (max-width: 768px) {
            .summary-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
            .header { flex-direction: column; text-align: center; gap: 12px; }
            table { font-size: 0.8rem; }
            th, td { padding: 6px 8px; }
        }

        .market-badge {
            display: inline-block; padding: 3px 10px; border-radius: 50px; font-size: 0.7rem;
            font-weight: 600; margin-left: 10px;
        }
        .market-open { background: rgba(16, 185, 129, 0.2); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.3); }
        .market-closed { background: rgba(239, 68, 68, 0.2); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div>
                <h1>📊 當沖模擬 <span id="marketStatus" class="market-badge market-closed">市場收盤</span></h1>
                <div class="subtitle" id="dtSubtitle">載入中...</div>
            </div>
            <a href="/" class="nav-link">← 主投資組合</a>
        </div>

        <!-- Summary Cards -->
        <div class="summary-grid">
            <div class="summary-card"><div class="label">初始資金</div><div class="value" id="dtInitial">—</div></div>
            <div class="summary-card"><div class="label">可用現金</div><div class="value" id="dtCash">—</div></div>
            <div class="summary-card"><div class="label">未實現損益</div><div class="value" id="dtUnrealized">—</div></div>
            <div class="summary-card"><div class="label">已實現損益</div><div class="value" id="dtRealized">—</div></div>
        </div>

        <!-- Open Positions -->
        <div class="section">
            <h2>當前持倉 <span id="positionsCount">0</span></h2>
            <table>
                <thead>
                    <tr>
                        <th>#</th><th>標的</th><th>股數</th><th>進場價</th><th>現價</th><th>損益</th><th>%</th><th>備註</th>
                    </tr>
                </thead>
                <tbody id="positionsBody">
                    <tr><td colspan="8" class="loading">載入中...</td></tr>
                </tbody>
            </table>
        </div>

        <!-- Trade History -->
        <div class="section">
            <h2>交易紀錄 <span id="historyCount">0</span></h2>
            <table>
                <thead>
                    <tr>
                        <th>#</th><th>標的</th><th>股數</th><th>進場</th><th>出場</th><th>損益</th><th>%</th>
                    </tr>
                </thead>
                <tbody id="historyBody">
                    <tr><td colspan="7" class="empty">尚無交易紀錄</td></tr>
                </tbody>
            </table>
        </div>

        <!-- Daily PnL -->
        <div class="section">
            <h2>本日當沖 <span id="tradesCount">0</span></h2>
            <table>
                <thead>
                    <tr>
                        <th>日期</th><th>已實現損益</th><th>交易次數</th>
                    </tr>
                </thead>
                <tbody id="tradesBody">
                    <tr><td colspan="3" class="empty">—</td></tr>
                </tbody>
            </table>
        </div>

        <div class="refresh-note" id="refreshNote">等待更新...</div>
    </div>

    <script>
        const USD_TWD = 33.0;
        const REFRESH_MS = 15000;

        function formatMoney(n) {
            if (n === undefined || n === null) return '—';
            return Number(n).toLocaleString('zh-TW', {minimumFractionDigits: 0, maximumFractionDigits: 0});
        }
        function formatPrice(n) { return Number(n).toFixed(2); }

        function checkMarketStatus() {
            const now = new Date();
            const ny = new Date(now.toLocaleString('en-US', {timeZone: 'America/New_York'}));
            const day = ny.getDay();
            const hours = ny.getHours();
            const mins = ny.getMinutes();
            const totalMins = hours * 60 + mins;
            const isOpen = day >= 1 && day <= 5 && totalMins >= 570 && totalMins < 960;
            const badge = document.getElementById('marketStatus');
            if (isOpen) {
                badge.textContent = '📈 交易中';
                badge.className = 'market-badge market-open';
            } else {
                badge.textContent = '🔒 市場收盤';
                badge.className = 'market-badge market-closed';
            }
        }

        async function fetchData() {
            const resp = await fetch('/api/daytrade');
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return await resp.json();
        }

        function render(dt) {
            if (!dt || dt.error) {
                document.getElementById('positionsBody').innerHTML =
                    '<tr><td colspan="8" class="error">無法載入資料</td></tr>';
                return;
            }

            const positions = dt.positions || [];
            const trades = dt.trade_history || [];
            const cash = dt.cash || 0;
            const initial = dt.initial_capital || 100000;

            document.getElementById('dtSubtitle').textContent =
                '獨立 ' + Number(initial).toLocaleString('zh-TW') + ' TWD 資金 — 同日買賣、即時損益';

            const totalRealized = dt.total_realized_pnl || 0;
            const unrealizedSum = positions.reduce((s, p) => s + (p.unrealized_pnl_usd || 0) * USD_TWD, 0);

            document.getElementById('dtInitial').textContent = 'NT$' + formatMoney(initial);
            document.getElementById('dtCash').textContent = 'NT$' + formatMoney(cash);

            const unrealCls = unrealizedSum >= 0 ? 'green' : 'red';
            document.getElementById('dtUnrealized').innerHTML =
                '<span class="' + unrealCls + '">' + (unrealizedSum >= 0 ? '+' : '') + 'NT$' + formatMoney(unrealizedSum) + '</span>';

            const realCls = totalRealized >= 0 ? 'green' : 'red';
            document.getElementById('dtRealized').innerHTML =
                '<span class="' + realCls + '">' + (totalRealized >= 0 ? '+' : '') + 'NT$' + formatMoney(totalRealized) + '</span>';

            document.getElementById('positionsCount').textContent = positions.length + ' 筆';

            const posHtml = positions.map(p => {
                const pnl = p.unrealized_pnl_usd || 0;
                const pct = p.unrealized_pnl_pct || 0;
                const cls = pnl >= 0 ? 'green' : 'red';
                const arrow = pnl >= 0 ? '▲' : '▼';
                return '<tr>' +
                    '<td>' + p.id + '</td>' +
                    '<td class="symbol">' + p.symbol + '</td>' +
                    '<td>' + p.shares + '</td>' +
                    '<td>$' + formatPrice(p.entry_price_usd) + '</td>' +
                    '<td>$' + formatPrice(p.current_price_usd) + '</td>' +
                    '<td class="' + cls + '">' + arrow + ' $' + formatPrice(Math.abs(pnl)) + '</td>' +
                    '<td class="' + cls + '">' + (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%</td>' +
                    '<td class="note">' + (p.note || '') + '</td>' +
                    '</tr>';
            }).join('') || '<tr><td colspan="8" class="empty">尚無持倉</td></tr>';
            document.getElementById('positionsBody').innerHTML = posHtml;

            const histHtml = trades.slice().reverse().map(t => {
                const pnl = t.pnl_twd || 0;
                const cls = pnl >= 0 ? 'green' : 'red';
                const arrow = pnl >= 0 ? '▲' : '▼';
                return '<tr>' +
                    '<td>' + (t.id || '') + '</td>' +
                    '<td class="symbol">' + (t.symbol || '') + '</td>' +
                    '<td>' + (t.shares || 0) + '</td>' +
                    '<td>$' + formatPrice(t.entry_price_usd || 0) + '</td>' +
                    '<td>$' + formatPrice(t.exit_price_usd || 0) + '</td>' +
                    '<td class="' + cls + '">' + arrow + ' NT$' + formatMoney(Math.abs(pnl)) + '</td>' +
                    '<td class="' + cls + '">' + (pnl >= 0 ? '+' : '') + (t.pnl_pct || 0).toFixed(2) + '%</td>' +
                    '</tr>';
            }).join('') || '<tr><td colspan="7" class="empty">尚無交易紀錄</td></tr>';
            document.getElementById('historyBody').innerHTML = histHtml;
            document.getElementById('historyCount').textContent = trades.length + ' 筆';

            const dpnl = dt.daily_pnl || {};
            const today = new Date().toISOString().slice(0, 10);
            const todayPnl = dpnl[today];
            const dailyHtml = todayPnl
                ? '<tr><td>' + today + '</td><td class="' + (todayPnl.realized_pnl_twd >= 0 ? 'green' : 'red') + '">' +
                  (todayPnl.realized_pnl_twd >= 0 ? '+' : '') + 'NT$' + formatMoney(todayPnl.realized_pnl_twd) +
                  '</td><td>' + (todayPnl.trades_count || 0) + ' 筆</td></tr>'
                : '<tr><td colspan="3" class="empty">本日尚無交易</td></tr>';
            document.getElementById('tradesBody').innerHTML = dailyHtml;
            document.getElementById('tradesCount').textContent = (todayPnl ? todayPnl.trades_count : 0) + ' 筆';
        }

        async function init() {
            checkMarketStatus();
            setInterval(checkMarketStatus, 60000);
            try {
                const dt = await fetchData();
                render(dt);
                document.getElementById('refreshNote').textContent = '每 ' + (REFRESH_MS/1000) + ' 秒自動更新 | ' + new Date().toLocaleTimeString('zh-TW');
                setInterval(async () => {
                    try {
                        const dt2 = await fetchData();
                        render(dt2);
                        document.getElementById('refreshNote').textContent = '每 ' + (REFRESH_MS/1000) + ' 秒自動更新 | 最後更新 ' + new Date().toLocaleTimeString('zh-TW');
                    } catch(e) {
                        document.getElementById('refreshNote').textContent = '⚠ 更新失敗: ' + e.message;
                    }
                }, REFRESH_MS);
            } catch (e) {
                document.getElementById('positionsBody').innerHTML =
                    '<tr><td colspan="8" class="error">無法載入當沖資料: ' + e.message + '</td></tr>';
                document.getElementById('refreshNote').textContent = '⚠ 載入失敗';
            }
        }

        init();
    </script>
</body>
</html>"""

SIM_PORTFOLIO_HTML = r"""<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>模擬投資組合</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'Segoe UI','Microsoft JhengHei',sans-serif}
body{background:linear-gradient(135deg,#0f172a 0%,#1e293b 100%);min-height:100vh;padding:20px}
.container{max-width:1100px;margin:0 auto}
.header{background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%);color:#fff;padding:24px 30px;border-radius:16px;margin-bottom:24px;display:flex;justify-content:space-between;align-items:center}
.header h1{font-size:1.5rem;font-weight:700}
.header .sub{opacity:.8;font-size:.85rem;margin-top:4px}
.nav-link{background:rgba(255,255,255,.2);padding:7px 16px;border-radius:50px;color:#fff;text-decoration:none;font-size:.82rem;transition:background .2s}
.nav-link:hover{background:rgba(255,255,255,.35)}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:24px}
.card{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:18px;text-align:center;color:#fff}
.card .lbl{font-size:.75rem;opacity:.5;margin-bottom:6px;letter-spacing:1px}
.card .val{font-size:1.4rem;font-weight:700}
.green{color:#10b981}
.red{color:#ef4444}
.blue{color:#60a5fa}
.section{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:24px;margin-bottom:20px}
.section h2{color:#fff;font-size:1.1rem;margin-bottom:16px;display:flex;align-items:center;gap:8px}
.section h2 span{opacity:.5;font-size:.85rem;font-weight:400}
.hgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}
.hcard{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.08);border-radius:10px;padding:16px;color:#fff;position:relative}
.hcard .hsym{font-size:1rem;font-weight:700;color:#60a5fa}
.hcard .hprice{font-size:.78rem;color:rgba(255,255,255,.5);margin:2px 0 6px}
.hcard .hrow{display:flex;justify-content:space-between;font-size:.82rem;padding:2px 0}
.hcard .hrow .l{color:rgba(255,255,255,.5)}
.hcard .hrow .v{font-weight:600}
.hcard .hpnl{position:absolute;top:16px;right:16px;font-size:1rem;font-weight:700}
table{width:100%;border-collapse:collapse}
th{text-align:left;padding:8px 12px;font-size:.72rem;color:rgba(255,255,255,.4);letter-spacing:1px;border-bottom:1px solid rgba(255,255,255,.1)}
td{padding:8px 12px;color:rgba(255,255,255,.85);font-size:.84rem;border-bottom:1px solid rgba(255,255,255,.05)}
tr:hover td{background:rgba(255,255,255,.03)}
.buy{color:#10b981}
.sell{color:#ef4444}
.empty{text-align:center;padding:30px;color:rgba(255,255,255,.35)}
.loading{text-align:center;padding:40px;color:rgba(255,255,255,.3)}
.error{text-align:center;padding:40px;color:#ef4444}
.rnote{text-align:right;color:rgba(255,255,255,.25);font-size:.72rem;margin-top:12px}
@media(max-width:768px){.grid{grid-template-columns:repeat(2,1fr)}.header{flex-direction:column;text-align:center;gap:12px}}
</style>
</head>
<body>
<div class="container">
<div class="header">
<div><h1>模擬投資組合</h1><div class="sub">AI 委員會自動交易模擬 &middot; 初始資金 NT$650,000</div></div>
<div><a href="/" class="nav-link">主組合</a> <a href="/daytrade" class="nav-link">當沖</a></div>
</div>

<div class="grid" id="summaryGrid">
<div class="card"><div class="lbl">總權益</div><div class="val" id="spEquity">—</div></div>
<div class="card"><div class="lbl">未實現損益</div><div class="val" id="spUpnl">—</div></div>
<div class="card"><div class="lbl">已實現損益</div><div class="val" id="spRpnl">—</div></div>
<div class="card"><div class="lbl">總報酬率</div><div class="val" id="spReturn">—</div></div>
</div>

<div id="holdingsSection"></div>

<div class="section">
<h2>交易紀錄 <span id="spTradeCount">0</span></h2>
<table><thead><tr><th>#</th><th>標的</th><th>動作</th><th>股數</th><th>價格</th><th>日期</th><th>備註</th></tr></thead>
<tbody id="spBody"><tr><td colspan="7" class="loading">載入中...</td></tr></tbody></table>
</div>
<div class="rnote" id="spRefresh">每 30 秒自動更新</div>
</div>

<script>
async function load(){
try{
const r=await fetch('/api/sim-portfolio');
if(!r.ok)throw new Error('HTTP '+r.status);
const d=await r.json();
if(d.error)throw new Error(d.error);
const h=d.holdings||{};

// Summary
document.getElementById('spEquity').textContent='NT$'+Number(d.total_equity||0).toLocaleString();
const u=d.unrealized_pnl||0;const ru=document.getElementById('spUpnl');
ru.textContent=(u>=0?'+':'')+'NT$'+Math.abs(u).toLocaleString();ru.className='val'+(u>=0?' green':' red');
const rp=d.realized_pnl||0;const rr=document.getElementById('spRpnl');
rr.textContent=(rp>=0?'+':'')+'NT$'+Math.abs(rp).toLocaleString();rr.className='val'+(rp>=0?' green':' red');
const ret=d.total_return_pct||0;const rret=document.getElementById('spReturn');
rret.textContent=(ret>=0?'+':'')+ret.toFixed(2)+'%';rret.className='val'+(ret>=0?' green':' red');

// Holdings
const hs=document.getElementById('holdingsSection');
const hkeys=Object.keys(h);
if(hkeys.length){
hs.innerHTML='<div class="section"><h2>當前持有 <span>'+hkeys.length+' 檔</span></h2><div class="hgrid">'+
hkeys.map(sym=>{
const x=h[sym];
const up=x.unrealized_pnl||0;
const cls=up>=0?'green':'red';
const isUS=sym.indexOf('.TW')===-1;
const priceLabel=isUS&&x.current_price_usd?'$'+Number(x.current_price_usd).toLocaleString():'NT$'+Number(x.current_price||0).toLocaleString();
return '<div class="hcard"><div class="hsym">'+sym+'</div><div class="hprice">成本 NT$'+Number(x.avg_price||0).toLocaleString()+'</div>'+
'<div class="hrow"><span class="l">持有</span><span class="v">'+Number(x.shares||0).toLocaleString()+' 股</span></div>'+
'<div class="hrow"><span class="l">市值</span><span class="v">NT$'+Number(x.market_value||0).toLocaleString()+'</span></div>'+
'<div class="hrow"><span class="l">現價</span><span class="v">'+priceLabel+'</span></div>'+
'<div class="hpnl '+cls+'">'+(up>=0?'+':'')+'NT$'+Math.abs(up).toLocaleString()+'</div></div>';
}).join('')+'</div></div>';
}else{
hs.innerHTML='<div class="section"><h2>當前持有</h2><div class="empty">尚無持有標的</div></div>';
}

// Trades
const trades=d.trades||[];
document.getElementById('spTradeCount').textContent=trades.length+' 筆';
document.getElementById('spBody').innerHTML=trades.slice().reverse().map(t=>{
const cls=t.action==='buy'?'buy':'sell';
return '<tr><td>'+(t.id||'')+'</td><td class="blue">'+(t.symbol||'')+'</td><td class="'+cls+'">'+(t.action||'')+'</td><td>'+(t.shares||0)+'</td><td>NT$'+Number(t.price||0).toLocaleString()+'</td><td>'+(t.date||'')+'</td><td style="color:rgba(255,255,255,0.4);font-size:.78rem">'+(t.note||'')+'</td></tr>';
}).join('')||'<tr><td colspan="7" class="empty">尚無交易</td></tr>';

document.getElementById('spRefresh').textContent='最後更新: '+new Date().toLocaleTimeString('zh-TW')+' | 每 30 秒自動更新';
}catch(e){
document.getElementById('spBody').innerHTML='<tr><td colspan="7" class="error">無法載入: '+e.message+'</td></tr>';
}}
load();setInterval(load,30000);
</script>
</body></html>"""

# ── HTTP Handler ────────────────────────────────────────────────────

# Simple cache for sim portfolio data (TTL: 20s so expensive yfinance calls don't block the server)
_sim_cache: dict = {"data": None, "ts": 0.0}

def _load_sim_portfolio_data() -> dict:
    """Load portfolio_sim.json, compute holdings, fetch live prices (cached 20s)."""
    import time
    now = time.time()
    if _sim_cache["data"] and now - _sim_cache["ts"] < 20:
        return _sim_cache["data"]

    raw = _load_json(BASE_DIR / "portfolio_sim.json")
    if not raw:
        return {"error": "no data", "initial_capital": 650000}

    trades = raw.get("trades", [])
    cap = float(raw.get("initial_capital", 650000))
    realized_pnl = float(raw.get("realized_pnl", 0))

    net: dict[str, dict] = {}
    for t in trades:
        sym = t["symbol"]
        if sym == "CASH":
            continue
        shares = float(t.get("shares", 0))
        price = float(t.get("price", 0))
        if sym not in net:
            net[sym] = {"shares": 0.0, "total_cost": 0.0}
        if t["action"] == "buy":
            net[sym]["shares"] += shares
            net[sym]["total_cost"] += shares * price
        elif t["action"] == "sell":
            net[sym]["shares"] -= shares
            net[sym]["total_cost"] -= shares * price

    holdings = {sym: v for sym, v in net.items() if abs(v["shares"]) > 0.001}

    import math

    # Separate US stocks (yfinance) and TW stocks (TWSE API)
    us_symbols = [sym for sym in holdings if not sym.endswith(".TW")]
    tw_symbols = [sym for sym in holdings if sym.endswith(".TW")]

    live = {}
    if us_symbols:
        import yfinance as yf
        for sym in us_symbols:
            try:
                h = yf.Ticker(sym).history(period="5d")
                if h is not None and len(h) >= 1:
                    cp = float(h["Close"].iloc[-1])
                    if not math.isnan(cp):
                        live[sym] = cp
            except Exception:
                pass

    # Use TWSE direct API for TW stocks (avoid yfinance NaN issues)
    if tw_symbols:
        tw_codes = [s.replace(".TW", "") for s in tw_symbols]
        tw_prices = _fetch_twse_prices(tw_codes)
        for sym in tw_symbols:
            code = sym.replace(".TW", "")
            p = tw_prices.get(code, {})
            if p.get("price", 0) > 0:
                live[sym] = p["price"]

    # Fetch USD/TWD rate via yfinance with NaN guard
    usd_twd = 33.0
    try:
        import yfinance as yf
        h = yf.Ticker("TWD=X").history(period="5d")
        if h is not None and len(h) >= 1:
            rate = float(h["Close"].iloc[-1])
            if not math.isnan(rate):
                usd_twd = rate
    except Exception:
        pass

    total_mv = 0.0
    total_upnl = 0.0
    for sym, v in holdings.items():
        avg_p = round(v["total_cost"] / v["shares"], 2) if v["shares"] else 0
        v["avg_price"] = avg_p
        cp_usd = live.get(sym)
        if cp_usd is not None and not (isinstance(cp_usd, float) and math.isnan(cp_usd)):
            is_us_stock = not sym.endswith(".TW")
            cp = round(cp_usd * usd_twd, 2) if is_us_stock else round(cp_usd, 2)
        else:
            cp = avg_p
            cp_usd = None
        mv = v["shares"] * cp
        upnl = mv - v["total_cost"]
        v["current_price"] = round(cp, 2)
        v["current_price_usd"] = round(cp_usd, 2) if cp_usd is not None else None
        v["market_value"] = round(mv, 2)
        v["unrealized_pnl"] = round(upnl, 2)
        v["unrealized_pnl_pct"] = round((cp - avg_p) / avg_p * 100, 2) if avg_p else 0
        total_mv += mv
        total_upnl += upnl

    equity = cap + realized_pnl + total_upnl
    ret_pct = (equity - cap) / cap * 100 if cap else 0

    result = {
        "initial_capital": cap,
        "total_equity": round(equity, 2),
        "total_return_pct": round(ret_pct, 2),
        "realized_pnl": round(realized_pnl, 2),
        "unrealized_pnl": round(total_upnl, 2),
        "holdings": holdings,
        "trades": trades,
        "trade_count": len(trades),
    }
    _sim_cache["data"] = result
    _sim_cache["ts"] = now
    return result


class Handler(BaseHTTPRequestHandler):
    def _json(self, data: Any, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _html(self, html: str, status=200):
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, path: str, method: str = "GET"):
        """Proxy request to backend server (airdrop_hunter on 8888)."""
        try:
            url = f"http://localhost:8888{path}"
            if method == "POST":
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length) if length > 0 else b"{}"
                req = urllib.request.Request(url, data=body, method="POST")
                req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
            else:
                req = urllib.request.Request(url, method="GET")
            resp = urllib.request.urlopen(req, timeout=15)
            rbody = resp.read()
            # Verify we got the full body (defensive against truncated reads)
            ct_len = resp.headers.get("Content-Length")
            if ct_len and len(rbody) < int(ct_len):
                logger.warning("Proxy %s %s: truncated %d < %s, retrying read", method, path, len(rbody), ct_len)
                rbody += resp.read()
            self.send_response(resp.status)
            self.send_header("Content-Type", resp.headers.get("Content-Type", "application/octet-stream"))
            self.send_header("Content-Length", str(len(rbody)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(rbody)
        except Exception as e:
            logger.error("Proxy %s %s failed: %s", method, path, e)
            self._json({"error": f"proxy error: {e}"}, 502)

    def do_GET(self):
        path = self.path.rstrip("/") or "/"
        try:
            if path == "/" or path == "/index.html":
                self._html(WIFE_HTML)
            elif path == "/quotation" or path == "/quotation.html":
                self._html(QUOTATION_HTML)
            elif path == "/daytrade" or path == "/daytrade.html":
                self._html(DAYTRADE_HTML)
            elif path == "/sim_portfolio" or path == "/sim_portfolio.html":
                self._html(SIM_PORTFOLIO_HTML)
            elif path == "/api/daytrade":
                self._json(_load_daytrade_data())
            elif path == "/api/sim-portfolio":
                self._json(_load_sim_portfolio_data())
            elif path.startswith("/api/prices"):
                qs = urllib.parse.urlparse(self.path).query
                params = urllib.parse.parse_qs(qs)
                codes_str = params.get("codes", [""])[0]
                codes = [c.strip() for c in codes_str.split(",") if c.strip()]
                data = _fetch_twse_prices(codes)
                self._json(data)
            elif path.startswith("/api/") or path.startswith("/db/"):
                self._proxy(self.path)
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            logger.exception("Request error")
            self._json({"error": str(e)}, 500)

    def do_POST(self):
        path = self.path.rstrip("/") or "/"
        try:
            if path.startswith("/api/"):
                self._proxy(self.path, method="POST")
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            logger.exception("POST error")
            self._json({"error": str(e)}, 500)

    def log_message(self, fmt, *args):
        pass  # quiet


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    port = 8890
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    logger.info("Dashboard server → http://localhost:%d", port)
    logger.info("  Wife Portfolio: http://localhost:%d/", port)
    logger.info("  Quotation: http://localhost:%d/quotation", port)
    logger.info("  Daytrade:  http://localhost:%d/daytrade", port)
    logger.info("  Sim Portfolio: http://localhost:%d/sim_portfolio.html", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
