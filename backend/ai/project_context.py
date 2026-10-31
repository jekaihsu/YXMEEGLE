"""User-specific case projections, fetched through the app's authorization routes."""
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import json
import hashlib
import logging
from datetime import datetime, timezone
from time import monotonic, perf_counter

import httpx

from .tools import Reader, ReadDenied, owners, pick, project_owners, project_progress


@dataclass(frozen=True)
class ProjectContext:
    json: str
    expires: float


ACTION_LABELS = {
    'local_node_assign': '指派節點負責人',
    'local_node_complete': '完成節點',
    'local_node_reject': '退回節點',
    'node_assignment': '指派節點負責人',
    'task_assignment': '指派任務負責人',
    'node_skip_create': '建立節點跳過草稿',
    'node_skip_submit': '送出節點跳過審批',
    'node_skip_vote': '確認節點跳過申請',
    'node_skip_apply': '套用核准跳過',
    'node_skip_withdraw': '撤回節點跳過申請',
    'task_start': '開始作業',
    'task_complete': '完成任務並交付成果',
    'task_return': '退回任務修正',
    'task_update': '更新任務指派與排程',
    'task_add': '新增任務',
    'node_complete': '送交節點確認',
    'participants_update': '更新案件參與人員',
    'comment_add': '新增評論',
    'file_link': '加入檔案連結',
    'approval_create': '建立審批草稿',
    'approval_submit': '送出審批',
    'approval_confirm': '完成審批確認',
    'approval_lark': '更新示範審批結果',
    'approval_execute': '套用已核准的調整',
    'approval_withdraw': '撤回申請',
    'change_resume': '恢復受影響工項',
    'calendar_update': '更新工作日設定',
    'demo_reset': '還原示範工作區',
}

UNREADABLE = {'unknown', 'read_failed', 'forbidden', 'loading', 'unlocated'}


class ContextUnavailable(Exception):
    pass


def unavailable(value, reason):
    value['unavailable'] = '無法確認：' + reason
    return value


def normalize(value):
    if isinstance(value, dict):
        result = {key: normalize(child) for key, child in value.items()}
        if (set(value.get('states', [])) & UNREADABLE or value.get('state') in UNREADABLE
                or str(value.get('reason') or '').startswith('no_authorized_')):
            unavailable(result, '來源未提供可確認資料')
        return result
    if isinstance(value, list):
        return [normalize(child) for child in value]
    return value


def compact(data, limit=12000):
    def encode():
        return json.dumps(data, ensure_ascii=False, separators=(',', ':'))
    def lists(value):
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from lists(child)
    result = encode()
    for key in ('recent_changes', 'blockers', 'dates', 'progress', 'unfinished_tasks', 'owners', 'project'):
        while len(result) > limit:
            data['truncated'] = True
            candidates = list(lists(data[key]))
            if candidates:
                max(candidates, key=lambda v: len(json.dumps(v, ensure_ascii=False))).pop()
            else:
                data[key] = unavailable({}, '內容超過脈絡長度限制')
                result = encode()
                break
            result = encode()
    return result


def event_time(row):
    try:
        return datetime.fromisoformat(row.get('created_at') or row.get('replaced_at')).astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError):
        return float('-inf')


def workflow(detail):
    section = detail.get('sections', {}).get('workflow_nodes')
    if section is None:
        return unavailable({}, '工作流程無法讀取')
    rows = []
    for node in section.get('rows', []):
        if node.get('status') in ('completed', 'superseded', 'cancelled'):
            continue
        for task in node.get('tasks', []):
            if task.get('status') not in ('completed', 'superseded', 'cancelled'):
                rows.append(dict(**pick(task, 'key', 'task_id', 'label', 'status', 'due_date', 'assignee_name'),
                                 node=pick(node, 'key', 'node_id', 'label')))
    rows.sort(key=lambda t: (0 if t.get('status') == 'overdue' else 1 if t.get('status') == 'blocked' else 2,
                             t.get('due_date') or '9999', t.get('key', '')))
    return normalize(dict(**pick(section, 'states', 'reason'), rows=rows[:15], truncated=len(rows) > 15))


async def build(app, cookie, project_id):
    started = perf_counter()
    try:
        async with asyncio.timeout(15):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://ai.internal',
                                         headers={'cookie': cookie}, timeout=15) as client:
                enabled = str(app.state.cfg.get('NODE_ASSIGNMENT_ENABLED', 'false')).lower() == 'true'
                reader = Reader(client, enabled)
                detail = await reader.get('/api/case-detail/' + project_id)
                header = detail['header']
                if not header:
                    raise ReadDenied('找不到或沒有權限查看這個案件')
                owner_data = project_owners(await owners(reader, {'case_id': project_id}, detail=detail))
                owner_data.pop('node_assignments_as_of', None)
                owner_data['responsible_person'] = header.get('responsible_person', unavailable({}, '負責人未提供'))
                try:
                    progress = project_progress(await reader.get('/api/projects/' + project_id + '/progress'))
                    progress.pop('as_of', None)
                except Exception:
                    progress = {'unavailable': 'progress data unavailable', 'reason_zh': '無法確認進度'}
                dates = header.get('dates')
                date_data = unavailable({}, '期限無法讀取') if dates is None else {
                    **{key: pick(dates[key], 'state', 'reason', 'value', 'date')
                       for key in ('effective_approved', 'estimated') if key in dates},
                    'pending_requested': [pick(d, 'approval_id', 'requested_due_date', 'task_key', 'status')
                                          for d in dates.get('pending_requested', [])]}
                history = detail.get('sections', {}).get('history')
                changes = unavailable({}, '最近變更無法讀取') if history is None else {
                    **pick(history, 'states', 'freshness', 'reason'),
                    'source_time': pick(history.get('source_time', {}), 'value', 'basis'),
                    'count': len(history.get('rows', [])),
                    'rows': [dict(**pick(row, 'confirmation_key', 'revision', 'replaced_at', 'event_id', 'action', 'created_at'),
                                  **({'action_label': ACTION_LABELS[row['action']]} if row.get('action') in ACTION_LABELS else {}))
                             for row in sorted(history.get('rows', []), key=event_time, reverse=True)[:20]]}
                if history and history.get('rows'):
                    latest = max(history['rows'], key=event_time)
                    changes['latest_timestamp'] = latest.get('created_at') or latest.get('replaced_at')
                blockers = header.get('blockers')
                blocker_data = unavailable({}, '阻礙無法讀取') if blockers is None else {
                    **pick(blockers, 'states'), 'items': [dict(code=b) if isinstance(b, str) else
                        pick(b, 'code', 'task_key', 'node_id', 'label') for b in blockers.get('items', [])]}
                if blockers and any(isinstance(b, str) for b in blockers.get('items', [])):
                    blocker_data['task_attribution'] = unavailable({}, '來源未提供阻礙所屬任務或節點')
                data = dict(project=dict(id=project_id, **pick(header, 'project_name', 'case_number'),
                    current_stage=pick(header.get('current_stage', {}), 'state', 'node_id', 'label', 'reason')),
                    owners=owner_data, progress=progress, dates=date_data, unfinished_tasks=workflow(detail),
                    blockers=blocker_data, recent_changes=changes)
                return ProjectContext(compact(normalize(data)), monotonic() + 90)
    except ReadDenied:
        raise
    except Exception as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 504 if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else 500
        if status in (401, 403, 404):
            raise ReadDenied('找不到或沒有權限查看這個案件') from None
        logging.getLogger(__name__).warning(
            'ai_context_failed project=%s status=%s exception=%s elapsed_ms=%s',
            hashlib.sha256(project_id.encode()).hexdigest()[:16], status, type(exc).__name__,
            round((perf_counter() - started) * 1000))
        raise ContextUnavailable() from None


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
