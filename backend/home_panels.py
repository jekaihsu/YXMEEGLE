"""Personal assignment panels. Lark I/O and authority stay in node_assignment."""
import base64
import hashlib
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .home_details import build_home_task, local_work_instance
from .home_queues import home_queues
from .node_assignment.cache import ReadScope, StaleCache
from .node_assignment.domain import CHAIN, NODE_DEPARTMENTS, NODE_LABELS, NodeAction, NodeKey, NodeStatus, TaskFacts, TaskStatus, derive_chain, node_permissions, task_permissions
from .node_assignment.errors import Failure
from .node_assignment.lark_table import NODE_FIELDS, TASK_FIELDS, CaseSnapshot, Table, assignment_key, iso_time, parse_node, parse_task
from .node_assignment.evidence import applicable, evidence_of
from .node_assignment.operations import facts_of
from .node_assignment.roster import fetch_roster
from .node_assignment.service import actor_for, confirmation_record
from .source_case_policy import filter_visible_cases
from .sources import link_ids, normalized_case, text
from .workflow import now

PANELS = ('assigned', 'proxy', 'confirmation', 'delegated', 'completed', 'local')
STATUS = {'未開始': 'not_started', '待處理': 'todo', '進行中': 'in_progress', '待審核': 'in_review',
          '已完成': 'done', '略過': 'skipped', '取消': 'cancelled'}
PRIORITY = {'rework': 0, 'in_progress': 1, 'todo': 2, 'in_review': 2, 'not_started': 3}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:32]


def public_user(ref):
    return {'id': ref.open_id, 'name': ref.name, 'avatar_url': ref.avatar_url} if ref else None


def urgency(item, today):
    due = item['deadline']
    return (not bool(due and due < today), due or '9999-12-31', PRIORITY.get(item['status'], 4),
            item['case']['code'] or '', item['kind'], item['id'])


class HomePanels:
    def __init__(self, nodes, sop=None):
        self.nodes = nodes
        self.sop = sop
        self.config = nodes.config
        self.cache = StaleCache(self.config.read_ttl_seconds, self.config.stale_max_seconds, nodes.clock)
        self.roster_cache = StaleCache(self.config.roster_ttl_seconds, self.config.stale_max_seconds, nodes.clock)

    def scope(self, data, user):
        return ReadScope(self.nodes.cfg.get('LARK_WORKER_ORGANIZATION', ''), self.nodes.cfg.get('LARK_APP_ID', ''),
                         user['id'], data['wid'], fingerprint([user.get('authz_version'), user.get('role'),
                         sorted(user.get('capabilities', [])), user.get('active', True)]))

    def read_table(self, scope, table, spec):
        projection = [name for name, _ in spec.values()]
        key = scope.key([self.config.base, getattr(self.config, table.value)], projection=projection)
        def load():
            with self.nodes.client() as client:
                self.nodes._check_roster_schema(client, table)
                return client.list_records(table, projection)
        return self.cache.get(key, load, revalidate=True)

    def roster(self, scope):
        def load():
            with self.nodes.client() as client:
                return fetch_roster(client, self.nodes._check_roster_schema)
        return self.roster_cache.get(scope.key([self.config.base, self.config.people_table]), load, allow_stale=False)

    def lark_items(self, state, data, user, scope, team, hidden_confirmations):
        org = self.nodes.cfg.get('LARK_WORKER_ORGANIZATION')
        if not self.config.enabled:
            return [], {}, None, 'disabled'
        if state.get('environment') != 'production' or not org or data['wid'] != 'lark-' + org:
            return [], {}, None, 'unavailable'
        if not self.config.writable or self.nodes.cfg.get('LARK_WORKER_IDENTITY') != 'application':
            return [], {}, None, 'unconfigured'
        with ThreadPoolExecutor(max_workers=3) as pool:
            reads = {name: pool.submit(self.read_table, scope, table, spec) for name, table, spec in
                     (('node_assignments', Table.NODES, NODE_FIELDS), ('tasks', Table.TASKS, TASK_FIELDS))}
            roster_future = pool.submit(self.roster, scope)
            sources = {}
            for name, future in reads.items():
                try:
                    sources[name] = future.result()
                except Failure as exc:
                    sources[name] = exc
            try:
                roster = roster_future.result().value
            except Failure:
                roster = None
        actor = actor_for(user, roster)
        manager = any(actor.manages(key) for key in CHAIN) if roster is not None or actor.override else None
        if team and not manager:
            raise HTTPException(403, '只有所屬組別經理或公司管理員可查看同組工作')
        nodes_read, tasks_read = sources['node_assignments'], sources['tasks']
        raw_nodes = [] if isinstance(nodes_read, Failure) else nodes_read.value
        raw_tasks = [] if isinstance(tasks_read, Failure) else tasks_read.value
        nodes = {r['record_id']: parse_node(r) for r in raw_nodes}
        tasks = {r['record_id']: parse_task(r) for r in raw_tasks}
        raw_by_id = {r['record_id']: r['fields'] for r in raw_nodes}
        task_fields = {r['record_id']: r['fields'] for r in raw_tasks}
        projects = defaultdict(list)
        for project in state.get('projects', []):
            if project.get('source_kind') in ('demo', 'mock', 'simulation'):
                continue
            rid = confirmation_record(project, self.config)
            if rid:
                projects[rid].append(project)
        labels = {value: key for key, value in NODE_LABELS.items()}
        groups = defaultdict(lambda: defaultdict(list))
        node_keys, node_groups = {}, {}
        duplicate_keys = Counter(row.assignment_key for row in nodes.values())
        for rid, row in nodes.items():
            fields = raw_by_id[rid]
            code = normalized_case(fields.get('確認單編號'))
            key = labels.get(text(fields.get('節點')).strip())
            if code and key and row.assignment_key == assignment_key(code, key):
                node_keys[rid] = (code, key)
                group = (code, tuple(sorted(link_ids(fields.get('工程確認單')))))
                node_groups[rid] = group
                groups[group][key].append(row)
        linked = {rid: tuple(t for t in tasks.values() if t.node_ids == (rid,)) for rid in nodes}
        chains = {}
        reports = self.nodes.reports() if self.nodes.reports else None
        for group, rows in groups.items():
            code, relations = group
            candidates = projects.get(relations[0], []) if len(relations) == 1 else []
            project = candidates[0] if len(candidates) == 1 and normalized_case(candidates[0].get('code')) == code else None
            skipped = frozenset(NodeKey(n['key']) for n in project.get('nodes', [])
                                if n.get('key') in NODE_LABELS and self.nodes.skipped_nodes(state, project, n)) if project else frozenset()
            snap = CaseSnapshot(code, {k: tuple(v) for k, v in rows.items()}, linked)
            evidence = applicable(evidence_of(project, state, reports), skipped) if project else {}
            chains[group] = derive_chain(facts_of(snap, skipped, evidence))
        items = []
        for kind, entries in (('node_assignment', nodes), ('task', tasks)):
            for rid, row in entries.items():
                parent_id = rid if kind == 'node_assignment' else row.node_ids[0] if len(row.node_ids) == 1 else None
                parent = nodes.get(parent_id)
                code, key = node_keys.get(parent_id, (None, None))
                assignees = list(row.owners) if kind == 'node_assignment' else [row.assignee] if row.assignee else []
                mine = any(ref.open_id == user['id'] for ref in assignees)
                outgoing = bool(row.assigned_by and row.assigned_by.open_id == user['id'] and assignees and not mine)
                managed = bool(key and actor.manages(key))
                if kind == 'task' and not key:
                    managed = actor.override or any(row.department in NODE_DEPARTMENTS[k] and actor.manages(k) for k in CHAIN)
                source_status = row.status if kind == 'node_assignment' else text(task_fields[rid].get('狀態')).strip()
                derived = chains[node_groups[parent_id]][key] if key else None
                duplicate = bool(parent and duplicate_keys[parent.assignment_key] > 1)
                review = bool(kind == 'node_assignment' and managed and derived is NodeStatus.IN_REVIEW and not duplicate)
                if not (mine or outgoing or review or (team and managed and assignees)):
                    continue
                if team and not managed:
                    continue
                relations = link_ids(raw_by_id.get(parent_id, {}).get('工程確認單'))
                if set(relations) & hidden_confirmations:
                    continue
                matches = projects.get(relations[0], []) if len(relations) == 1 else []
                project = matches[0] if len(matches) == 1 and normalized_case(matches[0].get('code')) == code else None
                case = {'id': project['id'] if project else None, 'code': code, 'name': project.get('name') if project else None,
                        'relation_state': 'verified' if project else 'unverified'}
                status = STATUS.get(derived if kind == 'node_assignment' and derived else source_status, 'unknown')
                if kind == 'node_assignment' and row.rejected and status != 'done':
                    status = 'rework'
                valid_tasks = [t for t in linked.get(rid, ()) if t.status is not TaskStatus.CANCELLED]
                deadlines = [t.deadline for t in valid_tasks if t.deadline]
                open_due = [t.deadline for t in valid_tasks if t.deadline and t.status is not TaskStatus.DONE]
                deadline = max(deadlines) if kind == 'node_assignment' and deadlines else row.deadline if kind == 'task' else None
                blockers = []
                if roster is None and not actor.override:
                    blockers.append('人員名冊權限待核對')
                if not project or key is None:
                    blockers.append('案件關聯待核對')
                if duplicate:
                    blockers.append('指派鍵重複，請管理員核對')
                if isinstance(tasks_read, Failure) or isinstance(nodes_read, Failure):
                    blockers.append('來源尚未完整，作業條件待核對')
                if derived is NodeStatus.NOT_STARTED:
                    blockers.append('等待前置節點')
                if source_status not in STATUS:
                    blockers.append('來源狀態待核對')
                enabled = state.get('settings', {}).get('external_enabled') is True
                if kind == 'task' and key:
                    allowed = task_permissions(actor, key, derived, TaskFacts(row.status, row.assignee and row.assignee.open_id,
                                                                           row.assigned_by and row.assigned_by.open_id)).edit_status
                else:
                    permissions = node_permissions(actor, key, derived, frozenset(ref.open_id for ref in assignees)) if key else {}
                    allowed = permissions.get(NodeAction.COMPLETE) or permissions.get(NodeAction.CREATE_TASK)
                target = {'view': 'project', 'project': project['id'], 'tab': 'flow', 'assignment_node': key.value} if project and key else None
                if target and kind == 'task':
                    target['assignment_task'] = rid
                item = {'id': f'{kind}/{self.config.base}/{self.config.node_table if kind == "node_assignment" else self.config.task_table}/{rid}',
                        'kind': kind, 'origin': 'lark', 'source': {'base': self.config.base, 'table_id': self.config.node_table if kind == 'node_assignment' else self.config.task_table, 'record_id': rid},
                        'case': case, 'node_key': key.value if key else None, 'title': NODE_LABELS[key] if kind == 'node_assignment' and key else row.title if kind == 'task' else '節點指派',
                        'status': status, 'source_status': source_status or None, 'derived_status': STATUS.get(derived) if derived else None,
                        'assignment_state': 'duplicate' if duplicate else 'assigned' if assignees else 'unassigned',
                        'assignees': [public_user(ref) for ref in assignees], 'assigned_by': public_user(row.assigned_by),
                        'deadline': deadline, 'next_due': min(open_due) if kind == 'node_assignment' and open_due else None,
                        'original_deadline': None, 'deadline_basis': 'related_tasks_max' if kind == 'node_assignment' else 'lark_task_deadline',
                        'can_execute': bool(enabled and allowed and not blockers and status not in ('done', 'skipped', 'cancelled')),
                        'blocked_reasons': blockers, 'target': target, 'detail': row.detail if kind == 'task' else row.reject_reason,
                        'assignment_method': row.method if kind == 'node_assignment' else None,
                        'completed_at': iso_time(row.finished_at if kind == 'node_assignment' else row.done_at),
                        '_mine': mine, '_outgoing': outgoing, '_review': review, '_team': team and managed and bool(assignees)}
                if kind == 'node_assignment' and project:
                    item['children'] = [{'id': t.record_id, 'title': t.title, 'deadline': t.deadline, 'status': t.status.value,
                                         'assignee': public_user(t.assignee), 'detail': t.detail} for t in valid_tasks]
                items.append(item)
        return items, sources, manager, None

    def local_items(self, state, user, panel):
        items = []
        for project in state.get('projects', []):
            for node in project.get('nodes', []):
                for task in node.get('tasks', []):
                    if not local_work_instance(project, task) or (task.get('owner_id') != user['id'] and panel != 'proxy'):
                        continue
                    home = build_home_task(state, project, node, task, user, now())
                    if not home['assigned']:
                        continue
                    detail = home['detail']
                    items.append({'id': 'local_workflow/' + task['id'], 'kind': 'local_workflow', 'origin': 'local_workflow',
                                  'source': None, 'case': {'id': project['id'], 'code': project.get('code'), 'name': project.get('name'), 'relation_state': 'verified'},
                                  'node_key': node.get('key'), 'title': task.get('title') or '本地 SOP 工作',
                                  'status': 'done' if task.get('status') == 'completed' else task.get('status'), 'source_status': task.get('status'),
                                  'assignees': [{'id': task['owner_id'], 'name': next((p['name'] for p in state['users'] if p['id'] == task['owner_id']), task['owner_id']), 'avatar_url': None}],
                                  'assigned_by': None, 'assignment_state': 'assigned', 'deadline': detail['risk']['current_due_date'], 'next_due': None,
                                  'original_deadline': None, 'deadline_basis': 'local_workflow',
                                  'can_execute': detail['actionable'], 'blocked_reasons': detail['blockers'], 'detail': detail.get('reason'), 'home_detail': detail,
                                  'target': {'view': 'project', 'project': project['id'], 'tab': 'flow', 'node': node['id'], 'task': task['id']},
                                  '_proxy': bool(detail.get('proxy')), '_mine': task.get('owner_id') == user['id']})
        if panel in ('confirmation', 'delegated'):
            queues = home_queues(state, user)
            for row in queues['awaiting_confirmation' if panel == 'confirmation' else 'delegated_by_me']:
                project = next((p for p in state['projects'] if p['id'] == row['project_id']), None)
                if not project or project.get('source_kind') in ('demo', 'mock', 'simulation'):
                    continue
                if row.get('task_id'):
                    task = next((t for n in project.get('nodes', []) for t in n.get('tasks', []) if t.get('id') == row['task_id']), None)
                    if not task or not local_work_instance(project, task):
                        continue
                items.append({'id': row['id'], 'kind': 'local_confirmation' if panel == 'confirmation' else 'local_assignment', 'origin': 'local_workflow',
                              'source': None, 'case': {'id': project['id'], 'code': project.get('code'), 'name': project.get('name'), 'relation_state': 'verified'},
                              'node_key': None, 'title': row['title'], 'status': 'todo', 'source_status': None, 'assignment_state': 'assigned', 'assignees': [],
                              'assigned_by': None, 'deadline': None, 'next_due': None, 'original_deadline': None, 'deadline_basis': 'local_workflow',
                              'can_execute': False, 'blocked_reasons': [row['reason']], 'detail': row['reason'],
                              'target': {'view': 'project', 'project': project['id'], 'tab': 'flow', 'node': row.get('node_id'), 'task': row.get('task_id')},
                              '_review': panel == 'confirmation', '_outgoing': panel == 'delegated'})
        return items

    def query(self, state, data, user, params):
        if not set(params) <= {'panel', 'scope', 'sort', 'limit', 'cursor', 'kinds', 'deadline', 'q', 'status'} or params.get('status', 'open') not in ('open', 'done'):
            raise HTTPException(422, '查詢參數錯誤')
        panel, scope_name = params.get('panel', 'assigned'), params.get('scope', 'mine')
        if params.get('status') == 'done':
            panel = 'completed'
        if panel not in PANELS or scope_name not in ('mine', 'team') or params.get('sort', 'urgency') != 'urgency':
            raise HTTPException(422, '查詢參數錯誤')
        try:
            limit = int(params.get('limit', 25))
        except ValueError:
            raise HTTPException(422, '查詢筆數錯誤') from None
        if not 1 <= limit <= 100:
            raise HTTPException(422, '查詢筆數錯誤')
        scope = self.scope(data, user)
        visible = filter_visible_cases(dict(state))
        visible_ids = {p['id'] for p in visible.get('projects', [])}
        hidden_confirmations = {confirmation_record(p, self.config) for p in state.get('projects', []) if p['id'] not in visible_ids} - {None}
        if not user.get('active', True):
            raise HTTPException(403, '此帳號已停用')
        if panel in ('proxy', 'local') or params.get('kinds') == 'sop_task':
            items, sources, manager, reason = [], {}, None, None
        else:
            items, sources, manager, reason = self.lark_items(visible, data, user, scope, scope_name == 'team', hidden_confirmations)
        if panel == 'confirmation' and manager is None and reason is None:
            reason = 'authorization_unavailable'
        if scope_name == 'team' and manager is not True:
            raise HTTPException(403, '無法核實同組工作權限')
        if scope_name == 'mine':
            items += self.local_items(visible, user, panel)
            sop_items = self.sop.personal_items(state, data['wid'], user) if self.sop else []
            items += sop_items
            if reason == 'disabled' and sop_items:
                reason = 'partial'
        if params.get('kinds') == 'sop_task' and scope_name == 'mine':
            items = [i for i in items if i['kind'] == 'sop_task']
            sources, reason = {}, None
        selector = {'assigned': lambda i: i['origin'] in ('lark', 'sop_local') and (i.get('_team') or i.get('_mine')),
                    'proxy': lambda i: i.get('_proxy'), 'confirmation': lambda i: i.get('_review'),
                    'delegated': lambda i: i.get('_outgoing'), 'completed': lambda i: i.get('_mine'),
                    'local': lambda i: i['origin'] == 'local_workflow' and i.get('_mine') and not i.get('_proxy')}[panel]
        items = [i for i in items if selector(i) and ((i['status'] == 'done') if panel == 'completed' else i['status'] not in ('done', 'cancelled', 'skipped'))]
        kinds = set(params.get('kinds', '').split(',')) - {''}
        if kinds:
            if not kinds <= {'node_assignment', 'task', 'local_workflow', 'local_confirmation', 'local_assignment', 'sop_task'}:
                raise HTTPException(422, '工作來源錯誤')
            items = [i for i in items if i['kind'] in kinds]
        if params.get('deadline') == 'unscheduled':
            items = [i for i in items if i['deadline'] is None]
        elif params.get('deadline') not in (None, '', 'all'):
            raise HTTPException(422, '期限篩選錯誤')
        q = params.get('q', '').strip().casefold()
        if q:
            items = [i for i in items if q in ' '.join(str(v or '') for v in (i['title'], i['case']['code'], i['case']['name'])).casefold()]
        today = datetime.fromtimestamp(self.nodes.clock(), timezone.utc).astimezone(ZoneInfo('Asia/Taipei')).date().isoformat()
        items.sort(key=lambda i: urgency(i, today))
        for item in items:
            item['overdue'] = bool(item['status'] != 'done' and item['deadline'] and item['deadline'] < today)
            item['due_today'] = item['status'] != 'done' and item['deadline'] == today
        states = {}
        for name, cached in sources.items():
            states[name] = {'readState': 'read_failed' if isinstance(cached, Failure) else 'stale' if cached.stale else 'complete',
                            'as_of': None if isinstance(cached, Failure) else datetime.fromtimestamp(cached.fetched_at, timezone.utc).isoformat(),
                            'refreshing': not isinstance(cached, Failure) and cached.stale_reason == 'refreshing'}
        complete = reason is None and all(s['readState'] in ('complete', 'stale') for s in states.values())
        counts = {name: sum(i['kind'] == kind for i in items) if reason is None and (name not in states or states[name]['readState'] != 'read_failed') else None
                  for name, kind in (('node_assignments', 'node_assignment'), ('tasks', 'task'), ('local_workflow', 'local_workflow'))}
        counts['sop_tasks'] = sum(i['kind'] == 'sop_task' for i in items)
        counts.update(count_scope='viewer_visible', complete=complete)
        # Task visibility can depend on a node relation, so a failed N read cannot prove T counts.
        if states.get('node_assignments', {}).get('readState') == 'read_failed' and scope_name == 'team':
            counts['tasks'] = None
        version = fingerprint([scope, visible.get('version'), params.get('scope'), panel, items, states, reason])
        query_hash = fingerprint([scope, {k: v for k, v in params.items() if k != 'cursor'}])
        offset = 0
        if cursor := params.get('cursor'):
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor))
                if decoded['query'] != query_hash or decoded['version'] != version or type(decoded['offset']) is not int or decoded['offset'] < 0:
                    raise ValueError()
                offset = decoded['offset']
            except (ValueError, KeyError, TypeError):
                raise HTTPException(409, {'code': 'cursor_expired', 'message': '工作清單已更新，請回第一頁'}) from None
        has_more = offset + limit < len(items)
        next_cursor = base64.urlsafe_b64encode(json.dumps({'query': query_hash, 'version': version, 'offset': offset + limit}).encode()).decode() if has_more else None
        stale = any(s['readState'] == 'stale' for s in states.values())
        as_of = min((s['as_of'] for s in states.values() if s['as_of']), default=None)
        return {'panel': panel, 'scope': scope_name, 'readState': reason or ('partial' if not complete else 'stale' if stale else 'complete_empty' if not items else 'complete'),
                'snapshot_version': version, 'as_of': as_of, 'source_as_of': None,
                'freshness': {'status': 'stale' if stale else 'fresh' if complete else 'unknown', 'last_success_at': as_of,
                              'refreshing': any(s['refreshing'] for s in states.values())},
                'sources': states, 'counts': counts, 'total_count': len(items) if complete else None, 'complete': complete,
                'manager_view_available': manager, 'count_scope': 'viewer_visible', 'filter_scope': 'viewer_visible',
                'items': [{k: v for k, v in i.items() if not k.startswith('_')} for i in items[offset:offset + limit]],
                'next_cursor': next_cursor, 'has_more': has_more, 'query_echo': {k: v for k, v in params.items() if k != 'cursor'}}

    def read_workspace(self, request, data, user):
        with self.sessions() as db:
            state = self.load(db, db.get(self.workspace_model, data['wid']))
        return self.read(request, data, user, state)

    def read(self, request, data, user, state):
        return self.query(state, data, user, dict(request.query_params))


def register(app, *, identity, load, sessions, workspace_model, nodes, sop=None):
    service = HomePanels(nodes, sop)
    service.sessions, service.load, service.workspace_model = sessions, load, workspace_model
    @app.get('/api/home-panels')
    def panels(request: Request):
        data, user = identity(request)
        body = service.read_workspace(request, data, user)
        return JSONResponse(body, headers={'Cache-Control': 'private, no-store'})
    return service
