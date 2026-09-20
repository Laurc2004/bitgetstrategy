"""One bounded eight-variant optimization followed by one frozen historical validation."""
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

START=utc('2026-06-19T00:00:00Z');END=utc('2026-08-18T00:00:00Z');OOS_END=utc('2026-09-17T00:00:00Z')


def robust(s):
    return bool(s['closed_cycles']>=5 and min(s['net_pnl'],s['first_half_pnl'],s['second_half_pnl'],s['pnl_excluding_best_trade'])>0
                and not s['unclosed_position'] and not s['halted'])


def run(out,data):
    out=Path(out);data=Path(data)
    if out.exists() and any(out.iterdir()):raise ValueError('Choose empty output')
    out.mkdir(parents=True,exist_ok=True)
    grid=[Settings(family='breakout',fast=f,slow=18,trailing_stop=stop,confirmation_bars=confirm)
          for confirm in (1,2) for f in (6,12) for stop in (.04,.08)]
    sources=[Path(__file__),ROOT/'src/basis_lab/trend_research.py',ROOT/'src/basis_lab/report.py',ROOT/'src/basis_lab/portfolio.py',ROOT/'src/basis_lab/models.py',ROOT/'src/basis_lab/data/validate.py']
    hashes={str(p.relative_to(ROOT)):sha256(p) for p in sources}
    protocol={'created_at':pd.Timestamp.now(tz='UTC'),'symbols':SYMBOLS,'variants':[asdict(c) for c in grid],
        'train_start':START,'train_end':END,'holdout_end':OOS_END,'maximum_training_variants':8,'cost_stress':{'fee_bps':15.,'slippage_bps':5.},
        'source_hashes':hashes,'prior_search_count':153,
        'changes':'Only confirmation1/2 completed 4h bars, low-channel exit6/12 bars, trailing stop4/8%; entry channel18 bars. Original breakout6/18 stop8 confirm1 is included control. Fees, universe, sizing and fill assumptions unchanged.',
        'selection':'First prefer candidates satisfying the unchanged strict robustness flag at BOTH base and stressed costs. Otherwise diagnostic selection among base AND stress positive, >=5 base closed trades, both flat/nonhalted. Rank each eligible tier by stress daily Sharpe descending, then base daily Sharpe descending, then name. If no eligible candidate, freeze original control as failed diagnostic. Exactly ONE selected candidate evaluated on historical holdout plus fixed baselines. No replacement after holdout.',
        'strict_robustness':'Positive net PnL, positive both training halves, positive excluding largest winning trade, >=5 completed trades, flat and no account halt.',
        'protocol_change_disclosure':'Previous training experiments skipped holdout unless strict robust. User now requests submission-length evidence: diagnostic holdout is allowed even if strict gate fails, with FAILED status retained. This policy is fixed before these 8 results and before holdout. It is not approval for live trading.',
        'causality':'Completed4h bars, next completed1m high/low+slip execution, volume cap1%, .01 step assumed, long-only shared10000USDT, max20% initial position per asset, no leverage. Buy30min expiration, sells persistent, stop orders fill later. Planned final24h exits. Existing source contains full exact rules.',
        'limitations':'Prior historical holdout partly exposed through baseline/team materials; not pristine blind test. Source token units/corporate actions not independently certified. Missing prices marked stale, no fill imputation. IS and OOS start separate10000USDT accounts; never compound them into a continuous live record. Raw data not redistributed without license.'}
    write_json(out/'protocol.json',protocol)
    for p in sources:
        dst=out/'source'/p.relative_to(ROOT);dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(p.read_bytes())
    frames={};audits={}
    for s in SYMBOLS:
        f,a=load_bars(data/f'R{s}USDT_spot.jsonl');frames[s]=completed_bars(f)
        audits[s]={'source':a,'training':audit_bars(frames[s],START,END)}
    write_json(out/'data_audit.json',audits)
    train={s:f.loc[f.index<END] for s,f in frames.items()}
    results=[]
    for cfg in grid:
        name=f'breakout-exit{cfg.fast}-stop{int(cfg.trailing_stop*100)}-confirm{cfg.confirmation_bars}'
        base=simulate(train,cfg,START,END);stresscfg=replace(cfg,fee_bps=15.,slippage_bps=5.)
        stress=simulate(train,stresscfg,START,END)
        a,b=base['stats'],stress['stats']
        row={'name':name,'config':asdict(cfg),'base':a,'stress':b,'strict_robustness':robust(a) and robust(b),
             'diagnostic_eligible':min(a['net_pnl'],b['net_pnl'])>0 and a['closed_cycles']>=5 and not (a['unclosed_position'] or b['unclosed_position'] or a['halted'] or b['halted'])}
        results.append(row)
        for label,r,c in [('train',base,cfg),('stress',stress,stresscfg)]:
            save_result(r,out/name/label,{'name':name,'split':label,'config':asdict(c),'source':audits,'protocol_sha256':sha256(out/'protocol.json')})
        write_json(out/'progress.json',results)
        print(f"{name}: base={a['net_pnl']:.4f}, stress={b['net_pnl']:.4f}, cycles={a['closed_cycles']}, robust={row['strict_robustness']}",flush=True)
    write_json(out/'results.json',results)
    rank=lambda r:(-(r['stress']['sharpe_daily_ann'] if r['stress']['sharpe_daily_ann'] is not None else -1e9),
                   -(r['base']['sharpe_daily_ann'] if r['base']['sharpe_daily_ann'] is not None else -1e9),r['name'])
    strict=[r for r in results if r['strict_robustness']]
    eligible=[r for r in results if r['diagnostic_eligible']]
    selected=sorted(strict or eligible,key=rank)[0] if strict or eligible else next(r for r in results if r['name']=='breakout-exit6-stop8-confirm1')
    selection={'frozen_at':pd.Timestamp.now(tz='UTC'),'selected':selected,'purpose':'qualified_candidate' if strict else 'diagnostic_only_failed_robustness',
               'holdout_not_yet_evaluated':True,'protocol_sha256':sha256(out/'protocol.json')}
    write_json(out/'selection.json',selection);write_json(out/'frozen_config.json',selected['config'])
    print('FROZEN:',selected['name'],selection['purpose'],flush=True)
    cfg=Settings(**selected['config'])
    holdout=simulate(frames,cfg,END,OOS_END)
    save_result(holdout,out/'holdout',{'name':selected['name'],'split':'historical_holdout_once','config':asdict(cfg),'source':audits,'selection_sha256':sha256(out/'selection.json')})
    holdout_stress=simulate(frames,replace(cfg,fee_bps=15.,slippage_bps=5.),END,OOS_END)
    save_result(holdout_stress,out/'holdout-stress',{'name':selected['name'],'split':'historical_holdout_fixed_cost_stress','config':asdict(replace(cfg,fee_bps=15.,slippage_bps=5.)),'selection_sha256':sha256(out/'selection.json')})
    baselines={}
    for split,start,end,fs in [('train',START,END,train),('holdout',END,OOS_END,frames)]:
        baselines[split]=[]
        for name in ('equal_hold','QQQ','SPY','cash'):
            r=simulate(fs,Settings(),start,end,benchmark=name)
            baselines[split].append({'name':name,**r['stats']})
            save_result(r,out/f'{split}-baseline-{name}',{'name':name,'split':split+'_baseline','config':asdict(Settings()),'source':audits})
    write_json(out/'holdout_data_audit.json',{s:audit_bars(f,END,OOS_END) for s,f in frames.items()})
    summary={'selected':selected['name'],'selection_purpose':selection['purpose'],'config':selected['config'],
        'training_trials':8,'prior_training_trials':153,'positive_base_trials':sum(r['base']['net_pnl']>0 for r in results),
        'training':selected['base'],'training_stress':selected['stress'],'holdout':holdout['stats'],'holdout_stress':holdout_stress['stats'],
        'strict_robustness_passed':selected['strict_robustness'],'baselines':baselines,'no_retuning_after_holdout':True,
        'validation_status':'historical_holdout_completed_not_pristine','data_provenance':'Public teammate repository at pinned commit; source inputs hash-verified; raw data not bundled.'}
    write_json(out/'summary.json',summary)
    print('HOLDOUT:',holdout['stats'],flush=True)
    rows=[{'name':r['name'],'train_pnl':r['base']['net_pnl'],'stress_pnl':r['stress']['net_pnl'],'closed':r['base']['closed_cycles'],
           'first_half':r['base']['first_half_pnl'],'second_half':r['base']['second_half_pnl'],'exclude_best':r['base']['pnl_excluding_best_trade'],'robust':r['strict_robustness']} for r in results]
    pd.DataFrame(rows).to_csv(out/'results.csv',index=False)
    report_rows=[{'period':k,**summary[k]} for k in ('training','training_stress','holdout','holdout_stress')]
    cols=['period','net_pnl','total_return_pct','max_drawdown_pct','sharpe_daily_ann','sortino_daily_ann','closed_cycles','winning_cycle_fraction','turnover_over_initial_cash','fees','stale_valuation_points']
    links=' · '.join(f'<a href="{r["name"]}/train/report.html">{r["name"]}</a>' for r in results)
    baseline_html=''.join('<h3>'+split+'</h3>'+pd.DataFrame(rs)[['name','net_pnl','total_return_pct','max_drawdown_pct','average_gross_exposure_pct']].to_html(index=False) for split,rs in baselines.items())
    (out/'report.html').write_text(f'''<!doctype html><meta charset="utf-8"><title>rToken Breakout Lab · v2</title><style>body{{font:14px/1.7 system-ui;margin:35px}}td,th{{padding:8px;border:1px solid #ddd}}table{{border-collapse:collapse}}a{{color:#246854}}</style><h1>rToken Breakout Lab · 固定8组优化与历史留出</h1><p>冻结版本：{selected['name']}。选择用途：{selection['purpose']}。稳定性通过：{selected['strict_robustness']}。</p><p>60天训练：2026-06-19至08-18；30天历史留出：08-18至09-17。两个区间分别从10000USDT开始。不是连续90天实盘净值，也不是完全未接触的盲测。此前153个方案保留，所有新尝试如下。</p><p><a href="protocol.json">运行前协议</a> · <a href="selection.json">留出前冻结选择</a> · <a href="data_audit.json">数据审计</a> · <a href="holdout_data_audit.json">留出数据缺口</a> · <a href="holdout/report.html">留出成交与曲线</a> · <a href="holdout-stress/report.html">留出成本压力</a></p><h2>冻结策略结果</h2>{pd.DataFrame(report_rows)[cols].to_html(index=False)}<h2>全部8组训练结果</h2><p>{links}</p>{pd.DataFrame(rows).to_html(index=False)}<h2>基准与实际仓位</h2>{baseline_html}<p>缺失行情不补成交，持仓按旧价估值可能低估风险；原始成交量单位、历史交易规格和公司行动尚未完成独立认证。正收益、材料齐备和稳定性通过是不同结论。</p>''',encoding='utf-8')
    for name,digest in hashes.items():
        if sha256(ROOT/name)!=digest:raise AssertionError('Source changed during experiment')
    write_json(out/'artifacts.json',{str(p.relative_to(out)):sha256(p) for p in out.rglob('*') if p.is_file()})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--data',default=str(ROOT/'review-weekend-bounce/reproduce/pair_1m'))
    a=p.parse_args();run(a.out,a.data)
