"""Fetch only pinned public input files. Refuse unexpected content or overwrite."""
from pathlib import Path
import json,hashlib,urllib.request
ROOT=Path(__file__).resolve().parents[1]
sources=json.loads((ROOT/'data/sources.json').read_text())
folder=ROOT/'data/raw';folder.mkdir(parents=True,exist_ok=True)
for name,record in sources['files'].items():
    target=folder/name
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Existing input differs: '+name)
        print('Verified existing',name);continue
    request=urllib.request.Request(record['url'],headers={'User-Agent':'rToken-Breakout-Lab'})
    with urllib.request.urlopen(request,timeout=60) as response: data=response.read(64*1024*1024+1)
    if len(data)!=record['upstream_bytes'] or hashlib.sha256(data).hexdigest()!=record['upstream_sha256']:raise ValueError('Upstream hash/length mismatch: '+name)
    # Original Windows study checkout used CRLF. Preserve both transport and study hashes.
    if record['analysis_line_endings']=='CRLF':data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
    if len(data)!=record['bytes'] or hashlib.sha256(data).hexdigest()!=record['sha256']:raise ValueError('Pinned source hash/length mismatch: '+name)
    with target.open('xb') as f:f.write(data)
    print('Fetched and verified',name)
