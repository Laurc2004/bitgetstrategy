"""Twelve fixed variants on an explicitly observed 90-day development interval."""
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

START=utc('2026-06-19T00:00:00Z');END=utc('2026-09-17T00:00:00Z')


def run(out,data):
    out=Path(out);data=Path(data)
    if out.exists() and any(out.iterdir()):raise ValueError('Choose empty output')
    out.mkdir(parents=True,exist_ok=True)
    grid=[Settings(family='breakout',fast=fast,slow=18,confirmation_bars=2,confirmation_mode=mode,trailing_stop=stop)
          for mode in ('fresh_highs','hold_level') for fast in (6,12,18) for stop in (.04,.08)]
    paths=[Path(__file__),ROOT/'src/basis_lab/trend_research.py',ROOT/'src/basis_lab/report.py',ROOT/'src/basis_lab/portfolio.py',ROOT/'src/basis_lab/models.py',ROOT/'src/basis_lab/data/validate.py']
    hashes={p.relative_to(ROOT).as_posix():sha256(p) for p in paths}
    protocol={'created_at':pd.Timestamp.now(tz='UTC'),'development_start':START,'development_end':END,'symbols':SYMBOLS,
        'variants':[asdict(c) for c in grid],'maximum_variants':12,'prior_variant_count':161,'source_hashes':hashes,
        'data_status':'ENTIRE 90 DAY WINDOW IS OBSERVED DEVELOPMENT DATA. Earlier v2 historical holdout was inspected. No new OOS claim is permitted. v2 frozen validation remains archived.',
        'hypothesis':'Requiring consecutive NEW highs may chase price and leave cash idle. Alternative confirms one completed bucket above the original breakout threshold without requiring a second fresh high. Compare exit windows6/12/18 and stop4/8 with the original fresh-high confirmation as controls. No universe/cost/position-size/leverage changes.',
        'execution':'Exact shared spot execution engine, next completed minute high/low + slippage,1% volume,.01 step assumption,min5USDT buy,30min buy expiry. Four symbols max20% equity target each,2%daily vol proxy sizing,10% account stop. Known end final24h exit. Data gaps never become fills.',
        'selection':'Eligible: >=8 closed development cycles, base and stress positive, no halt, flat end, worst base/stress measured maximum drawdown <=5%. Rank by STRESS net PnL, then smaller stress drawdown, then name. If no eligible, report highest stress net PnL as an unqualified diagnostic. Never filter symbols or discard losing trials.',
        'costs':{'base_fee_bps':10,'base_slippage_bps':2,'stress_fee_bps':15,'stress_slippage_bps':5},
        'validation':'All12 full90-day development runs at both costs. Fixed buy-hold baselines on same90 days. Profit concentration and three consecutive30-day marked PnL blocks are diagnostics, NOT OOS. No untouched validation performed.',
        'limitations':'Token units, historical corporate actions and trading specifications not independently certified. Stale marks underestimate risk. Parameters selected on this same development interval. Costs and raw data gaps are unchanged.'}
    write_json(out/'protocol.json',protocol)
    for p in paths:
        dest=out/'source'/p.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(p.read_bytes())
    frames={};audits={}
    for s in SYMBOLS:
        bars,source=load_bars(data/f'R{s}USDT_spot.jsonl');frames[s]=completed_bars(bars)
        audits[s]={'source':source,'development':audit_bars(frames[s],START,END)}
    write_json(out/'data_audit.json',audits)
    results=[]
    for cfg in grid:
        name=f'{cfg.confirmation_mode}-exit{cfg.fast}-stop{int(cfg.trailing_stop*100)}'
        pair={}
        for label,c in [('base',cfg),('stress',replace(cfg,fee_bps=15.,slippage_bps=5.))]:
            result=simulate(frames,c,START,END)
            curve=result['equity'];points=[cfg.initial_cash]
            for boundary in (START+pd.Timedelta(days=30),START+pd.Timedelta(days=60),END):
                points.append(float(curve.loc[curve.timestamp<boundary,'equity'].iloc[-1]))
            result['stats']['development_30d_blocks']=[points[i+1]-points[i] for i in range(3)]
            save_result(result,out/name/label,{'name':name,'split':'OBSERVED_DEVELOPMENT_90D_'+label,'config':asdict(c),'source':audits,'protocol_sha256':sha256(out/'protocol.json')})
            pair[label]=result['stats']
        a,b=pair['base'],pair['stress']
        eligible=bool(a['closed_cycles']>=8 and min(a['net_pnl'],b['net_pnl'])>0 and min(a['max_drawdown_pct'],b['max_drawdown_pct'])>=-5 and not(a['halted'] or b['halted'] or a['unclosed_position'] or b['unclosed_position']))
        row={'name':name,'config':asdict(cfg),**pair,'development_eligible':eligible};results.append(row)
        write_json(out/'progress.json',results)
        print(f"{name}: base={a['net_pnl']:.4f}, stress={b['net_pnl']:.4f}, closed={a['closed_cycles']}, eligible={eligible}",flush=True)
    write_json(out/'results.json',results)
    eligible=[r for r in results if r['development_eligible']]
    selected=sorted(eligible or results,key=lambda r:(-r['stress']['net_pnl'],-r['stress']['max_drawdown_pct'],r['name']))[0]
    write_json(out/'selection.json',{'selected':selected,'selected_at':pd.Timestamp.now(tz='UTC'),'scope':'SAME_SAMPLE_DEVELOPMENT_SELECTION','new_oos_evaluated':False,'protocol_sha256':sha256(out/'protocol.json')})
    write_json(out/'frozen_config.json',selected['config'])
    baselines=[]
    for name in ('equal_hold','QQQ','SPY','cash'):
        r=simulate(frames,Settings(),START,END,benchmark=name)
        baselines.append({'name':name,**r['stats']})
        save_result(r,out/f'baseline-{name}',{'name':name,'split':'DEVELOPMENT_BASELINE_90D','config':asdict(Settings()),'source':audits})
    summary={'selected':selected['name'],'config':selected['config'],'development':selected['base'],'development_stress':selected['stress'],
        'development_eligible':selected['development_eligible'],'baselines':baselines,'variants':12,'prior_variants':161,
        'new_oos_evaluated':False,'window_start':START,'window_end':END,'scope':'OBSERVED_DEVELOPMENT_90D','all_results':results}
    write_json(out/'summary.json',summary)
    rows=[{'name':r['name'],'net_pnl':r['base']['net_pnl'],'stress_net_pnl':r['stress']['net_pnl'],'return_pct':r['base']['total_return_pct'],
        'max_drawdown_pct':r['base']['max_drawdown_pct'],'closed_cycles':r['base']['closed_cycles'],'exclude_best_pnl':r['base']['pnl_excluding_best_trade'],
        'development_eligible':r['development_eligible']} for r in results]
    pd.DataFrame(rows).to_csv(out/'results.csv',index=False)
    links=' · '.join(f'<a href="{r["name"]}/base/report.html">{r["name"]}</a>' for r in results)
    (out/'report.html').write_text(f'''<!doctype html><meta charset="utf-8"><title>rToken Breakout Lab v3</title><style>body{{font:14px/1.7 system-ui;margin:35px}}td,th{{padding:8px;border:1px solid #ddd}}table{{border-collapse:collapse}}a{{color:#246854}}.notice{{background:#fff4da;padding:18px}}</style><h1>rToken Breakout Lab · v3 策略开发</h1><p>选择：{selected['name']}。收益 {selected['base']['total_return_pct']:+.4f}%；压力收益 {selected['stress']['total_return_pct']:+.4f}%。</p><p class="notice">2026-06-19至2026-09-17的90天全部属于已观察开发数据，参与本轮参数研究。这里没有新的样本外收益；旧v2的冻结留出亏损记录仍保留。新参数不代表已经通过独立验证。</p><p><a href="protocol.json">实验协议</a> · <a href="selection.json">选择记录</a> · <a href="data_audit.json">来源与缺口</a> · <a href="{selected['name']}/base/report.html">选定开发版本明细</a> · <a href="{selected['name']}/stress/report.html">更高成本</a></p><h2>全部12组尝试</h2><p>{links}</p>{pd.DataFrame(rows).to_html(index=False)}<h2>相同初始10000USDT的持有基准</h2>{pd.DataFrame(baselines)[['name','net_pnl','total_return_pct','max_drawdown_pct','average_gross_exposure_pct']].to_html(index=False)}<p>按最后价格估值的缺口会低估风险，实际仓位不同；原始历史单位和公司行动仍需独立核验。</p>''',encoding='utf-8')
    for name,h in hashes.items():
        if sha256(ROOT/name)!=h:raise AssertionError('Source changed during run')
    write_json(out/'artifacts.json',{p.relative_to(out).as_posix():sha256(p) for p in out.rglob('*') if p.is_file()})
    print('SELECTED',selected['name'],'DEVELOPMENT ONLY',selected['base']['net_pnl'],flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--data',default=str(ROOT/'review-weekend-bounce/reproduce/pair_1m'))
    a=p.parse_args();run(a.out,a.data)
