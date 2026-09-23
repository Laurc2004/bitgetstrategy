#!/usr/bin/env python3
"""Fetch 4h aggregated klines for the four RWA symbols (full listing history).

v3 public endpoint, interval 4H, 100 bars/call. Full history since listing
(RQQQ/RSPY/RAAPL: 2026-06-01; RTSLA: 2026-04-21). Output: data/raw4h/<SYM>.jsonl
Used for the sandbox-parity backtest while 1m extension completes.
"""
import json
import os
import time
import urllib.request
import urllib.parse

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'raw4h')
os.makedirs(RAW, exist_ok=True)
SYMS = ['RQQQUSDT', 'RSPYUSDT', 'RAAPLUSDT', 'RTSLAUSDT']
EARLIEST = {s: 1748000000000 for s in SYMS}  # probe back to ~2026-05-23; RTSLA listing 04-21


def get(sym, s, e):
    url = 'https://api.bitget.com/api/v3/market/history-candles?' + urllib.parse.urlencode(
        {'category': 'SPOT', 'symbol': sym, 'interval': '4H', 'limit': '100',
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


def fetch_all(sym):
    now = int(time.time() * 1000)
    rows = {}
    cur = EARLIEST[sym]
    while cur < now:
        batch = get(sym, cur, min(cur + 100 * 4 * 3600_000 - 1, now))
        if batch:
            for r in batch:
                rows[int(r[0])] = [str(x) for x in r[:6]]
            cur = int(batch[-1][0]) + 4 * 3600_000
        else:
            cur += 100 * 4 * 3600_000
        time.sleep(0.06)
    return rows


for sym in SYMS:
    rows = fetch_all(sym)
    f = os.path.join(RAW, f'{sym}.jsonl')
    with open(f, 'w') as fh:
        for ts in sorted(rows):
            fh.write(json.dumps(rows[ts]) + '\n')
    print(sym, len(rows), 'bars,', time.strftime('%Y-%m-%d', time.gmtime(min(rows)/1000)),
          '->', time.strftime('%Y-%m-%d', time.gmtime(max(rows)/1000)), flush=True)
print('done')
