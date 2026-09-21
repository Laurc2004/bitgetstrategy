"""Durable, public-data-only forward paper account. No exchange order API."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import math
import os
import sqlite3

import pandas as pd

from .portfolio import Position
from .trend_research import Settings, SYMBOLS, features


def stamp(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError('Timezone required')
    return t.tz_convert('UTC')


def iso(value):
    return stamp(value).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8')
    os.replace(temp, path)


def initial_state(cfg, started):
    return dict(started_at=iso(started), last_bar=iso(stamp(started).floor('min')),
                cash=cfg.initial_cash, fees=0., highwater=cfg.initial_cash, max_drawdown_pct=0.,
                halted=False, positions={s: asdict(Position()) for s in SYMBOLS},
                marks={s: None for s in SYMBOLS}, seen={s: None for s in SYMBOLS},
                goals={}, peaks={}, cycles={}, closed_cycles=0, fills_count=0, decisions={})


def equity(state):
    return state['cash'] + sum(p['quantity']*(state['marks'][s] or 0.)
                               for s, p in state['positions'].items())


def step(state, cfg, completed_at, bars, signals, received_at):
    """One completed minute, at actual observation time. Never backdate an order.

    Bars older than 120 seconds can update marks only. An order can only fill on
    a full minute STARTING after its actual creation time. This is deliberately
    stricter than the historical next-minute model, which assumes zero latency.
    """
    t, now = stamp(completed_at), stamp(received_at)
    if t <= stamp(state['last_bar']) or t > now or t <= stamp(state['started_at']):
        return []
    events = []
    fresh = 0 <= (now-t).total_seconds() <= 120
    positions = {s: Position(**p) for s, p in state['positions'].items()}
    floor = lambda q: max(0., math.floor((q+1e-10)/cfg.step)*cfg.step)

    def emit(kind, s=None, **kw):
        events.append(dict(kind=kind, symbol=s, timestamp=iso(t), observed_at=iso(now), **kw))

    def order(s, target, reason):
        state['goals'][s] = dict(created_at=iso(now), signal_time=iso(t), target=target, reason=reason)
        emit('order', s, target=target, reason=reason, created_at=iso(now))

    for s, b in bars.items():
        state['marks'][s], state['seen'][s] = b['close'], iso(t)
    # Expire buys by wall clock, even when their symbol has no bars.
    for s in sorted(list(state['goals']), key=lambda k: state['goals'][k]['target'] > positions[k].quantity):
        g, p = state['goals'][s], positions[s]
        buying = g['target'] > p.quantity+1e-8
        if buying and (now-stamp(g['created_at'])).total_seconds() > cfg.order_minutes*60:
            emit('cancel', s, reason='buy_expired'); state['goals'].pop(s); continue
        if not fresh or s not in bars or t-pd.Timedelta(minutes=1) < stamp(g['created_at']):
            continue
        b = bars[s]
        price = b['high' if buying else 'low']*(1+(1 if buying else -1)*cfg.slippage_bps/10000)
        amount = floor(min(abs(g['target']-p.quantity), b['volume']*cfg.participation))
        if buying:
            amount = min(amount, floor(state['cash']/(price*(1+cfg.fee_bps/10000))))
        if amount <= 0 or (buying and amount*price < cfg.min_order):
            continue
        if buying and p.quantity == 0:
            state['cycles'][s] = dict(entry_time=iso(t), net_pnl=0., fees=0.)
            state['peaks'][s] = b['close']
        quantity = amount if buying else -amount
        fee = amount*price*cfg.fee_bps/10000
        realized = p.trade(quantity, price)
        state['cash'] -= quantity*price+fee
        state['fees'] += fee
        state['fills_count'] += 1
        cycle = state['cycles'][s]
        cycle['net_pnl'] += realized-fee
        cycle['fees'] += fee
        emit('fill', s, quantity=quantity, price=price, fee=fee, reason=g['reason'],
             signal_time=g['signal_time'], order_created_at=g['created_at'])
        if p.quantity == 0:
            emit('trade', s, **state['cycles'].pop(s), reason=g['reason'])
            state['closed_cycles'] += 1
        if abs(p.quantity-g['target']) < cfg.step/2:
            state['goals'].pop(s)
    state['positions'] = {s: asdict(p) for s, p in positions.items()}
    eq = equity(state)
    state['highwater'] = max(state['highwater'], eq)
    state['max_drawdown_pct'] = min(state['max_drawdown_pct'], (eq/state['highwater']-1)*100)
    if eq < state['highwater']*(1-cfg.drawdown_stop):
        state['halted'] = True
    for s, p in positions.items():
        g = state['goals'].get(s)
        if state['halted']:
            if p.quantity > 0 and (g is None or g['target'] != 0):
                order(s, 0., 'account_stop')
            elif p.quantity == 0:
                state['goals'].pop(s, None)
            continue
        if s not in bars or not fresh:
            continue
        if p.quantity > 0:
            state['peaks'][s] = max(state['peaks'].get(s, bars[s]['close']), bars[s]['close'])
            if bars[s]['close'] < state['peaks'][s]*(1-cfg.trailing_stop):
                if g is None or g['target'] != 0:
                    order(s, 0., 'trailing_stop')
                continue
        signal = signals.get(s)
        if signal is None:
            continue
        decision = dict(timestamp=iso(t), observed_at=iso(now), **signal)
        state['decisions'][s] = decision
        emit('signal', s, **signal)
        if not signal['ready']:
            continue
        if signal['leave']:
            if p.quantity > 0 and (g is None or g['target'] != 0):
                order(s, 0., 'signal_exit')
            elif p.quantity == 0:
                state['goals'].pop(s, None)
        elif signal['enter'] and p.quantity == 0 and s not in state['goals']:
            order(s, floor(eq*cfg.symbol_weight*signal['scale']/bars[s]['close']), 'breakout_entry')
    state['last_bar'] = iso(t)
    assert state['cash'] >= -1e-6
    residual = equity(state)-cfg.initial_cash-(sum(p.realized+p.unrealized(state['marks'][s] or 0.)
                for s, p in positions.items())-state['fees'])
    assert abs(residual) < 1e-6, residual
    return events


def parse_candles(rows, observed_at):
    """Normalize only completed, finite, consistent minute candles."""
    cutoff = int(stamp(observed_at).timestamp()*1000)-1000
    result = {}
    for row in rows:
        ts = int(row[0]); o, h, l, c, v = map(float, row[1:6])
        if ts+60000 > cutoff:
            continue
        if ts % 60000 or not all(math.isfinite(x) for x in (o,h,l,c,v)):
            raise ValueError('Invalid candle timestamp or nonfinite value')
        if min(o,h,l,c) <= 0 or v < 0 or h < max(o,l,c) or l > min(o,h,c):
            raise ValueError('Invalid candle OHLC/volume')
        values = [o,h,l,c,v]
        if ts in result and result[ts] != values:
            raise ValueError('Conflicting candle in response')
        result[ts] = values
    return result


class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.protocol = json.loads((self.folder/'protocol.json').read_text(encoding='utf-8'))
        self.cfg = Settings(**self.protocol['strategy'])
        self.db = sqlite3.connect(self.folder/'account.sqlite')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS bars(symbol TEXT,ts INTEGER,o REAL,h REAL,l REAL,c REAL,v REAL,
            first_seen TEXT,PRIMARY KEY(symbol,ts));
          CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,data TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS curve(ts TEXT PRIMARY KEY,equity REAL,cash REAL);
          CREATE TABLE IF NOT EXISTS checkpoint(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL);
        ''')
        row = self.db.execute('SELECT data FROM checkpoint WHERE id=1').fetchone()
        self.state = json.loads(row[0]) if row else initial_state(self.cfg, self.protocol['started_at'])

    def ingest(self, batches, observed_at, warmup=False):
        state = json.loads(json.dumps(self.state))
        inserted = conflicts = 0
        with self.db:
            for s, rows in batches.items():
                for ts, vals in parse_candles(rows, observed_at).items():
                    old = self.db.execute('SELECT o,h,l,c,v FROM bars WHERE symbol=? AND ts=?', (s,ts)).fetchone()
                    if old is not None:
                        conflicts += list(old) != vals
                        continue  # first observation wins; never rewrite a used candle
                    self.db.execute('INSERT INTO bars VALUES (?,?,?,?,?,?,?,?)', (s,ts,*vals,iso(observed_at)))
                    inserted += 1
            frames, signals = {}, {}
            lower = int((stamp(observed_at)-pd.Timedelta(days=12)).timestamp()*1000)
            for s in SYMBOLS:
                rows = self.db.execute('SELECT ts,o,h,l,c,v FROM bars WHERE symbol=? AND ts>=? ORDER BY ts', (s,lower)).fetchall()
                f = pd.DataFrame(rows, columns=['timestamp','open','high','low','close','volume'])
                f.index = pd.to_datetime(f.pop('timestamp'), unit='ms', utc=True)+pd.Timedelta(minutes=1)
                frames[s] = f
                signals[s] = features(f, self.cfg) if not f.empty else pd.DataFrame()
            if not warmup:
                for s,g in list(state['goals'].items()):
                    if (g['target'] > state['positions'][s]['quantity'] and
                        (stamp(observed_at)-stamp(g['created_at'])).total_seconds() > self.cfg.order_minutes*60):
                        event=dict(kind='cancel',symbol=s,timestamp=iso(observed_at),observed_at=iso(observed_at),reason='buy_expired')
                        self.db.execute('INSERT INTO events(data) VALUES (?)',(json.dumps(event),))
                        state['goals'].pop(s)
                idx = sorted(set(t for f in frames.values() for t in f.index if t > stamp(state['last_bar'])))
                for t in idx:
                    bars = {s: f.loc[t].to_dict() for s,f in frames.items() if t in f.index}
                    fs = {s: self.signal_row(f.loc[t]) for s,f in signals.items() if t in f.index}
                    for event in step(state, self.cfg, t, bars, fs, observed_at):
                        self.db.execute('INSERT INTO events(data) VALUES (?)', (json.dumps(event),))
                    self.db.execute('INSERT OR IGNORE INTO curve VALUES (?,?,?)', (iso(t),equity(state),state['cash']))
            self.db.execute('INSERT OR REPLACE INTO checkpoint VALUES (1,?)', (json.dumps(state),))
        self.state = state
        return dict(inserted=inserted, conflicting_reobservations=conflicts)

    @staticmethod
    def signal_row(row):
        return dict(enter=bool(row['enter']), leave=bool(row['leave']), ready=bool(row['ready']),
                    scale=float(row['scale']) if pd.notna(row['scale']) else 0.)

    def dashboard(self, quotes, status, errors, now):
        state = self.state
        rows = []
        for s in SYMBOLS:
            p = state['positions'][s]
            rows.append(dict(symbol=s, **p, mark=state['marks'][s], mark_at=state['seen'][s],
                             quote=quotes.get(s), signal=state['decisions'].get(s),
                             pending=state['goals'].get(s), peak=state['peaks'].get(s),
                             bars=self.db.execute('SELECT COUNT(*) FROM bars WHERE symbol=?',(s,)).fetchone()[0]))
        events = [json.loads(r[0]) for r in self.db.execute('SELECT data FROM events ORDER BY id DESC LIMIT 200')]
        curve = [dict(timestamp=r[0],equity=r[1],cash=r[2]) for r in self.db.execute('SELECT * FROM curve ORDER BY ts')]
        if len(curve)>2000:
            curve = curve[::math.ceil(len(curve)/2000)]+[curve[-1]]
        return dict(mode='forward_paper', generated_at=iso(now), status=status, errors=errors,
                    protocol=self.protocol, equity=equity(state), cash=state['cash'], fees=state['fees'],
                    net_pnl=equity(state)-self.cfg.initial_cash, max_drawdown_pct=state['max_drawdown_pct'],
                    closed_cycles=state['closed_cycles'], fills_count=state['fills_count'], halted=state['halted'],
                    symbols=rows, events=events, curve=curve, last_bar=state['last_bar'])
