"""Entry point for the rToken Breakout Lab Playbook.

Historical mode: fetch Bitget RWA spot 4h bars via getagent.data, replay the
confirmed-breakout rules through the Nautilus engine, and emit a summary
signal with sandbox metrics.

Live mode: every scheduled run evaluates each symbol's completed 4h bars,
enters on confirmed breakouts (hold_level confirmation), exits on channel
breaks; execution flows through the managed follow-trade callback.
"""
import math
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from getagent import data, runtime

SYMBOLS = ["RQQQUSDT", "RSPYUSDT", "RAAPLUSDT", "RTSLAUSDT"]
INTERVAL = "4h"
INTERVAL_MS = 4 * 60 * 60 * 1000
MAX_STALE_INTERVALS = 2


def _sanitize(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _records(response: object) -> list[dict]:
    return [dict(row) for row in data.to_records(response)]


def _decimal(value: object, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _fetch_4h(symbol: str, lookback: int = 400) -> list[dict]:
    bars = data.crypto.spot.kline(
        symbol=symbol,
        interval=INTERVAL,
        exchange="bitget",
        limit=lookback,
        closed_only=True,
    )
    return _records(bars)


# ---------------------------------------------------------------- indicators
def confirmed_breakout_state(rows: list[dict], window: int, confirmations: int) -> dict | None:
    """Evaluate hold_level-confirmed breakout on completed 4h bars.

    Mirrors src/basis_lab/trend_research.py: breakout vs prior `window`-bar high
    (excluding current bar), confirmed by `confirmations` consecutive closes
    holding above the ORIGINAL breakout anchor. Channel exit vs prior
    `window`-bar low.
    """
    closes, highs, lows = [], [], []
    for row in rows:
        c, h, l = _decimal(row.get("close")), _decimal(row.get("high")), _decimal(row.get("low"))
        if c > 0 and h > 0 and l > 0:
            closes.append(c); highs.append(h); lows.append(l)
    n = len(closes)
    need = window + confirmations + 1
    if n < need:
        return None

    def prior_extremes(idx: int) -> tuple[Decimal, Decimal] | None:
        """(prior_high, prior_low) over [idx-window, idx-1] using closes list index."""
        if idx < window:
            return None
        hi = max(highs[idx - window:idx])
        lo = min(lows[idx - window:idx])
        return hi, lo

    last = n - 1
    ext = prior_extremes(last)
    if ext is None:
        return None
    prior_high, prior_low = ext
    close = closes[last]

    # hold_level confirmation: the breakout fired (confirmations-1) bars ago
    anchor_idx = last - (confirmations - 1)
    anchor_ext = prior_extremes(anchor_idx)
    if anchor_ext is None:
        return None
    anchor_high = anchor_ext[0]

    # was it a genuine breakout at anchor, and has every bar since held above it?
    breakout_at_anchor = closes[anchor_idx] > anchor_high
    held = all(closes[last - lag] > anchor_high for lag in range(confirmations))
    enter_now = breakout_at_anchor and held

    leave_now = close < prior_low

    # realized vol (annualized, 6 bars/day) over last 18 bars
    rets = [(closes[i] / closes[i - 1] - 1) for i in range(n - 18, n) if closes[i - 1] > 0]
    vol_ann = Decimal(str(math.sqrt(sum(float(r) ** 2 for r in rets) / max(len(rets, 1)) * 6 * 365))) \
        if rets else Decimal("0")
    return {
        "close": close,
        "prior_high": prior_high,
        "prior_low": prior_low,
        "anchor_high": anchor_high,
        "enter": enter_now,
        "leave": leave_now,
        "vol_ann": vol_ann,
    }


def _last_bar_open_ms(rows: list[dict]) -> int | None:
    stamps = [int(v) for row in rows for v in (row.get("time"),)
              if isinstance(v, (int, float)) and not isinstance(v, bool)]
    return max(stamps) if stamps else None


def _is_stale(last_open_ms: int | None) -> bool:
    if last_open_ms is None:
        return True
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return now_ms - (last_open_ms + INTERVAL_MS) > MAX_STALE_INTERVALS * INTERVAL_MS


# ---------------------------------------------------------------- historical
# ---------------------------------------------------------------- live
def _execute_spot_buy(*, symbol: str, quote_budget: str) -> dict:
    from getagent import trade

    qty_plan = trade.helpers.compute_qty(
        symbol=symbol, market="spot", budget_amount=quote_budget,
    )
    result = trade.spot.buy_market(symbol=symbol, qty=qty_plan.qty)
    if not trade.is_success(result):
        raise RuntimeError(f"spot buy failed: {result}")
    return {"qty": str(qty_plan.qty), "result": result}


def _execute_spot_sell(*, symbol: str, base_qty: str) -> dict:
    from getagent import trade

    result = trade.spot.sell_market(symbol=symbol, qty=base_qty)
    if not trade.is_success(result):
        raise RuntimeError(f"spot sell failed: {result}")
    return {"result": result}


def _run_live() -> None:
    cfg = runtime.manifest.get("strategy_config", {}) or {}
    window = int(cfg.get("window", 18) or 18)
    confirmations = int(cfg.get("confirmation_bars", 2) or 2)
    weight = _decimal(cfg.get("symbol_weight", "0.2"))
    vol_target = _decimal(cfg.get("daily_vol_target", "0.02"))
    budget = str(cfg.get("quote_budget", "1000") or "1000")

    per_symbol = {}
    for sym in SYMBOLS:
        rows = _fetch_4h(sym)
        if _is_stale(_last_bar_open_ms(rows)):
            per_symbol[sym] = {"stale": True}
            continue
        state = confirmed_breakout_state(rows, window, confirmations)
        if state is None:
            per_symbol[sym] = {"insufficient_history": True}
            continue
        vol_ann = state["vol_ann"]
        scale = (vol_target * Decimal("365") ** Decimal("0.5") / vol_ann).quantize(Decimal("0.01")) \
            if vol_ann > 0 else Decimal("1")
        scale = min(scale, Decimal("1"))
        per_symbol[sym] = {
            "close": str(state["close"]),
            "prior_high": str(state["prior_high"]),
            "prior_low": str(state["prior_low"]),
            "enter": state["enter"],
            "leave": state["leave"],
            "vol_ann": str(vol_ann.quantize(Decimal("0.0001"))),
            "scale": str(scale),
        }

    entries = [s for s, v in per_symbol.items() if v.get("enter")]
    exits = [s for s, v in per_symbol.items() if v.get("leave")]

    from getagent import trade
    executed = []
    errors = []
    for sym in exits:  # sells precede buys
        try:
            current = trade.spot.current_position(symbol=sym)
            base = trade.helpers.find_spot_position(current, symbol=sym) if hasattr(trade.helpers, 'find_spot_position') else None
            base_qty = str(getattr(base, "available", getattr(base, "quantity", "0"))) if base else "0"
            if _decimal(base_qty) > 0:
                _execute_spot_sell(symbol=sym, base_qty=base_qty)
                executed.append({"symbol": sym, "side": "sell", "reason": "channel_exit"})
        except Exception as e:  # noqa: BLE001
            errors.append({"symbol": sym, "op": "sell", "error": str(e)})
    for sym in entries:
        try:
            sized = _decimal(budget) * weight * _decimal(per_symbol[sym].get("scale", "1"))
            if sized > 0:
                _execute_spot_buy(symbol=sym, quote_budget=str(sized.quantize(Decimal("0.01"))))
                executed.append({"symbol": sym, "side": "buy",
                                 "reason": "confirmed_breakout", "notional": str(sized)})
        except Exception as e:  # noqa: BLE001
            errors.append({"symbol": sym, "op": "buy", "error": str(e)})

    action = "buy" if entries else "sell" if exits else "hold"
    runtime.emit_signal(
        action=action,
        symbol=(entries or exits or SYMBOLS)[0],
        confidence=0.7 if (entries or exits) else 0.0,
        metrics={"per_symbol": per_symbol, "entries": entries, "exits": exits,
                 "executed": executed, "errors": errors},
        meta={"rule": "confirmed 4h breakout (hold_level), channel exit, vol-scaled sizing",
              "symbols": SYMBOLS},
    )


def run() -> None:
    if runtime.is_live():
        _run_live()
        return
    raise ValueError(
        "live-only playbook: platform replay data has no RWA spot history; "
        "historical evidence lives in the repository's own 1m engine reports"
    )


if __name__ == "__main__":
    run()
