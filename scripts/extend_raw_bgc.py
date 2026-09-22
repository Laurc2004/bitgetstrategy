#!/usr/bin/env python3
"""Extend data/raw/<SYM>_spot.jsonl with fresh bars via the official Agent Hub
bgc CLI (bitget-agent-cli, v3 public market endpoint).

No credentials needed (public market data). Pages forward with
startTime/endTime windows of 100 bars per call, dedupes on ts, appends sorted,
and records provenance (including the bgc version) into data/sources_local.json.
"""
import hashlib
import json
import os
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, '..', 'data', 'raw')
SYMS = ['RQQQUSDT', 'RSPYUSDT', 'RAAPLUSDT', 'RTSLAUSDT']


def bgc_candles(sym, start_ms, end_ms):
    """Call `bgc market candlesHistory` for one window; return raw rows."""
    cmd = ['bgc', 'market', '--action', 'candlesHistory',
           '--category', 'SPOT', '--symbol', sym, '--interval', '1m',
           '--limit', '100',
           '--startTime', str(start_ms), '--endTime', str(end_ms)]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError(f'bgc failed for {sym}: {out.stderr[:200]}')
    d = json.loads(out.stdout)
    if not d.get('ok', True):
        raise RuntimeError(f'bgc error for {sym}: {json.dumps(d.get("error"))[:200]}')
    return d.get('data') or []


def fetch_range(sym, start_ms, end_ms):
    rows = []
    cur = start_ms
    while cur < end_ms:
        batch = bgc_candles(sym, cur, min(cur + 100 * 60_000, end_ms))
        if not batch:
            cur += 100 * 60_000
            time.sleep(0.05)
            continue
        rows.extend(batch)
        cur = int(batch[-1][0]) + 60_000
        time.sleep(0.05)
    return rows


def main():
    ver = subprocess.run(['bgc', '--version'], capture_output=True, text=True).stdout.strip()
    now_ms = int(time.time() * 1000)
    provenance = {'fetch_path': 'bgc market candlesHistory (Bitget Agent Hub CLI)', 'bgc_version': ver}
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
        sha = hashlib.sha256(open(f, 'rb').read()).hexdigest()
        provenance[sym] = {'added_bars': added, 'last_ts': max(existing), 'sha256': sha,
                           'fetched_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        print(sym, f'+{added} bars, last',
              time.strftime('%Y-%m-%d %H:%M', time.gmtime(max(existing) / 1000)), 'UTC', flush=True)
    with open(os.path.join(RAW, '..', 'sources_local.json'), 'w') as fh:
        json.dump(provenance, fh, indent=1)
    print('provenance -> data/sources_local.json')


if __name__ == '__main__':
    main()
