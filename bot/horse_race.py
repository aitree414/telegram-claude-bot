import json
import os
from datetime import date
from typing import Optional

REPORT_DIR = os.environ.get("REPORT_DIR", "/Users/aitree414/backtester/reports")

STRATEGY_LABELS = {
    "pullback": "PULLBACK",
    "momentum": "MOMENTUM",
    "quality": "QUALITY",
    "value": "VALUE",
}


def _score_bar(score: float, width: int = 10) -> str:
    filled = max(0, min(width, round(score * width)))
    return "\u2588" * filled + "\u2591" * (width - filled)


def format_daily_report(report_date: Optional[str] = None) -> str:
    if report_date is None:
        report_date = date.today().isoformat()

    path = os.path.join(REPORT_DIR, f"{report_date}.json")
    if not os.path.exists(path):
        return (
            f"\u627e\u4e0d\u5230 {report_date} \u7684\u5831\u544a\u3002\n\n"
            "\u8acb\u5148\u57f7\u884c scheduler_job \u7522\u751f\u5831\u544a\u3002"
        )

    with open(path) as f:
        report = json.load(f)

    lines = [
        f"<b>Horse Race \u2014 {report['date']}</b>",
        "<i>Paper Portfolio Strategy Tracker</i>",
    ]

    for entry in report.get("leaderboard", []):
        strategy = entry["strategy"]
        label = STRATEGY_LABELS.get(strategy, strategy.upper())
        wr = (entry.get("win_rate_30d") or 0) * 100
        avg_ret = (entry.get("avg_return_30d") or 0) * 100
        pick_count = entry.get("pick_count", 0)
        top_picks = entry.get("top_picks", [])

        top_score = top_picks[0]["score"] if top_picks else 0
        bar = _score_bar(top_score)

        top3 = top_picks[:3]
        top3_parts = [
            f"<code>{p['symbol']}</code>\u00a0({p.get('score', 0):.2f})"
            for p in top3
        ]
        top3_str = " \u00b7 ".join(top3_parts)

        top_signals = top_picks[0].get("signals", []) if top_picks else []
        signal_str = " \u00b7 ".join(top_signals[:2]) if top_signals else ""

        lines += [
            "",
            "\u2500" * 20,
            f"<b>{label}</b>",
            f"WR: {wr:.0f}%  |  AvgRet: {avg_ret:+.2f}%  |  {pick_count} picks",
            f"[{bar}]\u00a0{top_score:.2f}",
            f"Top:\u00a0{top3_str}",
        ]
        if signal_str:
            lines.append(f"<i>{signal_str}</i>")

    portfolio = report.get("portfolio_summary", {})
    open_pos = portfolio.get("open_positions", 0)
    if open_pos:
        lines += [
            "",
            "\u2500" * 20,
            f"Portfolio:\u00a0{open_pos}\u00a0open positions",
        ]

    lines += ["", "<i>\u50c5\u4f9b\u53c3\u8003\uff0c\u975e\u6295\u8cc7\u5efa\u8b70</i>"]
    return "\n".join(lines)
