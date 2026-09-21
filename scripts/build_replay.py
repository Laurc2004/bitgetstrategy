"""Export a compact interactive replay from the fixed v3 ledger and source bars."""
from pathlib import Path
import json
import sys

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from basis_lab.forward import atomic_json, iso
from basis_lab.trend_research import Settings, completed_bars, features, SYMBOLS
from basis_lab.data.validate import load_bars
from basis_lab.portfolio import Position


def build():
    report=ROOT/'reports/v3/hold_level-exit18-stop8/base'
    cfg=Settings(**json.loads((ROOT/'configs/development-v3.json').read_text()))
    curve=pd.read_csv(report/'equity.csv',parse_dates=['timestamp'])
    curve['drawdown']=(curve.equity/curve.equity.cummax().clip(lower=10000)-1).cummin()*100
    fills=pd.read_csv(report/'fills.csv',parse_dates=['timestamp','signal_time'])
    orders=pd.read_csv(report/'orders.csv',parse_dates=['timestamp'])
    trades=pd.read_csv(report/'trades.csv',parse_dates=['entry_time','exit_time'])
    frames={}; signals={}
    for s in SYMBOLS:
        raw,_=load_bars(ROOT/'data/raw'/('R'+s+'USDT_spot.jsonl'))
        frames[s]=completed_bars(raw)
        signals[s]=features(frames[s],cfg)
    timeline=list(pd.date_range(curve.timestamp.iloc[0],curve.timestamp.iloc[-1],freq='4h'))
    # Include every actual fill time so "next trade" lands on the transaction.
    timeline=sorted(set(timeline+list(fills.timestamp)+[curve.timestamp.iloc[-1]]))
    positions={s:Position() for s in SYMBOLS}; snapshots=[]; fill_idx=0
    records=fills.to_dict('records'); fees=0.
    for t in timeline:
        while fill_idx<len(records) and records[fill_idx]['timestamp']<=t:
            f=records[fill_idx];positions[f['symbol']].trade(f['quantity'],f['price']);fees+=f['fee'];fill_idx+=1
        account=curve.loc[curve.timestamp<=t].iloc[-1]
        rows=[]
        for s in SYMBOLS:
            bars=frames[s].loc[:t];fs=signals[s].loc[:t];p=positions[s]
            sig=None
            if not fs.empty:
                r=fs.iloc[-1]
                sig=dict(timestamp=iso(fs.index[-1]),ready=bool(r.ready),enter=bool(r.enter),leave=bool(r.leave),
                         scale=float(r.scale) if pd.notna(r.scale) else 0.)
            price=float(bars.close.iloc[-1]) if not bars.empty else None
            rows.append(dict(symbol=s,quantity=p.quantity,average=p.average,realized=p.realized,mark=price,
                             mark_at=iso(bars.index[-1]) if not bars.empty else None,signal=sig,quote=None,pending=None))
        snapshots.append(dict(timestamp=iso(t),equity=float(account.equity),cash=float(account.cash),
                              fees=fees,fills_count=fill_idx,max_drawdown_pct=float(account.drawdown),stale=bool(account.stale),symbols=rows))
    events=[]
    for f in records:
        events.append(dict(kind='fill',**{k:iso(v) if isinstance(v,pd.Timestamp) else v for k,v in f.items()}))
    for o in orders.to_dict('records'):
        events.append(dict(kind='order',**{k:iso(v) if isinstance(v,pd.Timestamp) else v for k,v in o.items()}))
    for tr in trades.to_dict('records'):
        events.append(dict(kind='trade',timestamp=iso(tr['exit_time']),**{k:iso(v) if isinstance(v,pd.Timestamp) else v for k,v in tr.items()}))
    events.sort(key=lambda e:e['timestamp'])
    output=dict(mode='historical_development',name='hold_level-exit18-stop8',start=iso(timeline[0]),end=iso(timeline[-1]),
                summary=json.loads((report/'summary.json').read_text()),snapshots=snapshots,events=events,
                sources=['reports/v3/hold_level-exit18-stop8/base/equity.csv','reports/v3/hold_level-exit18-stop8/base/fills.csv'])
    atomic_json(ROOT/'data/replay.json',output)
    print('Exported',len(snapshots),'replay steps;',len(events),'events')


if __name__=='__main__':build()
