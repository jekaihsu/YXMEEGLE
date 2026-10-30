"""Cheap Linux process accounting without commands, credentials or dependencies."""
import ctypes
import gc
import json
import logging
import os
import sys
from pathlib import Path
import time

ACTIVITY = Path('/tmp/yx-workbench-activity')
_last_activity = 0.0


def mark_activity(path='', method='GET'):
    # Read timers alone must not keep bulk source refresh alive indefinitely.
    if method == 'GET' and path in ('/api/home-panels', '/api/my-work', '/api/live/status', '/api/source-health'):
        return
    global _last_activity
    now = time.monotonic()
    if now - _last_activity >= 30:
        try:
            ACTIVITY.touch()
            _last_activity = now
        except OSError:
            pass


def user_active():
    try:
        return 0 <= time.time() - ACTIVITY.stat().st_mtime < 180
    except OSError:
        return False


def processes(root=Path('/proc')):
    rows = []
    for path in root.glob('[0-9]*'):
        try:
            stat = path.joinpath('stat').read_text().rsplit(')', 1)[1].split()
            status = dict(line.split(':', 1) for line in path.joinpath('status').read_text().splitlines() if ':' in line)
            # The container includes only our service children. No argv or env is exposed.
            rows.append(dict(pid=int(path.name), parent_pid=int(stat[1]),
                             cpu_seconds=(int(stat[11]) + int(stat[12])) / os.sysconf('SC_CLK_TCK'),
                             rss_bytes=int(status.get('VmRSS', '0 kB').split()[0]) * 1024,
                             anonymous_bytes=int(status.get('RssAnon', '0 kB').split()[0]) * 1024,
                             threads=int(status.get('Threads', '0'))))
        except (OSError, ValueError, IndexError):
            continue
    return rows


def container_busy():
    try:
        lines = Path('/sys/fs/cgroup/cpu.pressure').read_text().splitlines()
        full = next(line for line in lines if line.startswith('full '))
        return float(dict(item.split('=') for item in full.split()[1:])['avg10']) >= 25
    except (OSError, ValueError, KeyError, StopIteration):
        return False


def release_working_memory():
    """Return freed bulk-import arenas to Linux after the background cycle."""
    gc.collect()
    if os.name == 'posix':
        try:
            ctypes.CDLL(None).malloc_trim(0)
        except (AttributeError, OSError):
            pass


def log_stage(stage, started, cpu):
    own = next((row for row in processes() if row['pid'] == os.getpid()), {})
    source_cache = getattr(sys.modules.get('backend.sources'), '_source_cache', None)
    source_entries = len(source_cache._entries) if source_cache is not None else 0
    logging.getLogger('backend.resources').warning('resource_stage %s', json.dumps(dict(
        stage=stage, source_cache_entries=source_entries, stage_wall_seconds=round(time.monotonic()-started, 3),
        stage_cpu_seconds=round(time.process_time()-cpu, 3), allocated_blocks=sys.getallocatedblocks(), **own)))
