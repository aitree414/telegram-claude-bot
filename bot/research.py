"""
Research module — uses browser-harness for live web research.
Integrates with the Telegram bot for stock/news/polymarket research.
"""

import subprocess
import json
import re
import os
import logging

logger = logging.getLogger(__name__)

BH_CMD = "/Users/aitree414/.local/bin/browser-harness"
BH_ENV = {**os.environ, "BU_CDP_URL": "http://localhost:9222", "PATH": f"{os.environ.get('PATH', '')}:/Users/aitree414/.local/bin"}


def _run_bh(python_code: str) -> str:
    """Run Python code via browser-harness and return stdout."""
    try:
        result = subprocess.run(
            [BH_CMD],
            input=python_code,
            capture_output=True,
            text=True,
            timeout=30,
            env=BH_ENV,
        )
        if result.returncode != 0:
            logger.warning(f"browser-harness stderr: {result.stderr[:500]}")
        return result.stdout or result.stderr or ""
    except subprocess.TimeoutExpired:
        return "browser-harness timed out (30s)"
    except FileNotFoundError:
        return "browser-harness not found — run `uv tool install browser-harness`"
    except Exception as e:
        return f"browser-harness error: {e}"


def research_stock(symbol: str) -> str:
    """Research a stock via Google Finance using browser-harness."""
    code = f'''
new_tab("https://www.google.com/finance/quote/{symbol.upper()}:NASDAQ")
wait_for_load()
text = js("document.body.innerText")
print(text[:3000])
'''
    return _run_bh(code)


def research_market_news() -> str:
    """Get market news from Google Finance."""
    code = '''
new_tab("https://www.google.com/finance")
wait_for_load()
text = js("document.body.innerText")
print(text[:3000])
'''
    return _run_bh(code)


def research_web(query: str) -> str:
    """Search and extract content from a webpage."""
    # Try Google search first
    code = f'''
new_tab("https://www.google.com/search?q={query.replace(' ', '+')}")
wait_for_load()
text = js("document.body.innerText")
print(text[:3000])
'''
    return _run_bh(code)


def research_url(url: str) -> str:
    """Navigate to a URL and extract content."""
    code = f'''
new_tab("{url}")
wait_for_load()
text = js("document.body.innerText")
print(text[:3000])
'''
    return _run_bh(code)


def format_research_output(raw: str, query: str) -> str:
    """Format the raw browser-harness output for Telegram."""
    # Clean up raw output
    lines = raw.strip().split("\n")
    lines = [l for l in lines if l.strip() and not l.startswith("browser-harness")]

    # Truncate to Telegram-friendly length
    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3800] + "\n\n...(truncated)"

    return text
