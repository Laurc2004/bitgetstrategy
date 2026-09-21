"""Prepare a timestamped public snapshot; does not upload or push anything."""
from pathlib import Path
import argparse
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from basis_lab.forward import atomic_json


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--account',required=True,type=Path)
    a=p.parse_args()
    data=json.loads((a.account/'dashboard.json').read_text(encoding='utf-8'))
    data['publication']='STATIC_SNAPSHOT_NOT_A_LIVE_CONNECTION'
    atomic_json(ROOT/'data/live.json',data)
    freeze=ROOT/'configs/forward-v3-freeze.json'
    if freeze.exists():
        if json.loads(freeze.read_text(encoding='utf-8'))!=data['protocol']:
            raise ValueError('Existing published freeze differs; choose an explicitly named new version')
    else:
        atomic_json(freeze,data['protocol'])
    print('Prepared snapshot at',data['generated_at'])
