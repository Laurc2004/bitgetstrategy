#!/usr/bin/env python3
"""Probe Bitget spot 1m history depth for the four RWA symbols (v2 spot API)."""
import json
import time
import urllib.request
import urllib.parse

BASE = 'https://api.bitget.com'
SYMS = ['RQQQUSDT', 'RSPYUSDT', 'RAAPLUSDT', 'RTSLAUSDT']


def get(path, params):
    url = BASE + path + '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={'User-Agent': 'rToken-Breakout-Lab'})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except Exception:
            if attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))


# page as deep as possible: start from now, walk backward 100 pages of 100 bars
for sym in SYMS:
    cur_end = None
    oldest = None
    pages = 0
    while pages < 600:
        p = {'symbol': sym, 'granularity': '1min', 'limit': '100'}
        if cur_end:
            p['endTime'] = str(cur_end)
            p['startTime'] = str(cur_end - 100 * 60_000 - 1)
        d = get('/api/v2/spot/market/history-candles', p)
        if d.get('code') != '00000':
            print(sym, 'api error', d.get('code'), d.get('msg'))
            break
        batch = d.get('data') or []
        if not batch:
            break
        oldest = int(batch[0][0])
        cur_end = oldest - 1
        pages += 1
        time.sleep(0.13)
        if pages % 100 == 0:
            print(f'  {sym}: {pages} pages, oldest so far',
                  time.strftime('%Y-%m-%d', time.gmtime(oldest / 1000)), flush=True)
    import datetime
    print(sym, '-> deepest:', datetime.datetime.utcfromtimestamp(oldest / 1000).date(),
          f'({pages} pages, ~{pages * 100} bars)', flush=True)
