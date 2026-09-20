"""Reproduce selected v3 development results, not a new out-of-sample test."""
from pathlib import Path
from dataclasses import replace,asdict
import argparse,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from basis_lab.trend_research import Settings,completed_bars,simulate,save_result
from basis_lab.data.validate import load_bars,utc
p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();out=Path(a.out)
if out.exists() and any(out.iterdir()):raise ValueError('Choose empty output')
cfg=Settings(**json.loads((ROOT/'configs/development-v3.json').read_text(encoding='utf-8')))
expected=json.loads((ROOT/'reports/v3/summary.json').read_text(encoding='utf-8'))
sources=json.loads((ROOT/'data/sources.json').read_text(encoding='utf-8'));frames={}
for name,record in sources['files'].items():
    path=ROOT/'data/raw'/name
    if hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Input mismatch: '+name)
    frame,_=load_bars(path);frames[name[1:].split('USDT')[0]]=completed_bars(frame)
for key,c in [('development',cfg),('development_stress',replace(cfg,fee_bps=15.,slippage_bps=5.))]:
    r=simulate(frames,c,utc(expected['window_start']),utc(expected['window_end']))
    for metric in ('net_pnl','fees','closed_cycles','max_drawdown_pct','total_return_pct'):
        if abs(r['stats'][metric]-expected[key][metric])>1e-7:raise AssertionError((key,metric,'does not reproduce'))
    save_result(r,out/key,{'name':expected['selected'],'split':'OBSERVED_DEVELOPMENT_REPLAY','config':asdict(c)})
    print(key,'verified',r['stats']['net_pnl'],flush=True)
