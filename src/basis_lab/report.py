from dataclasses import asdict
from pathlib import Path
from html import escape
import hashlib
import json
import math
import platform
import numpy as np
import pandas as pd
from .data.validate import sha256


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (pd.Timestamp, Path)):
        return str(value)
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path, obj):
    Path(path).write_text(json.dumps(clean(obj), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def metrics(equity_frame, initial_cash):
    frame = equity_frame.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
    curve = frame.equity
    # Initial capital is included in the high-water mark, even when first trade loses.
    peaks = curve.cummax().clip(lower=initial_cash)
    drawdown = curve / peaks - 1
    daily = curve.resample("1D").last().ffill()
    daily_returns = daily.pct_change()
    daily_returns.iloc[0] = daily.iloc[0] / initial_cash - 1
    std = daily_returns.std(ddof=1)
    downside = np.sqrt(np.mean(np.minimum(daily_returns, 0) ** 2))
    sharpe = daily_returns.mean() / std * np.sqrt(365) if len(daily) >= 30 and std > 0 else None
    sortino = daily_returns.mean() / downside * np.sqrt(365) if len(daily) >= 30 and downside > 0 else None
    rolling = daily_returns.rolling(30).mean() / daily_returns.rolling(30).std() * np.sqrt(365)
    stats = {"total_return_pct": (curve.iloc[-1] / initial_cash - 1) * 100,
             "net_pnl": curve.iloc[-1] - initial_cash,
             "max_drawdown_pct": drawdown.min() * 100,
             "sharpe_daily_ann": sharpe, "sortino_daily_ann": sortino,
             "daily_observations": len(daily), "valuation_points": len(frame),
             "stale_valuation_points": int(frame.stale.sum()) if "stale" in frame else 0,
             "max_unhedged_notional": float(frame.net_exposure.abs().max()) if "net_exposure" in frame else 0}
    return stats, pd.DataFrame({"equity": daily, "return": daily_returns, "rolling_30d_sharpe": rolling})


def save_report(engine, output, manifest):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(engine.rows)
    frame.to_csv(output / "equity.csv", index=False)
    stats, daily = metrics(frame, engine.cfg.initial_cash)
    daily.to_csv(output / "daily_returns.csv")
    for name, records, columns in (
        ("fills", engine.fills, ["timestamp", "leg", "quantity", "price", "fee", "slippage_cost", "reason"]),
        ("orders", engine.orders, ["timestamp", "state", "target_shares", "reason"]),
        ("signals", engine.signals, ["timestamp", "entry_basis_bps", "close_basis_bps", "expected_edge_bps", "open_pair", "reason"]),
        ("funding", engine.funding_log, ["timestamp", "rate", "mark", "quantity", "payment", "approximate_mark"]),
        ("trades", engine.trades, ["entry_signal", "exit_time", "exit_reason", "net_pnl", "fees", "funding"]),
    ):
        extra = sorted({key for row in records for key in row} - set(columns))
        pd.DataFrame(records, columns=columns + extra).to_csv(output / f"{name}.csv", index=False)
    p = engine.portfolio
    spot, perp = engine.quotes["spot"], engine.quotes["perp"]
    price_pnl = p.spot.realized + p.perp.realized
    if spot and perp:
        price_pnl += p.spot.unrealized(spot.mark) + p.perp.unrealized(perp.mark)
    stats.update({"closed_cycles": len(engine.trades), "fills": len(engine.fills),
                  "winning_cycle_fraction": np.mean([t["net_pnl"] > 0 for t in engine.trades]) if engine.trades else None,
                  "price_pnl": price_pnl, "funding_pnl": p.funding, "fees": p.fees,
                  "slippage_embedded_in_price_pnl": p.slippage_cost,
                  "turnover_over_initial_cash": sum(abs(f["quantity"] * f["price"]) for f in engine.fills) / p.initial_cash,
                  "ending_spot_shares": p.spot.quantity, "ending_perp_shares": p.perp.quantity,
                  "ending_state": engine.state, "halted": engine.halted,
                  "unclosed_position": not p.flat,
                  "funding_approximate_marks": sum(f["approximate_mark"] for f in engine.funding_log)})
    stats["accounting_residual"] = stats["net_pnl"] - (price_pnl + p.funding - p.fees)
    if abs(stats["accounting_residual"]) > 1e-6:
        raise AssertionError(f"Accounting does not reconcile: {stats['accounting_residual']}")
    execution_note = ("Bar replay uses next completed bar high/low with volume caps, not observed bid/ask depth."
                      if manifest.get("mode") == "bar_research" else
                      "Paper replay uses recorded top-of-book snapshots; queueing, intervening trades and available capacity remain assumptions.")
    warnings = [
        "Research simulation; positive returns do not establish an executable arbitrage.",
        execution_note,
        "Configured fees/margin/contract mapping are assumptions until verified for the account and instruments.",
        "Funding without settlement mark uses the latest fresh perp close as an approximation.",
        "No dividends, splits, issuer adjustments, exchange liquidation tiers or borrow model in v0.1.",
        "Remaining positions are marked, never force-filled at the end of data; exit costs are not booked until filled.",
        "Historical holdout is not proof of an untouched forward test; do not retune on its results.",
    ]
    if stats["unclosed_position"]:
        warnings.append("OPEN POSITION AT END: reported equity includes unrealized PnL and incomplete exit costs.")
    if stats["stale_valuation_points"]:
        warnings.append("STALE PRICES PRESENT: measured drawdown can understate risk during market/data outages.")
    if stats["daily_observations"] < 30:
        warnings.append("Fewer than 30 daily observations: annualized Sharpe/Sortino suppressed.")
    if stats["closed_cycles"] < 30:
        warnings.append("Fewer than 30 completed cycles: performance estimates have very limited statistical support.")
    stats["warnings"] = warnings
    source_root = Path(__file__).parent
    code_files = {str(f.relative_to(source_root)): sha256(f) for f in sorted(source_root.rglob("*.py"))}
    manifest.update({"config": asdict(engine.cfg), "python": platform.python_version(),
                     "pandas": pd.__version__, "numpy": np.__version__, "source_hashes": code_files,
                     "config_sha256": hashlib.sha256(json.dumps(asdict(engine.cfg), sort_keys=True).encode()).hexdigest()})
    write_json(output / "manifest.json", manifest)
    write_json(output / "summary.json", stats)
    # Standalone HTML, no CDN or JavaScript required; all figures are generated.
    values = frame.equity.to_numpy()
    stride = max(1, len(values) // 1800)
    sampled = np.append(values[::stride], values[-1])
    lo, hi = float(min(sampled)), float(max(sampled))
    coords = " ".join(f"{20+i/(len(sampled)-1)*960:.1f},{220-(v-lo)/max(hi-lo,1e-8)*190:.1f}" for i,v in enumerate(sampled))
    rows = "".join(f"<tr><td>{escape(k)}</td><td>{escape(str(clean(v)))}</td></tr>" for k,v in stats.items() if k != "warnings")
    notes = "".join(f"<li>{escape(w)}</li>" for w in warnings)
    title = "SYNTHETIC DEMO" if manifest.get("synthetic") else "HISTORICAL RESEARCH"
    html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Basis Lab · {title}</title><style>body{{font:16px system-ui;background:#101827;color:#e5edf7;max-width:1040px;margin:40px auto;padding:0 24px}}h1{{color:#72e5c0}}svg{{background:#182538;border-radius:12px;width:100%}}table{{border-collapse:collapse;width:100%}}td{{padding:9px;border-bottom:1px solid #314158}}td:last-child{{text-align:right}}li{{margin:9px 0}}small{{color:#a0b2c7}}a{{color:#72e5c0}}</style>
<h1>Basis Lab · {title}</h1><p>{escape(engine.cfg.spot_symbol)} + short {escape(engine.cfg.perp_symbol)} · {escape(str(manifest.get('split')))}</p>
<p>Net return {stats['total_return_pct']:.4f}% · Max drawdown {stats['max_drawdown_pct']:.4f}% · Closed cycles {stats['closed_cycles']}</p>
<svg viewBox="0 0 1000 250" role="img" aria-label="Portfolio equity"><polyline points="{coords}" fill="none" stroke="#72e5c0" stroke-width="2"/></svg>
<small>Equity range {lo:.2f}–{hi:.2f} USDT. Initial capital {p.initial_cash:.2f}. Full timestamps in equity.csv.</small>
<h2>Assumptions & limitations</h2><ul>{notes}</ul><h2>Computed metrics</h2><table>{rows}</table>
<p><a href="summary.json">Summary</a> · <a href="manifest.json">Manifest</a> · <a href="equity.csv">Equity</a> · <a href="fills.csv">Fills</a> · <a href="funding.csv">Funding</a></p></html>'''
    (output / "report.html").write_text(html, encoding="utf-8")
    return clean(stats)
