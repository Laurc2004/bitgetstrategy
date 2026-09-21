"""Refresh hashes after intentional edits; excludes Git-ignored runtime data."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT=Path(__file__).resolve().parents[1]
if __name__=='__main__':
    names=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=ROOT).decode('utf-8').split('\0')
    hashes={}
    for name in sorted(set(names)):
        p=ROOT/name
        if name and name!='repository_manifest.json' and p.is_file():
            hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    (ROOT/'repository_manifest.json').write_text(json.dumps(hashes,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Prepared manifest for',len(hashes),'files')
