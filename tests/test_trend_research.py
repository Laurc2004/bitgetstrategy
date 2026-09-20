import pandas as pd
import numpy as np
from dataclasses import replace
from basis_lab.trend_research import Settings, features, simulate, audit_bars


def bars(start='2026-01-01', days=3):
    idx=pd.date_range(start,periods=days*1440,freq='1min',tz='UTC')
    close=np.linspace(100,110,len(idx))
    return pd.DataFrame({'high':close+.1,'low':close-.1,'close':close,'volume':10000.},index=idx)


def test_next_bar_cash_account_and_end_exit():
    frame=bars();start=frame.index[0];end=start+pd.Timedelta(days=3)
    result=simulate({'QQQ':frame},Settings(),start,end,benchmark='QQQ')
    f=result['fills'];s=result['stats']
    assert (f.timestamp>f.signal_time).all()
    assert f.iloc[0].timestamp==start+pd.Timedelta(minutes=1)
    assert not s['unclosed_position'] and s['closed_cycles']==1
    assert abs(s['accounting_residual'])<1e-8
    assert result['equity'].cash.min()>=0
    assert result['trades'].iloc[0].reason=='planned_end_exit'


def test_missing_exit_liquidity_does_not_fabricate_fill():
    frame=bars();start=frame.index[0];end=start+pd.Timedelta(days=3)
    frame.loc[frame.index>=end-pd.Timedelta(days=1),'volume']=0
    r=simulate({'QQQ':frame},Settings(),start,end,benchmark='QQQ')
    assert r['stats']['unclosed_position'] and r['stats']['closed_cycles']==0
    assert (r['fills'].quantity>0).all()


def test_future_prices_do_not_change_past_signals():
    frame=bars(days=12);cut=frame.index[7*1440]
    a=features(frame,Settings());changed=frame.copy()
    changed.loc[changed.index>cut,['high','low','close']]*=10
    b=features(changed,Settings())
    pd.testing.assert_frame_equal(a.loc[:cut],b.loc[:cut])


def test_breakout_excludes_current_bucket_from_threshold():
    frame=bars(days=12)
    f=features(frame,Settings(family='breakout'))
    assert f.enter.any()


def test_stress_costs_and_shared_cash_capacity():
    frame=bars();start=frame.index[0];end=start+pd.Timedelta(days=3)
    frames={s:frame for s in ('QQQ','SPY','AAPL','TSLA')}
    cfg=Settings()
    a=simulate(frames,cfg,start,end,benchmark='equal_hold')
    b=simulate(frames,replace(cfg,fee_bps=15,slippage_bps=5),start,end,benchmark='equal_hold')
    assert a['stats']['net_pnl']>b['stats']['net_pnl']
    assert a['equity'].cash.min()>=0
    assert (a['fills'].quantity.abs()<=frame.volume.iloc[0]*cfg.participation).all()


def test_gap_audit_reports_missing_date():
    frame=bars();start=frame.index[0];end=start+pd.Timedelta(days=3)
    frame=frame.loc[frame.index.normalize()!=start+pd.Timedelta(days=1)]
    a=audit_bars(frame,start,end)
    assert a['missing_dates']==['2026-01-02']
    assert a['max_observed_gap_minutes']==1441


def test_trailing_stop_submits_then_fills_next_minute(monkeypatch):
    frame=bars();start=frame.index[0];end=start+pd.Timedelta(days=3)
    frame[['high','low','close']]=100.
    frame.loc[frame.index>=start+pd.Timedelta(minutes=2),['high','low','close']]=90.
    signal=pd.DataFrame({'enter':[True],'leave':[False],'ready':[True],'scale':[1.]},index=[start])
    monkeypatch.setattr('basis_lab.trend_research.features',lambda frame,cfg:signal)
    r=simulate({'QQQ':frame},Settings(),start,end)
    assert len(r['fills'])==2
    assert r['fills'].iloc[1].timestamp==start+pd.Timedelta(minutes=3)
    assert r['fills'].iloc[1].reason=='trailing_stop'
    assert r['stats']['net_pnl']<0


def test_partial_buys_respect_capacity_then_expire():
    frame=bars();frame['volume']=10.
    start=frame.index[0];end=start+pd.Timedelta(days=3)
    r=simulate({'QQQ':frame},Settings(),start,end,benchmark='QQQ')
    buys=r['fills'].loc[r['fills'].quantity>0]
    assert len(buys)==30
    assert (buys.quantity<=.1+1e-9).all()
    assert 'buy_expired' in set(r['orders'].reason)
    assert not r['stats']['unclosed_position']


def test_confirmation_requires_consecutive_completed_signals():
    frame=bars(days=12)
    one=features(frame,Settings(family='breakout',confirmation_bars=1))
    two=features(frame,Settings(family='breakout',confirmation_bars=2))
    expected=one.enter & one.enter.shift(1,fill_value=False)
    pd.testing.assert_series_equal(two.enter,expected)
    assert two.enter.sum()<one.enter.sum()


def test_hold_confirmation_accepts_retest_without_second_new_high():
    frame=bars(days=12)
    t=frame.index[-1].floor('4h')
    previous=float(frame.loc[t-pd.Timedelta(hours=4),'close'])
    mask=(frame.index>t-pd.Timedelta(hours=4))&(frame.index<=t)
    frame.loc[mask,['high','low','close']]=previous-.01
    fresh=features(frame,Settings(family='breakout',confirmation_bars=2))
    hold=features(frame,Settings(family='breakout',confirmation_bars=2,confirmation_mode='hold_level'))
    assert not fresh.loc[t,'enter']
    assert hold.loc[t,'enter']
    changed=frame.copy();changed.loc[changed.index>t,['high','low','close']]*=100
    pd.testing.assert_frame_equal(hold.loc[:t],features(changed,Settings(family='breakout',confirmation_bars=2,confirmation_mode='hold_level')).loc[:t])
