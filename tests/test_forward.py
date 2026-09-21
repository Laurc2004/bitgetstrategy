from dataclasses import asdict
import json

import pandas as pd
import pytest

from basis_lab.forward import Store, initial_state, step, parse_candles, equity
from basis_lab.trend_research import Settings


START = pd.Timestamp('2026-09-21T00:00:00Z')
CFG = Settings(family='breakout',fast=18,confirmation_bars=2,confirmation_mode='hold_level')
BAR = dict(open=100.,high=101.,low=99.,close=100.,volume=10000.)
ENTER = dict(enter=True,leave=False,ready=True,scale=1.)


def test_receipt_time_prevents_backdated_fill_and_repeated_minute():
    state=initial_state(CFG,START)
    t=START+pd.Timedelta(minutes=1)
    observed=t+pd.Timedelta(seconds=15)
    events=step(state,CFG,t,{'QQQ':BAR},{'QQQ':ENTER},observed)
    assert [e['kind'] for e in events]==['signal','order']
    assert state['goals']['QQQ']['created_at']==observed.isoformat()
    # The next minute started before the signal was actually available.
    assert not step(state,CFG,t+pd.Timedelta(minutes=1),{'QQQ':BAR},{},observed+pd.Timedelta(minutes=1))
    events=step(state,CFG,t+pd.Timedelta(minutes=2),{'QQQ':BAR},{},observed+pd.Timedelta(minutes=2))
    fill=next(e for e in events if e['kind']=='fill')
    assert fill['quantity']>0 and fill['fee']>0
    assert state['cash']>=0 and abs(equity(state)-10000)>0
    assert not step(state,CFG,t+pd.Timedelta(minutes=2),{'QQQ':BAR},{},observed+pd.Timedelta(minutes=2))
    assert state['fills_count']==1


def test_late_bars_never_fill_and_buy_expires():
    state=initial_state(CFG,START)
    t=START+pd.Timedelta(minutes=1)
    step(state,CFG,t,{'QQQ':BAR},{'QQQ':ENTER},t)
    events=step(state,CFG,t+pd.Timedelta(minutes=2),{'QQQ':BAR},{},t+pd.Timedelta(minutes=10))
    assert not any(e['kind']=='fill' for e in events)
    events=step(state,CFG,t+pd.Timedelta(minutes=31),{}, {},t+pd.Timedelta(minutes=31))
    assert events[0]['reason']=='buy_expired'
    assert not state['goals'] and state['cash']==10000


def test_zero_volume_does_not_fill_and_stop_exits_on_later_bar():
    state=initial_state(CFG,START);t=START+pd.Timedelta(minutes=1)
    step(state,CFG,t,{'QQQ':BAR},{'QQQ':ENTER},t)
    step(state,CFG,t+pd.Timedelta(minutes=1),{'QQQ':{**BAR,'volume':0}},{},t+pd.Timedelta(minutes=1))
    assert state['fills_count']==0
    step(state,CFG,t+pd.Timedelta(minutes=2),{'QQQ':BAR},{},t+pd.Timedelta(minutes=2))
    down=dict(open=90.,high=90.,low=90.,close=90.,volume=10000.)
    events=step(state,CFG,t+pd.Timedelta(minutes=3),{'QQQ':down},{},t+pd.Timedelta(minutes=3))
    assert any(e.get('reason')=='trailing_stop' for e in events)
    step(state,CFG,t+pd.Timedelta(minutes=4),{'QQQ':down},{},t+pd.Timedelta(minutes=4))
    assert state['positions']['QQQ']['quantity']==0 and state['closed_cycles']==1
    assert equity(state)<10000


def test_unfinished_invalid_and_conflicting_candles():
    ts=int(START.timestamp()*1000)
    row=[ts,100,101,99,100,10]
    assert not parse_candles([row],START+pd.Timedelta(seconds=45))
    assert len(parse_candles([row,row],START+pd.Timedelta(seconds=62)))==1
    with pytest.raises(ValueError):parse_candles([row,[ts,100,101,99,100,20]],START+pd.Timedelta(minutes=2))
    with pytest.raises(ValueError):parse_candles([[ts,100,90,99,100,10]],START+pd.Timedelta(minutes=2))


def test_restart_idempotence_and_no_warmup_pnl(tmp_path):
    (tmp_path/'protocol.json').write_text(json.dumps(dict(strategy=asdict(CFG),started_at=START.isoformat())))
    store=Store(tmp_path);ts=int(START.timestamp()*1000)
    warm=[[ts-60000,100,101,99,100,10]]
    store.ingest({'QQQ':warm},START+pd.Timedelta(seconds=2),warmup=True)
    assert store.state['fills_count']==0 and equity(store.state)==10000
    rows=[[ts,100,101,99,100,10],[ts+60000,100,101,99,100,10]]
    now=START+pd.Timedelta(minutes=2,seconds=2)
    store.ingest({'QQQ':rows},now)
    state=json.loads(json.dumps(store.state));store.db.close()
    restored=Store(tmp_path)
    assert restored.state==state
    result=restored.ingest({'QQQ':rows},now)
    assert result['inserted']==0 and restored.state==state
    conflict=restored.ingest({'QQQ':[[ts,100,101,99,100,20]]},now)
    assert conflict['conflicting_reobservations']==1
    assert restored.db.execute('SELECT v FROM bars WHERE ts=?',(ts,)).fetchone()[0]==10
    restored.db.close()
