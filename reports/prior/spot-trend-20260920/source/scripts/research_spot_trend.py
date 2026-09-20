"""Bounded, preregistered four-rule spot trend experiment."""
from dataclasses import asdict, replace
from pathlib import Path
import argparse
import sys

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from basis_lab.data.validate import load_bars, sha256, utc
from basis_lab.report import write_json
from basis_lab.trend_research import SYMBOLS, Settings, completed_bars, audit_bars, simulate, save_result

START=utc('2026-06-19T00:00:00Z')
END=utc('2026-08-18T00:00:00Z')
OOS_END=utc('2026-09-17T00:00:00Z')


def run(out, data=None):
    out=Path(out)
    if out.exists() and any(out.iterdir()): raise ValueError('Choose an empty output directory')
    out.mkdir(parents=True,exist_ok=True)
    data=Path(data or ROOT/'review-weekend-bounce/reproduce/pair_1m')
    grid=[Settings(family=f,fast=fast,slow=slow) for f in ('trend','breakout') for fast,slow in ((6,18),(12,36))]
    source_paths=[Path(__file__),ROOT/'src/basis_lab/trend_research.py',ROOT/'src/basis_lab/portfolio.py',ROOT/'src/basis_lab/report.py',ROOT/'src/basis_lab/data/validate.py']
    source={str(p.relative_to(ROOT)):sha256(p) for p in source_paths}
    protocol={'created_at':str(pd.Timestamp.now(tz='UTC')),'symbols':SYMBOLS,
        'train_start':START,'train_end':END,'holdout_end':OOS_END,'variants':[asdict(c) for c in grid],
        'maximum_training_strategy_trials':4,'source_hashes':source,
        'selection':'>=5 closed cycles, positive net PnL and both 30d training halves, positive after removing best trade, flat end, no account halt. Rank by training Sharpe (descending), tie by name. Stress qualified candidates only at 15bp fee/5bp slippage; first positive, flat, nonhalted candidate selected. Freeze selection before ONE historical holdout. Never choose a different candidate from holdout outcome.',
        'signals':'Completed 4h buckets: >=60 active minutes, last observed <=5min old. Rolling fixed calendar windows require >=75% valid buckets. Trend: fast MA > slow MA and close > slow; exit inverse. Breakout: close above PRIOR slow-window high; exit below PRIOR fast-window low. Volatility: 18 buckets, >=12 contiguous observed returns; size down to target 2% daily proxy vol.',
        'execution':'Shared cash, spot long-only; 20% equity cap per initial position, at most four positions. No periodic rebalancing. Fill on next completed minute high/low +2bp, 10bp fee each way, 1% observed minute volume, .01 token step assumption, 5USDT minimum buy. Buy targets expire after30min; sells persist. Close-based 8% trailing stop and10% account drawdown halt submit NEXT-minute exits. Orders may gap and exceed stops. Planned liquidation during final24h for ALL strategies/benchmarks; no terminal fictitious fills.',
        'baselines':'Equal hold at20% per symbol; QQQ hold80%; SPY hold80%; cash0%yield. Same fees, capacity, price rules and end-window exit. Buy-hold has no strategy stop or volatility sizing; report actual exposure for fair interpretation.',
        'limitations':'Exploratory research, not exchange-certified simulation. Raw token units/volume, fee schedule, minima and corporate actions not historically verified. Data gaps flagged without imputation; stale marks may understate risk. Prior project/team material exposed some historical holdout information; not pristine blind validation. These four trials add to earlier149 trials; no erased failures. No likelihood of profit inferred from papers.'}
    write_json(out/'protocol.json',protocol)
    for p in source_paths:
        dst=out/'source'/p.relative_to(ROOT); dst.parent.mkdir(parents=True,exist_ok=True); dst.write_bytes(p.read_bytes())
    frames={};audits={}
    for s in SYMBOLS:
        bars, audit=load_bars(data/f'R{s}USDT_spot.jsonl')
        frames[s]=completed_bars(bars)
        audits[s]={'source':audit,'training':audit_bars(frames[s],START,END)}
    write_json(out/'data_audit.json',audits)
    results=[]; qualified=[]; training={s:f.loc[f.index<END] for s,f in frames.items()}
    for cfg in grid:
        name=f'{cfg.family}-{cfg.fast}-{cfg.slow}'
        result=simulate(training,cfg,START,END)
        s=result['stats']
        ok=bool(s['closed_cycles']>=5 and min(s['net_pnl'],s['first_half_pnl'],s['second_half_pnl'],s['pnl_excluding_best_trade'])>0 and not s['unclosed_position'] and not s['halted'])
        row={'name':name,'config':asdict(cfg),**s,'qualified_training':ok}
        results.append(row)
        if ok: qualified.append(row)
        save_result(result,out/name,{'name':name,'split':'training_search','config':asdict(cfg),'source':audits,'protocol_sha256':sha256(out/'protocol.json')})
        write_json(out/'progress.json',results)
        print(f"{name}: pnl={s['net_pnl']:.4f}, return={s['total_return_pct']:.4f}%, trades={s['closed_cycles']}, qualified={ok}",flush=True)
    baselines=[]
    for name in ('equal_hold','QQQ','SPY','cash'):
        result=simulate(training,Settings(),START,END,benchmark=name)
        baselines.append({'name':name,**result['stats']})
        save_result(result,out/('baseline-'+name),{'name':name,'split':'training_baseline','config':asdict(Settings()),'source':audits})
        print(f"baseline {name}: pnl={result['stats']['net_pnl']:.4f}",flush=True)
    write_json(out/'results.json',results);write_json(out/'baselines.json',baselines)
    selected=None;stress=[]
    for candidate in sorted(qualified,key=lambda c:(-(c['sharpe_daily_ann'] or -1e9),c['name'])):
        cfg=replace(Settings(**candidate['config']),fee_bps=15.,slippage_bps=5.)
        result=simulate(training,cfg,START,END)
        s=result['stats']; stress.append({'name':candidate['name'],**s})
        save_result(result,out/(candidate['name']+'-stress'),{'name':candidate['name'],'split':'training_cost_stress','config':asdict(cfg),'source':audits})
        if selected is None and s['net_pnl']>0 and not s['unclosed_position'] and not s['halted']: selected=candidate
    selection={'selected':selected,'stress':stress,'frozen_before_holdout_at':str(pd.Timestamp.now(tz='UTC')),'oos_evaluated_at_freeze':False}
    write_json(out/'selection.json',selection)
    holdout=None;holdout_baselines=[]
    if selected:
        cfg=Settings(**selected['config'])
        holdout=simulate(frames,cfg,END,OOS_END)
        save_result(holdout,out/'holdout',{'name':selected['name'],'split':'historical_holdout_once','config':asdict(cfg),'selection_sha256':sha256(out/'selection.json'),'source':audits})
        for name in ('equal_hold','QQQ','SPY','cash'):
            result=simulate(frames,Settings(),END,OOS_END,benchmark=name)
            holdout_baselines.append({'name':name,**result['stats']})
            save_result(result,out/('holdout-baseline-'+name),{'name':name,'split':'historical_holdout_baseline','config':asdict(Settings()),'source':audits})
        write_json(out/'holdout_data_audit.json',{s:audit_bars(f,END,OOS_END) for s,f in frames.items()})
        print('HOLDOUT',holdout['stats'],flush=True)
    validation={'holdout':holdout['stats'] if holdout else None,'baselines':holdout_baselines,'no_retuning_after_holdout':True}
    write_json(out/'validation.json',validation)
    summary={'training_trials':4,'positive_training_trials':sum(r['net_pnl']>0 for r in results),
        'qualified_training_trials':len(qualified),'selected':selected['name'] if selected else None,
        'holdout':validation['holdout'],'training_results':results,'training_baselines':baselines,'holdout_baselines':holdout_baselines,
        'scope':'historical_holdout_once' if holdout else 'training_only_no_qualified_candidate'}
    write_json(out/'summary.json',summary)
    columns=['name','net_pnl','total_return_pct','max_drawdown_pct','sharpe_daily_ann','closed_cycles','first_half_pnl','second_half_pnl','fees','average_gross_exposure_pct']
    table=pd.DataFrame(results)[columns+['qualified_training']].to_html(index=False)
    headline=f"冻结候选 {selected['name']}；历史留出收益 {holdout['stats']['total_return_pct']:.4f}%" if selected else '没有候选同时通过训练稳定性与成本压力门槛；未运行历史留出'
    links=' · '.join(f'<a href="{r["name"]}/report.html">{r["name"]}</a>' for r in results)
    blinks=' · '.join(f'<a href="baseline-{r["name"]}/report.html">{r["name"]}</a>' for r in baselines)
    extra='<p><a href="holdout/report.html">冻结策略留出报告</a></p>'+pd.DataFrame([{'name':selected['name'],**holdout['stats']}]+holdout_baselines)[columns].to_html(index=False) if selected else ''
    (out/'report.html').write_text(f'''<!doctype html><meta charset="utf-8"><title>现货趋势与突破对照</title><style>body{{font:14px/1.7 system-ui;margin:35px}}td,th{{padding:8px;border:1px solid #ddd}}table{{border-collapse:collapse}}</style><h1>现货趋势择时＋突破：固定四组规则</h1><p>{headline}</p><p>训练2026-06-19至2026-08-18，共60天；留出2026-08-18至2026-09-17，共30天。股票相关现货，无杠杆，四资产共享10000USDT。所有费用与失败实验保留。行情缺口未填造，历史费用、代币单位及公司行动未完全认证。此前已有149次其他策略训练尝试，不能忽略选择偏差。</p><p><a href="protocol.json">预声明规则</a> · <a href="data_audit.json">数据缺口</a> · <a href="selection.json">冻结选择</a> · <a href="validation.json">验证状态</a></p><h2>全部训练策略</h2><p>{links}</p>{table}<h2>训练基准</h2><p>{blinks}</p>{pd.DataFrame(baselines)[columns].to_html(index=False)}<p>基准使用相同初始现金和最高目标配置，实际成交与策略波动缩仓造成仓位差异，不能只比较净利润。</p>{extra}''',encoding='utf-8')
    for name,digest in source.items():
        if sha256(ROOT/name)!=digest: raise AssertionError('Research source changed during execution')
    write_json(out/'artifacts.json',{str(p.relative_to(out)):sha256(p) for p in out.rglob('*') if p.is_file()})


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);parser.add_argument('--data')
    args=parser.parse_args();run(args.out,args.data)
