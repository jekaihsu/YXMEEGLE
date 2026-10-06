"""Fail-closed verification of an exact deployment stage inventory."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat


def inventory_digest(entries: list[dict]) -> str:
    canonical = sorted(
        ({'path': entry['path'], 'size': entry['size'], 'sha256': entry['sha256']} for entry in entries),
        key=lambda entry: entry['path'],
    )
    payload = json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def verify_stage_inventory(stage: Path, entries: list[dict]) -> str:
    stage = Path(stage).resolve(strict=True)
    if not isinstance(entries, list) or not entries:
        raise ValueError('Deployment manifest must contain files')

    expected: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'path', 'size', 'sha256'}:
            raise ValueError('Malformed deployment manifest entry')
        name = entry['path']
        if not isinstance(name, str) or '\\' in name:
            raise ValueError('Non-canonical deployment path')
        relative = PurePosixPath(name)
        if relative.is_absolute() or not relative.parts or any(part in ('', '.', '..') for part in relative.parts):
            raise ValueError('Unsafe deployment path')
        canonical = relative.as_posix()
        if canonical != name or canonical in expected:
            raise ValueError('Duplicate or non-canonical deployment path')
        if not isinstance(entry['size'], int) or entry['size'] < 0 or not isinstance(entry['sha256'], str):
            raise ValueError('Malformed deployment manifest metadata')
        expected[canonical] = entry

    actual: set[str] = set()
    for path in stage.rglob('*'):
        relative = path.relative_to(stage).as_posix()
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError('Deployment stage contains a symlink')
        if stat.S_ISREG(info.st_mode):
            actual.add(relative)
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError('Deployment stage contains a special file')
    if actual != set(expected):
        raise ValueError('Deployment stage inventory differs from manifest')

    for name, entry in expected.items():
        path = stage.joinpath(*PurePosixPath(name).parts)
        data = path.read_bytes()
        if len(data) != entry['size'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
            raise ValueError('Deployment snapshot changed')
    return inventory_digest(entries)
