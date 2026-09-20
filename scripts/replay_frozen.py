"""Reproduce frozen IS/OOS without selecting any new parameters."""
from pathlib import Path
from dataclasses import replace,asdict
import argparse,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from basis_lab.trend_research import Settings,completed_bars,simulate,save_result
from basis_lab.data.validate import load_bars,utc
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args()
out=Path(a.out)
if out.exists() and any(out.iterdir()):raise ValueError('Choose empty output')
cfg=Settings(**json.loads((ROOT/'configs/frozen.json').read_text()))
expected=json.loads((ROOT/'reports/v2/summary.json').read_text())
sources=json.loads((ROOT/'data/sources.json').read_text());frames={}
for name,record in sources['files'].items():
    path=ROOT/'data/raw'/name
    if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Input differs: '+name)
    frame,_=load_bars(path);frames[name[1:].split('USDT')[0]]=completed_bars(frame)
for label,start,end in [('training','2026-06-19T00:00:00Z','2026-08-18T00:00:00Z'),('holdout','2026-08-18T00:00:00Z','2026-09-17T00:00:00Z')]:
    for stress in (False,True):
        key=label+('_stress' if stress else '')
        c=replace(cfg,fee_bps=15.,slippage_bps=5.) if stress else cfg
        result=simulate(frames,c,utc(start),utc(end))
        for metric in ('net_pnl','fees','closed_cycles','total_return_pct','max_drawdown_pct'):
            if abs(result['stats'][metric]-expected[key][metric])>1e-7:raise AssertionError((key,metric,'does not reproduce'))
        save_result(result,out/key,{'name':expected['selected'],'split':key+'_frozen_replay','config':asdict(c)})
        print(key,'verified',result['stats']['net_pnl'],flush=True)
