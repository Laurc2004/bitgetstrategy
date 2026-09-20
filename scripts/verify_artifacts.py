"""Verify prepared repository artifacts; .git and untracked runtime files are excluded."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[1]
m=json.loads((ROOT/'repository_manifest.json').read_text())
for name,h in m.items():
    p=(ROOT/name).resolve()
    if not p.is_relative_to(ROOT) or not p.is_file():raise ValueError('Missing or unsafe artifact '+name)
    if hashlib.sha256(p.read_bytes()).hexdigest()!=h:raise ValueError('Artifact changed: '+name)
print('Verified',len(m),'prepared files. Intentional source changes require an updated manifest.')
