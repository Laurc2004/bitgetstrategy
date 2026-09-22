#!/usr/bin/env python3
"""Frozen-parameter IS/OOS backtest on v3 4h data (fetched via Bitget v3 public API).

Split (honest, given listing dates 2026-06-01 / RTSLA 2026-04-21):
  IS  = 2026-06-01 .. 2026-08-17  (development window superset; touched by research)
  OOS = 2026-08-18 .. 2026-09-16  (30 days; 06-19 onward touched by v3 research — disclosed)
Frozen config: v3 hold_level-exit18-stop8, zero changes. Base + stress costs.

Note: 4h bars vs the repository's native 1m engine — this script adapts the
signal logic to 4h granularity for the sandbox-parity run; the repository's
own 1m replay (replay_development_v3.py) remains the execution-precision gold
standard for the 06-19..09-17 development window.
"""
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, 'src')
import pandas as pd  # noqa: E402
import numpy as np  # noqa: E402

# --- load 4h bars ---
def load4h(sym):
    df = pd.read_json(f'data/raw4h/{sym}.jsonl', lines=True, convert_dates=False)
    df.columns = ['timestamp', 'open', 'high', 'low', 'close', 'volume'][:len(df.columns)]
    df['timestamp'] = pd.to_datetime(pd.to_numeric(df.timestamp), unit='ms', utc=True)
    return df.drop_duplicates('timestamp').sort_values('timestamp').set_index('timestamp')


CFG = json.loads(Path('configs/development-v3.json').read_text(encoding='utf-8'))
WINDOW = CFG['slow']            # 18
CONFIRM = CFG['confirmation_bars']  # 2
VOL_WIN = 18
VOL_TARGET = CFG['daily_vol_target']  # 0.02
SYM_W = CFG['symbol_weight']    # 0.2
FEE = CFG['fee_bps'] / 1e4
SLIP = CFG['slippage_bps'] / 1e4
TRAIL = CFG['trailing_stop']    # 0.08
CASH0 = CFG['initial_cash']


def signals(df):
    """hold_level-confirmed breakout on 4h bars (mirrors trend_research)."""
    prior_high = df.high.shift(1).rolling(WINDOW, min_periods=WINDOW).max()
    prior_low = df.low.shift(1).rolling(WINDOW, min_periods=WINDOW).min()
    enter0 = df.close > prior_high
    # hold_level confirmation: breakout fired CONFIRM-1 bars ago, held above since
    anchor = prior_high.shift(CONFIRM - 1)
    confirmed = enter0.shift(CONFIRM - 1, fill_value=False)
    for lag in range(CONFIRM - 1):
        confirmed = confirmed & (df.close.shift(lag) > anchor)
    leave = df.close < prior_low
    rets = df.close.pct_change()
    vol = rets.rolling(VOL_WIN, min_periods=12).std() * np.sqrt(6)
    scale = (VOL_TARGET / vol.clip(lower=1e-6)).clip(upper=1.0)
    return pd.DataFrame({'enter': confirmed.fillna(False), 'leave': leave.fillna(False),
                         'scale': scale, 'close': df.close})


def backtest(frames, start, end, fee, slip):
    names = list(frames)
    cash = CASH0
    pos = {s: 0.0 for s in names}
    entry_px = {}
    peaks = {}
    fees_total = 0.0
    trades = []
    eq_curve = []
    idx = None
    for s in names:
        f = frames[s].loc[start:end]
        idx = f.index if idx is None else idx.union(f.index)
    idx = idx.sort_values()
    marks = {s: frames[s]['close'].reindex(idx).ffill() for s in names}
    sig = {s: signals(frames[s]).reindex(idx).ffill() for s in names}
    for t in idx:
        for s in names:
            px = marks[s].loc[t]
            sigrow = sig[s].loc[t]
            if pos[s] > 0:
                peaks[s] = max(peaks[s], px)
                if px < peaks[s] * (1 - TRAIL):  # trailing stop
                    proceeds = pos[s] * px * (1 - fee - slip)
                    fees_total += pos[s] * px * (fee + slip)
                    cash += proceeds
                    trades.append({'sym': s, 'exit': t, 'reason': 'trailing_stop',
                                   'pnl': proceeds - entry_px[s][1]})
                    pos[s] = 0.0
                    continue
            if sigrow['leave'] and pos[s] > 0:
                proceeds = pos[s] * px * (1 - fee - slip)
                fees_total += pos[s] * px * (fee + slip)
                cash += proceeds
                trades.append({'sym': s, 'exit': t, 'reason': 'channel_exit',
                               'pnl': proceeds - entry_px[s][1]})
                pos[s] = 0.0
            elif sigrow['enter'] and pos[s] == 0 and not np.isnan(sigrow['scale']):
                equity = cash + sum(pos[k] * marks[k].loc[t] for k in names)
                budget = equity * SYM_W * sigrow['scale']
                qty = budget / px
                if budget >= CFG['min_order']:
                    cash -= qty * px * (1 + fee + slip)
                    fees_total += qty * px * (fee + slip)
                    pos[s] = qty
                    entry_px[s] = (t, qty * px * (1 + fee + slip))
                    peaks[s] = px
        eq_curve.append({'ts': t, 'equity': cash + sum(pos[k] * marks[k].loc[t] for k in names)})
    curve = pd.DataFrame(eq_curve).set_index('ts')
    return curve, trades, fees_total, pos


def metrics(curve, fees):
    daily = curve.equity.resample('1D').last().ffill()
    r = daily.pct_change()
    r.iloc[0] = daily.iloc[0] / CASH0 - 1
    dd = (daily / daily.cummax().clip(lower=CASH0) - 1)
    std = r.std(ddof=1)
    dn = np.sqrt(np.mean(np.minimum(r, 0) ** 2))
    return {
        'total_return_pct': round((daily.iloc[-1] / CASH0 - 1) * 100, 4),
        'net_pnl': round(daily.iloc[-1] - CASH0, 4),
        'max_drawdown_pct': round(dd.min() * 100, 4),
        'sharpe_daily_ann': round(r.mean() / std * np.sqrt(365), 4) if std > 0 else None,
        'sortino_daily_ann': round(r.mean() / dn * np.sqrt(365), 4) if dn > 0 else None,
        'daily_observations': int(len(daily)),
        'fees_slippage': round(fees, 4),
        'open_positions_end': None,  # filled by caller
    }


def main():
    frames = {s: load4h(s) for s in ['RQQQUSDT', 'RSPYUSDT', 'RAAPLUSDT', 'RTSLAUSDT']}
    names = {'RQQQUSDT': 'RQQQ', 'RSPYUSDT': 'RSPY', 'RAAPLUSDT': 'RAAPL', 'RTSLAUSDT': 'RTSLA'}
    frames = {names[k]: v for k, v in frames.items()}
    out = {}
    Path('reports/is-oos-4h').mkdir(parents=True, exist_ok=True)
    for label, start, end in [
        ('is_2026-06-01_2026-08-17', '2026-06-01', '2026-08-18'),
        ('oos_2026-08-18_2026-09-16', '2026-08-18', '2026-09-16')]:
        for stress in (False, True):
            key = label + ('_stress' if stress else '')
            fee = 15e-4 if stress else FEE
            slip = 5e-4 if stress else SLIP
            curve, trades, fees, pos = backtest(frames, start, end, fee, slip)
            m = metrics(curve, fees)
            m['closed_trades'] = len(trades)
            m['win_rate'] = round(sum(t['pnl'] > 0 for t in trades) / len(trades), 4) if trades else None
            m['open_positions_end'] = {k: round(v, 4) for k, v in pos.items() if v > 0}
            out[key] = m
            print(key, json.dumps(m), flush=True)
            curve.to_csv(f'reports/is-oos-4h/{key}_equity.csv')
            import csv
            with open(f'reports/is-oos-4h/{key}_trades.csv', 'w', newline='') as fh:
                w = csv.DictWriter(fh, fieldnames=['sym', 'exit', 'reason', 'pnl'])
                w.writeheader()
                for t in trades:
                    w.writerow({**t, 'exit': str(t['exit'])})
    Path('reports/is-oos-4h/summary.json').write_text(json.dumps(out, indent=1))
    print('BACKTEST_OK')


if __name__ == '__main__':
    main()
