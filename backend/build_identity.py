import json
import re
from pathlib import Path

MANIFEST_PATH = Path(__file__).with_name('build-manifest.json')


def read_build_identity():
    try:
        value = json.loads(MANIFEST_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get('git_sha'), str) or not re.fullmatch(r'[0-9a-f]{40}', value['git_sha']):
        return None
    if type(value.get('dirty')) is not bool or not all(isinstance(value.get(k), str) for k in ('built_at', 'branch')):
        return None
    return {key: value[key] for key in ('git_sha', 'dirty', 'built_at', 'branch')}
