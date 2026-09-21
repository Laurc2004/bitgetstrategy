"""Freeze and run a bounded v3 forward paper account using GET-only market data."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse
import gzip
import hashlib
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from basis_lab.forward import Store, atomic_json, digest, iso, stamp
from basis_lab.trend_research import SYMBOLS


def capture(folder, endpoint, symbol, **params):
    if endpoint not in ('candles','tickers'):
        raise ValueError('Public market GET allowlist only')
    query = dict(category='SPOT',symbol='R'+symbol+'USDT',**params)
    url = 'https://api.bitget.com/api/v3/market/'+endpoint+'?'+urllib.parse.urlencode(query)
    record = dict(url=url, requested_at=iso(pd.Timestamp.now(tz='UTC')))
    try:
        request = urllib.request.Request(url,headers={'User-Agent':'rToken-Breakout-Lab/0.3'},method='GET')
        with urllib.request.urlopen(request,timeout=15) as response:
            raw = response.read(2_000_000)
        record['body'] = json.loads(raw)
        if record['body'].get('code') != '00000':
            raise ValueError('API '+str(record['body'].get('code'))+': '+str(record['body'].get('msg')))
    except Exception as exc:
        record['error'] = type(exc).__name__+': '+str(exc)
    record['received_at'] = iso(pd.Timestamp.now(tz='UTC'))
    path = folder/'raw'/(str(time.time_ns())+'-'+symbol+'-'+endpoint+'.json.gz')
    path.parent.mkdir(exist_ok=True)
    with gzip.open(path,'wt',encoding='utf-8') as handle:
        json.dump(record,handle,ensure_ascii=False)
    return record


def initialize(folder, days):
    if folder.exists() and any(folder.iterdir()):
        raise ValueError('Use a new empty directory for a new account')
    folder.mkdir(parents=True,exist_ok=True)
    now = pd.Timestamp.now(tz='UTC')
    cfg = ROOT/'configs/development-v3.json'
    paths = [cfg, ROOT/'scripts/track_forward.py', *sorted((ROOT/'src/basis_lab').rglob('*.py'))]
    protocol = dict(name='v3-forward-001', started_at=iso(now), ends_at=iso(now+pd.Timedelta(days=days)),
        strategy=json.loads(cfg.read_text(encoding='utf-8')), config_sha256=digest(cfg),
        source_hashes={str(p.relative_to(ROOT)).replace('\\','/'):digest(p) for p in paths},
        scope='PROSPECTIVE_PUBLIC_DATA_PAPER', interval_seconds=60,
        warmup='Up to 10 prior calendar days, no pre-start PnL or orders.',
        execution='Actual receipt time; first full subsequent minute; bars >120s late cannot fill or signal.',
        stopping='No scheduled liquidation: stopping records open positions; resume this same account.',
        data='GET Bitget v3 SPOT candles/tickers. First completed observation retained. Missing bars never filled.',
        comparison='Same v3 signal, costs and risk parameters; stricter receipt-time execution than historical replay.')
    atomic_json(folder/'protocol.json',protocol)
    for p in paths:
        dest = folder/'frozen_source'/p.relative_to(ROOT)
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(p.read_bytes())


def verify(folder):
    protocol=json.loads((folder/'protocol.json').read_text(encoding='utf-8'))
    for path,h in protocol['source_hashes'].items():
        if digest(ROOT/path)!=h:
            raise ValueError('Frozen implementation changed: '+path+'; use its frozen_source or a new version/account')
    if protocol['strategy']!=json.loads((ROOT/'configs/development-v3.json').read_text(encoding='utf-8')):
        raise ValueError('Protocol strategy does not match frozen configuration')
    return protocol


def warmup(store):
    folder=store.folder
    before=int(stamp(store.protocol['started_at']).floor('min').timestamp()*1000)
    lower=before-10*86400*1000
    def collect(s):
        end=before; rows=[]; errors=[]
        for _ in range(20):
            r=capture(folder,'candles',s,interval='1m',limit=1000,endTime=end)
            if r.get('error'):
                errors.append(s+': '+r['error']);break
            batch=r['body']['data']
            rows.extend(x for x in batch if lower<=int(x[0])<before)
            if not batch:break
            oldest=min(int(x[0]) for x in batch)
            if oldest<=lower or oldest>=end:break
            end=oldest-1
            time.sleep(.3)
        return s,rows,errors
    errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for s,rows,errs in pool.map(collect,SYMBOLS):
            try:store.ingest({s:rows},pd.Timestamp.now(tz='UTC'),warmup=True)
            except Exception as exc:errs.append(s+': '+str(exc))
            errors.extend(errs)
    atomic_json(folder/'warmup.json',dict(finished_at=iso(pd.Timestamp.now(tz='UTC')),errors=errors))
    return errors


def run(folder, once=False):
    protocol=verify(folder)
    lock=folder/'runner.lock'
    try:
        descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:
        raise ValueError('Runner lock exists. Verify its PID is stopped before removing stale lock.')
    os.write(descriptor,str(os.getpid()).encode());os.close(descriptor)
    store=Store(folder); quotes={}; errors=[]; status='starting'
    def publish():
        atomic_json(folder/'dashboard.json',store.dashboard(quotes,status,errors,pd.Timestamp.now(tz='UTC')))
    try:
        if stamp(protocol['ends_at'])<=pd.Timestamp.now(tz='UTC'):
            status='observation_complete';publish();return
        if not (folder/'warmup.json').exists():
            status='warming_up';publish();errors=warmup(store)
        while True:
            now=pd.Timestamp.now(tz='UTC')
            if (folder/'STOP').exists() or now>=stamp(protocol['ends_at']):
                status='stopped' if (folder/'STOP').exists() else 'observation_complete';break
            verify(folder)
            begin=time.monotonic(); errors=[]; batches={}; quotes={}
            specs=[(s,e) for s in SYMBOLS for e in ('candles','tickers')]
            def fetch(spec):
                s,e=spec
                return s,e,capture(folder,e,s,**(dict(interval='1m',limit=100) if e=='candles' else {}))
            with ThreadPoolExecutor(max_workers=4) as pool:
                for s,e,r in pool.map(fetch,specs):
                    if r.get('error'):
                        errors.append(s+'/'+e+': '+r['error']);continue
                    if e=='candles':batches[s]=r['body']['data']
                    elif r['body']['data']:
                        q=r['body']['data'][0]
                        try:
                            quotes[s]=dict(price=float(q['lastPrice']),bid=float(q['bid1Price']),ask=float(q['ask1Price']),
                                change_pct=float(q['price24hPcnt'])*100,exchange_at=iso(pd.to_datetime(int(q['ts']),unit='ms',utc=True)),
                                received_at=r['received_at'])
                            if not all(math.isfinite(quotes[s][k]) for k in ('price','bid','ask','change_pct')):
                                quotes.pop(s);raise ValueError('Nonfinite quote')
                        except (KeyError,ValueError,TypeError) as exc:errors.append(s+'/ticker: '+str(exc))
            now=pd.Timestamp.now(tz='UTC')
            # Validate per symbol: one malformed response cannot poison the other symbols.
            from basis_lab.forward import parse_candles
            valid={}
            for s,rows in batches.items():
                try:parse_candles(rows,now);valid[s]=rows
                except Exception as exc:errors.append(s+'/candles: '+str(exc))
            result=store.ingest(valid,now)
            status='running' if not errors else 'data_degraded'
            publish()
            with (folder/'rounds.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps(dict(at=iso(now),status=status,errors=errors,**result))+'\n')
            print(iso(now),status,'equity',round(store.dashboard({},status,errors,now)['equity'],4),flush=True)
            if once:status='snapshot_only';break
            delay=max(1,protocol['interval_seconds']-(time.monotonic()-begin))
            for _ in range(math_ceil(delay)):
                if (folder/'STOP').exists():break
                time.sleep(1)
    except BaseException as exc:
        status='runner_error';errors.append(type(exc).__name__+': '+str(exc));raise
    finally:
        publish();store.db.close();lock.unlink(missing_ok=True)


def math_ceil(value):
    return int(value)+(value>int(value))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',required=True);p.add_argument('--init',action='store_true')
    p.add_argument('--days',type=int,default=7);p.add_argument('--once',action='store_true');p.add_argument('--stop',action='store_true')
    args=p.parse_args();folder=Path(args.out).resolve()
    if not 1<=args.days<=30:p.error('--days must be 1..30')
    if args.stop:
        if not (folder/'protocol.json').is_file():p.error('No account at --out')
        (folder/'STOP').write_text('Requested stop',encoding='utf-8')
    else:
        if args.init:initialize(folder,args.days)
        run(folder,args.once)
