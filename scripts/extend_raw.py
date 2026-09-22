#!/usr/bin/env python3
"""Extend data/raw/<SYM>_spot.jsonl to now via Bitget v3 public market endpoint
(same endpoint the Agent Hub `bgc market candlesHistory` fronts; direct call
avoids per-window CLI subprocess overhead — provenance records both paths).

v3: GET /api/v3/market/history-candles, category=SPOT, interval=1m,
startTime+endTime required, max 100 bars/call.
"""
import hashlib
import json
import os
import time
import urllib.request
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, '..', 'data', 'raw')
SYMS = ['RQQQUSDT', 'RSPYUSDT', 'RAAPLUSDT', 'RTSLAUSDT']


def get_candles(sym, start_ms, end_ms):
    url = 'https://api.bitget.com/api/v3/market/history-candles?' + urllib.parse.urlencode({
        'category': 'SPOT', 'symbol': sym, 'interval': '1m', 'limit': '100',
        'startTime': str(start_ms), 'endTime': str(end_ms)})
    req = urllib.request.Request(url, headers={'User-Agent': 'rToken-Breakout-Lab'})
    last = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode())
            if d.get('code') != '00000':
                raise RuntimeError(d.get('msg'))
            return d.get('data') or []
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0 + attempt)
    raise last


def fetch_range(sym, start_ms, end_ms):
    rows = []
    cur = start_ms
    while cur < end_ms:
        batch = get_candles(sym, cur, min(cur + 100 * 60_000 - 1, end_ms))
        if batch:
            rows.extend(batch)
            cur = int(batch[-1][0]) + 60_000
        else:
            cur += 100 * 60_000
        time.sleep(0.06)
    return rows


def main():
    now_ms = int(time.time() * 1000)
    prov = {'fetch_path': 'Bitget v3 public /api/v3/market/history-candles '
                          '(identical endpoint to `bgc market candlesHistory`, Agent Hub CLI)'}
    for sym in SYMS:
        f = os.path.join(RAW, f'{sym}_spot.jsonl')
        existing = {}
        for line in open(f):
            r = json.loads(line)
            existing[int(r[0])] = r
        last = max(existing)
        new = fetch_range(sym, last + 60_000, now_ms)
        added = 0
        for r in new:
            ts = int(r[0])
            if last < ts <= now_ms and ts not in existing:
                existing[ts] = [str(x) for x in r[:6]]
                added += 1
        with open(f, 'w') as fh:
            for ts in sorted(existing):
                fh.write(json.dumps(existing[ts]) + '\n')
        prov[sym] = {'added_bars': added, 'last_ts': max(existing),
                     'sha256': hashlib.sha256(open(f, 'rb').read()).hexdigest(),
                     'fetched_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        print(sym, f'+{added} bars, last',
              time.strftime('%Y-%m-%d %H:%M', time.gmtime(max(existing) / 1000)), 'UTC', flush=True)
    with open(os.path.join(RAW, '..', 'sources_local.json'), 'w') as fh:
        json.dump(prov, fh, indent=1)
    print('done -> data/sources_local.json')


if __name__ == '__main__':
    main()
