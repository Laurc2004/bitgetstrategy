"""Long-only spot research: completed-bar signals, shared cash, next-bar execution."""
from dataclasses import dataclass, asdict
from pathlib import Path
from html import escape
import math

import numpy as np
import pandas as pd

from .portfolio import Position
from .report import metrics, write_json


SYMBOLS = ('QQQ', 'SPY', 'AAPL', 'TSLA')


@dataclass(frozen=True)
class Settings:
    family: str = 'trend'
    fast: int = 6
    slow: int = 18
    initial_cash: float = 10000.
    fee_bps: float = 10.
    slippage_bps: float = 2.
    participation: float = .01
    step: float = .01
    min_order: float = 5.
    symbol_weight: float = .20
    daily_vol_target: float = .02
    trailing_stop: float = .08
    drawdown_stop: float = .10
    order_minutes: int = 30


def completed_bars(raw):
    result = raw.copy()
    result.index = result.index + pd.Timedelta(minutes=1)
    return result


def audit_bars(frame, start, end):
    x = frame.loc[(frame.index >= start) & (frame.index < end)]
    expected = pd.date_range(start.normalize(), end, freq='1D', inclusive='left')
    daily = x.groupby(x.index.normalize()).agg(minutes=('close', 'size'), volume=('volume', 'sum'))
    gaps = x.index.to_series().diff().dt.total_seconds().div(60)
    jumps = x.close.pct_change().abs()
    return {'observed_minutes': len(x), 'observed_dates': len(daily),
            'missing_dates': [str(d.date()) for d in expected.difference(daily.index)],
            'unobserved_minutes_in_calendar_window': int((end-start).total_seconds()/60)-len(x),
            'max_observed_gap_minutes': float(gaps.max()),
            'zero_volume_minutes': int((x.volume <= 0).sum()),
            'adjacent_observed_price_jumps_over_20pct': int((jumps > .20).sum()),
            'gap_interpretation': 'Unknown closure/data/issuer cause; no tradable bars are imputed.'}


def features(frame, cfg):
    """Use completed 4h buckets only. Missing buckets remain missing, never tradable."""
    active = frame.loc[frame.volume > 0].copy()
    active['observed_at'] = active.index
    bars = active.resample('4h', closed='right', label='right').agg(
        close=('close', 'last'), high=('high', 'max'), low=('low', 'min'),
        count=('close', 'count'), observed_at=('observed_at', 'last'))
    fresh = (bars.index.to_series()-bars.observed_at).dt.total_seconds() <= 300
    good = fresh & (bars['count'] >= 60)
    bars.loc[~good, ['close', 'high', 'low']] = np.nan
    # Windows are fixed calendar buckets; at least 75% need observed, valid prices.
    minimum = lambda n: max(2, math.ceil(n*.75))
    fast = bars.close.rolling(cfg.fast, min_periods=minimum(cfg.fast)).mean()
    slow = bars.close.rolling(cfg.slow, min_periods=minimum(cfg.slow)).mean()
    prior_high = bars.high.shift(1).rolling(cfg.slow, min_periods=minimum(cfg.slow)).max()
    prior_low = bars.low.shift(1).rolling(cfg.fast, min_periods=minimum(cfg.fast)).min()
    returns = bars.close.pct_change(fill_method=None)
    vol = returns.rolling(18, min_periods=12).std()*np.sqrt(6)
    ready = good & vol.notna() & slow.notna()
    if cfg.family == 'breakout':
        enter = (bars.close > prior_high) & ready
        leave = (bars.close < prior_low) & ready
    else:
        enter = (fast > slow) & (bars.close > slow) & ready
        leave = ((fast <= slow) | (bars.close < slow)) & ready
    result = pd.DataFrame({'enter': enter, 'leave': leave, 'ready': ready,
        'scale': (cfg.daily_vol_target/vol.clip(lower=1e-6)).clip(upper=1), 'close': bars.close})
    return result


def simulate(frames, cfg, start, end, benchmark=None):
    names = list(frames)
    idx = pd.date_range(start, end, freq='1min', inclusive='left')
    values = {s: frames[s].reindex(idx)[['high', 'low', 'close', 'volume']].to_numpy() for s in names}
    fs = {s: features(frames[s].loc[frames[s].index < end], cfg).reindex(idx) for s in names}
    fv = {s: fs[s][['enter', 'leave', 'ready', 'scale']].to_numpy() for s in names}
    positions = {s: Position() for s in names}
    marks = {s: 0. for s in names}; seen = {s: None for s in names}
    goals = {}; peaks = {}; cycles = {}; bought = set()
    fills = []; trades = []; orders = []; rows = []; signals = []
    cash = cfg.initial_cash; fees = slip = 0.; highwater = cash; halted = False
    cleanup = end-pd.Timedelta(days=1)
    def floor(q): return max(0., math.floor((q+1e-10)/cfg.step)*cfg.step)
    def equity(): return cash + sum(positions[s].quantity*marks[s] for s in names)
    def order(s, t, target, reason):
        goals[s] = {'at': t, 'target': target, 'reason': reason}
        orders.append({'timestamp': t, 'symbol': s, 'target': target, 'reason': reason})
    for i, t in enumerate(idx):
        valid = {}
        for s in names:
            hi, lo, close, volume = values[s][i]
            if np.isfinite(close):
                marks[s] = close; seen[s] = t
                valid[s] = (hi, lo, close, volume)
        # Process only orders created before this completed minute. Sells precede buys.
        for s in sorted(list(goals), key=lambda k: goals[k]['target'] > positions[k].quantity):
            g = goals[s]; pos = positions[s]
            if t <= g['at']: continue
            buying = g['target'] > pos.quantity + 1e-8
            if buying and (t-g['at']).total_seconds() > cfg.order_minutes*60:
                orders.append({'timestamp': t, 'symbol': s, 'reason': 'buy_expired', 'target': pos.quantity})
                goals.pop(s); continue
            if s not in valid: continue
            hi, lo, close, volume = valid[s]
            if volume <= 0: continue
            amount = floor(min(abs(g['target']-pos.quantity), volume*cfg.participation))
            price = (hi if buying else lo)*(1+(1 if buying else -1)*cfg.slippage_bps/10000)
            if buying: amount = min(amount, floor(cash/(price*(1+cfg.fee_bps/10000))))
            if amount <= 0 or (buying and amount*price < cfg.min_order): continue
            signed = amount if buying else -amount
            if buying and pos.quantity == 0:
                cycles[s] = {'entry_time': t, 'net_pnl': 0., 'fees': 0., 'entry_notional': 0.}
                peaks[s] = close
            fee = amount*price*cfg.fee_bps/10000
            realized = pos.trade(signed, price)
            cash -= signed*price+fee; fees += fee
            slip_cost = amount*abs(price-(hi if buying else lo)); slip += slip_cost
            cycle = cycles[s]; cycle['net_pnl'] += realized-fee; cycle['fees'] += fee
            if buying: cycle['entry_notional'] += amount*price; bought.add(s)
            fills.append({'timestamp': t, 'signal_time': g['at'], 'symbol': s, 'quantity': signed,
                          'price': price, 'fee': fee, 'slippage_cost': slip_cost, 'reason': g['reason']})
            if pos.quantity == 0:
                trades.append({**cycles.pop(s), 'symbol': s, 'exit_time': t, 'reason': g['reason']})
            if abs(pos.quantity-g['target']) < cfg.step/2: goals.pop(s)
            if cash < -1e-6: raise AssertionError('Spot account borrowed cash')
        eq = equity(); highwater = max(highwater, eq)
        if benchmark is None and eq < highwater*(1-cfg.drawdown_stop): halted = True
        for s in names:
            pos = positions[s]; g = goals.get(s)
            if t >= cleanup or halted:
                if pos.quantity > 0 and (g is None or g['target'] != 0):
                    order(s, t, 0., 'planned_end_exit' if t >= cleanup else 'account_stop')
                elif pos.quantity == 0: goals.pop(s, None)
                continue
            if s not in valid: continue
            if benchmark:
                eligible = benchmark == 'equal_hold' or benchmark == s
                if eligible and s not in bought and s not in goals:
                    weight = cfg.symbol_weight if benchmark == 'equal_hold' else cfg.symbol_weight*len(names)
                    order(s, t, floor(cfg.initial_cash*weight/marks[s]), 'buy_hold')
                continue
            if pos.quantity > 0:
                peaks[s] = max(peaks.get(s, marks[s]), marks[s])
                if marks[s] < peaks[s]*(1-cfg.trailing_stop):
                    if g is None or g['target'] != 0: order(s, t, 0., 'trailing_stop')
                    continue
            enter, leave, ready, scale = fv[s][i]
            if pd.isna(ready) or not ready: continue
            signals.append({'timestamp': t, 'symbol': s, 'enter': bool(enter), 'leave': bool(leave), 'scale': scale})
            if leave:
                if pos.quantity > 0 and (g is None or g['target'] != 0): order(s, t, 0., 'signal_exit')
                elif pos.quantity == 0: goals.pop(s, None)
            elif enter and pos.quantity == 0 and s not in goals:
                order(s, t, floor(eq*cfg.symbol_weight*float(scale)/marks[s]), 'trend_entry')
        stale = any(positions[s].quantity > 0 and (seen[s] is None or (t-seen[s]).total_seconds() > 300) for s in names)
        rows.append({'timestamp': t, 'equity': equity(), 'cash': cash, 'stale': stale,
                     'gross_exposure': sum(positions[s].quantity*marks[s] for s in names)})
    curve = pd.DataFrame(rows)
    stats, daily = metrics(curve, cfg.initial_cash)
    price_pnl = sum(p.realized+p.unrealized(marks[s]) for s,p in positions.items())
    residual = stats['net_pnl']-(price_pnl-fees)
    assert abs(residual) < 1e-6, residual
    half = float(curve.loc[curve.timestamp < start+(end-start)/2, 'equity'].iloc[-1])-cfg.initial_cash
    best = max([t['net_pnl'] for t in trades], default=0.)
    stats.pop('max_unhedged_notional', None)
    stats.update(fees=fees, slippage_embedded=slip, price_pnl=price_pnl, accounting_residual=residual,
        closed_cycles=len(trades), fills=len(fills), winning_cycle_fraction=sum(t['net_pnl']>0 for t in trades)/len(trades) if trades else None,
        first_half_pnl=half, second_half_pnl=stats['net_pnl']-half, pnl_excluding_best_trade=stats['net_pnl']-best,
        turnover_over_initial_cash=sum(abs(f['quantity']*f['price']) for f in fills)/cfg.initial_cash,
        average_gross_exposure_pct=float(curve.gross_exposure.mean()/cfg.initial_cash*100),
        unclosed_position=any(p.quantity>0 for p in positions.values()), halted=halted,
        ending_positions={s:p.quantity for s,p in positions.items()})
    return {'stats':stats, 'equity':curve, 'daily':daily, 'fills':pd.DataFrame(fills),
            'trades':pd.DataFrame(trades), 'orders':pd.DataFrame(orders), 'signals':pd.DataFrame(signals)}


def save_result(result, folder, manifest):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    write_json(folder/'summary.json', result['stats']); write_json(folder/'manifest.json', manifest)
    for name in ('equity','daily','fills','trades','orders','signals'):
        result[name].to_csv(folder/(name+'.csv'), index=name=='daily')
    s = result['stats']; curve = result['equity'].equity.to_numpy()
    low, high = min(curve), max(curve); sample = np.append(curve[::max(1,len(curve)//1200)],curve[-1])
    points = ' '.join(f'{i/(len(sample)-1)*1000:.1f},{220-(v-low)/max(high-low,1e-8)*190:.1f}' for i,v in enumerate(sample))
    html = f'''<!doctype html><meta charset="utf-8"><title>现货趋势研究</title>
<style>body{{font:15px/1.7 system-ui;max-width:1100px;margin:30px auto;padding:20px}}td,th{{padding:8px;border:1px solid #ddd}}svg{{width:100%;background:#f3f7fb}}table{{border-collapse:collapse}}</style>
<h1>{escape(manifest['name'])} · {escape(manifest['split'])}</h1>
<p>净损益 {s['net_pnl']:.4f} USDT · 收益 {s['total_return_pct']:.4f}% · 最大回撤 {s['max_drawdown_pct']:.4f}% · 完整交易 {s['closed_cycles']}</p>
<p>真实历史现货研究，非合成演示。四资产共用 10,000 USDT 现金账户，无杠杆、无资金费、闲置现金不计息。缺失分钟不补成交；缺口中的持仓按最后价格估值，可能低估回撤。交易费率、数量单位和公司行动尚未完成历史认证。</p>
<p>信号后下一完整分钟按买入高价／卖出低价加滑点成交，最多使用该分钟 1% 成交量。最后一天预先退出，无法成交的余仓保留并披露。训练搜索存在选择偏差，历史留出并非完全未接触的盲测。</p>
<svg viewBox="0 0 1000 250"><polyline points="{points}" fill="none" stroke="#237c62" stroke-width="2"/></svg><p>净值轴 {low:.2f}–{high:.2f} USDT。</p>
{pd.DataFrame([s]).drop(columns=['ending_positions']).T.to_html(header=False)}
<p><a href="manifest.json">规则与来源</a> · <a href="equity.csv">分钟净值</a> · <a href="daily.csv">每日收益</a> · <a href="fills.csv">成交</a> · <a href="trades.csv">交易</a> · <a href="signals.csv">信号</a></p>'''
    (folder/'report.html').write_text(html, encoding='utf-8')
