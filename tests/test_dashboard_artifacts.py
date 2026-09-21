"""Cross-check displayed account metrics against the independent CSV ledger."""
from pathlib import Path
import hashlib
import json

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]


def test_replay_account_matches_minute_ledger_at_every_exported_step():
    replay=json.loads((ROOT/'data/replay.json').read_text(encoding='utf-8'))
    report=ROOT/'reports/v3/hold_level-exit18-stop8/base'
    curve=pd.read_csv(report/'equity.csv',parse_dates=['timestamp']).set_index('timestamp')
    fills=pd.read_csv(report/'fills.csv',parse_dates=['timestamp'])
    dd=(curve.equity/curve.equity.cummax().clip(lower=10000)-1).cummin()*100
    for snap in replay['snapshots']:
        t=pd.Timestamp(snap['timestamp']);ledger=curve.loc[t];past=fills.loc[fills.timestamp<=t]
        assert abs(snap['equity']-ledger.equity)<1e-7
        assert abs(snap['cash']-ledger.cash)<1e-7
        assert abs(snap['max_drawdown_pct']-dd.loc[t])<1e-7
        assert abs(snap['fees']-past.fee.sum())<1e-7
        for row in snap['symbols']:
            assert abs(row['quantity']-past.loc[past.symbol==row['symbol'],'quantity'].sum())<1e-7
    assert len([e for e in replay['events'] if e['kind']=='trade'])==12


def test_published_forward_freeze_matches_configuration_and_distinct_account():
    freeze=json.loads((ROOT/'configs/forward-v3-freeze.json').read_text(encoding='utf-8'))
    snapshot=json.loads((ROOT/'data/live.json').read_text(encoding='utf-8'))
    config=ROOT/'configs/development-v3.json'
    assert freeze['config_sha256']==hashlib.sha256(config.read_bytes()).hexdigest()
    assert freeze['strategy']==json.loads(config.read_text(encoding='utf-8'))
    assert snapshot['protocol']==freeze
    assert snapshot['publication']=='STATIC_SNAPSHOT_NOT_A_LIVE_CONNECTION'
    assert pd.Timestamp(freeze['started_at'])>pd.Timestamp('2026-09-17T00:00:00Z')
    assert all(pd.Timestamp(e['timestamp'])>pd.Timestamp(freeze['started_at']) for e in snapshot['events'])
