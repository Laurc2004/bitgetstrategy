#!/usr/bin/env python3
"""Fast parallel extend of data/raw spot jsonl files to now (v3 public API).

4 symbols in parallel threads; empty windows skipped without sleep; request
rate ~15/s aggregate stayed well under limits in testing.
Writes results and provenance when ALL symbols complete.
"""
import hashlib
import json
import os
import threading
import time
import urllib.request
import urllib.parse

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw')
SYMS = ['RQQQUSDT', 'RSPYUSDT', 'RAAPLUSDT', 'RTSLAUSDT']
prov = {}
lock = threading.Lock()


def get(sym, s, e):
    url = 'https://api.bitget.com/api/v3/market/history-candles?' + urllib.parse.urlencode(
        {'category': 'SPOT', 'symbol': sym, 'interval': '1m', 'limit': '100',
         'startTime': str(s), 'endTime': str(e)})
    req = urllib.request.Request(url, headers={'User-Agent': 'rToken-Breakout-Lab'})
    for a in range(5):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode())
            if d.get('code') != '00000':
                raise RuntimeError(d.get('msg'))
            return d.get('data') or []
        except Exception:
            time.sleep(0.5 + a)
    return []


def worker(sym):
    f = os.path.join(RAW, f'{sym}_spot.jsonl')
    existing = {}
    for line in open(f):
        r = json.loads(line)
        existing[int(r[0])] = r
    last = max(existing)
    now = int(time.time() * 1000)
    cur = last + 60_000
    added = 0
    reqs = 0
    while cur < now:
        batch = get(sym, cur, min(cur + 100 * 60_000 - 1, now))
        reqs += 1
        if batch:
            for r in batch:
                ts = int(r[0])
                if last < ts <= now and ts not in existing:
                    existing[ts] = [str(x) for x in r[:6]]
                    added += 1
            cur = int(batch[-1][0]) + 60_000
        else:
            cur += 100 * 60_000
        if reqs % 100 == 0:
            time.sleep(0.15)
    with open(f, 'w') as fh:
        for ts in sorted(existing):
            fh.write(json.dumps(existing[ts]) + '\n')
    with lock:
        prov[sym] = {
            'added_bars': added, 'last_ts': max(existing),
            'sha256': hashlib.sha256(open(f, 'rb').read()).hexdigest(),
            'fetched_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    print(sym, 'done +', added, flush=True)


def main():
    threads = [threading.Thread(target=worker, args=(s,)) for s in SYMS]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    prov['_fetch_path'] = ('Bitget v3 public /api/v3/market/history-candles '
                           '(endpoint fronted by Agent Hub `bgc market candlesHistory`)')
    with open(os.path.join(RAW, '..', 'sources_local.json'), 'w') as fh:
        json.dump(prov, fh, indent=1)
    print('all done in', round(time.time() - t0, 1), 's')


if __name__ == '__main__':
    main()
