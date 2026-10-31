"""User-specific case projections, fetched through the app's authorization routes."""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import json
from time import monotonic

import httpx

from .tools import Reader, ReadDenied, owners, pick, project_owners, project_progress


@dataclass(frozen=True)
class ProjectContext:
    json: str
    expires: float


def compact(data, limit=12000):
    def encode():
        return json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    result = encode()
    # Lower-priority parts lose whole entries, never partial JSON or silent omissions.
    for key in ('recent_changes', 'blockers', 'dates', 'progress', 'owners', 'project'):
        while len(result) > limit:
            data['truncated'] = True
            def lists(value):
                if isinstance(value, list) and value:
                    yield value
                elif isinstance(value, dict):
                    for child in value.values():
                        yield from lists(child)
            candidates = list(lists(data[key]))
            if candidates:
                max(candidates, key=lambda v: len(json.dumps(v, ensure_ascii=False))).pop()
            else:
                data[key] = {'unavailable': 'omitted for context length'}
                result = encode()
                break
            result = encode()
    return result


async def build(app, cookie, project_id):
    try:
        async with asyncio.timeout(15):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://ai.internal',
                                         headers={'cookie': cookie}, timeout=15) as client:
                enabled = str(app.state.cfg.get('NODE_ASSIGNMENT_ENABLED', 'false')).lower() == 'true'
                reader = Reader(client, enabled)
                try:
                    detail = await reader.get('/api/case-detail/' + project_id)
                    header = detail['header']
                    if not header:
                        raise ValueError('missing header')
                except Exception:
                    raise ReadDenied('找不到或沒有權限查看這個案件') from None
                owner_data = project_owners(await owners(reader, {'case_id': project_id}, detail=detail))
                try:
                    progress = project_progress(await reader.get('/api/projects/' + project_id + '/progress'))
                except Exception:
                    progress = {'unavailable': 'progress data unavailable'}
                dates = header.get('dates')
                date_data = {'unavailable': 'dates unavailable'} if dates is None else {
                    **{key: pick(dates[key], 'state', 'reason', 'value', 'date')
                       for key in ('effective_approved', 'estimated') if key in dates},
                    'pending_requested': [pick(d, 'approval_id', 'requested_due_date', 'task_key', 'status')
                                          for d in dates.get('pending_requested', [])]}
                history = detail.get('sections', {}).get('history')
                changes = {'unavailable': 'recent changes unavailable'} if history is None else {
                    **pick(history, 'states', 'freshness', 'reason'),
                    'source_time': pick(history.get('source_time', {}), 'value', 'basis', 'fetched_at'),
                    'rows': [pick(row, 'confirmation_key', 'revision', 'replaced_at', 'event_id', 'action', 'created_at')
                             for row in history.get('rows', [])]}
                if history and 'read_failed' in history.get('states', []):
                    changes['unavailable'] = 'recent changes unavailable'
                data = dict(project=dict(id=project_id, **pick(header, 'project_name', 'case_number'),
                    current_stage=pick(header.get('current_stage', {}), 'state', 'node_id', 'label', 'reason')),
                    owners=owner_data, progress=progress, dates=date_data,
                    blockers=pick(header['blockers'], 'items', 'states') if 'blockers' in header else {'unavailable': 'blockers unavailable'},
                    recent_changes=changes)
                return ProjectContext(compact(data), monotonic() + 90)
    except TimeoutError:
        raise ReadDenied('找不到或沒有權限查看這個案件') from None


class ProjectContextCache:
    def __init__(self, maxsize=128):
        self.entries = OrderedDict()
        self.maxsize = maxsize

    async def get(self, app, cookie, workspace, user, project):
        key = (workspace, user, project)
        while True:
            task = self.entries.get(key)
            if task is not None and task.done():
                if task.cancelled() or task.exception() or task.result().expires <= monotonic():
                    del self.entries[key]
                    task = None
            if task is not None:
                self.entries.move_to_end(key)
                return await asyncio.shield(task)
            if len(self.entries) < self.maxsize:
                task = asyncio.create_task(build(app, cookie, project))
                self.entries[key] = task
                def discard_failed(done):
                    if done.cancelled() or done.exception() is not None:
                        if self.entries.get(key) is done:
                            del self.entries[key]
                task.add_done_callback(discard_failed)
                return await asyncio.shield(task)
            for old_key, old_task in self.entries.items():
                if old_task.done():
                    del self.entries[old_key]
                    break
            else:
                await asyncio.wait(list(self.entries.values()), return_when=asyncio.FIRST_COMPLETED)
