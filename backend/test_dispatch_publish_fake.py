"""In-memory V4 Bitable for dispatch publish tests: real REST shapes, client_token dedupe and fault hooks."""
import json
import threading
from urllib.parse import parse_qs

import httpx

from .dispatch_board.config import SOURCES

BASE = 'H7W6b0PFWaVF1BsgqXJj3pQ9pXb'
TASKS = SOURCES['tasks'].table_id
SCHEDULE = SOURCES['schedule'].table_id
PEOPLE = SOURCES['people'].table_id
NAMES = {'ou_jia': '甲', 'ou_yi': '乙', 'ou_bing': '丙', 'ou_gone': '離職', 'ou_pm': '派工PM', 'ou_lead': '組長',
         'ou_mgr': '經理', 'ou_pmf': '專案PM'}


def _kinds():
    kinds = {}
    for table in SOURCES.values():
        for name, types in table.fields.items():
            kinds.setdefault(table.table_id, {})[name] = types[0]
    return kinds


KINDS = _kinds()


class Crash(BaseException):
    """The process dies mid-request; nothing after the remote effect runs."""


def ok(data):
    return httpx.Response(200, json={'code': 0, 'msg': 'success', 'data': data})


class FakeLark:
    def __init__(self):
        self.tables = {table.table_id: {} for table in SOURCES.values()}
        self.lock = threading.RLock()
        self.requests, self.hooks, self.tokens = [], [], {}
        self.dedupe = True
        self.seq = 0

    def add(self, table, rid, fields):
        with self.lock:
            self.tables[table][rid] = {k: v for k, v in fields.items() if v not in (None, [], False, '')}
        return rid

    def on(self, method, suffix, hook, times=1):
        """hook(request, proceed) -> response; proceed() runs the normal handler."""
        self.hooks.append([method, suffix, hook, times])

    def creates(self):
        return [(m, p, q) for m, p, q in self.requests if m == 'POST' and p.endswith(f'/{TASKS}/records')]

    def writes(self):
        return [r for r in self.requests if r[0] in ('PUT', 'PATCH', 'DELETE')] + self.creates()

    def task_rows(self):
        with self.lock:
            return dict(self.tables[TASKS])

    def render(self, table, rid, style, names=None):
        out = {}
        for name, value in self.tables[table][rid].items():
            if names is not None and name not in names:
                continue
            kind = KINDS[table].get(name, 1)
            if kind == 11:
                value = [{'id': u['id'], 'name': NAMES.get(u['id'], ''), 'en_name': '', 'email': ''} for u in value]
            elif kind in (18, 21):
                value = {'link_record_ids': list(value)} if style == 'search' else [
                    {'record_ids': list(value), 'table_id': table, 'text': '', 'text_arr': [], 'type': 'text'}]
            elif kind == 1 and style == 'search':
                value = [{'text': value, 'type': 'text'}]
            out[name] = value
        return {'record_id': rid, 'fields': out}

    def __call__(self, request):
        path, method = request.url.path, request.method
        query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        self.requests.append((method, path, query))
        for hook in list(self.hooks):
            if hook[0] == method and path.endswith(hook[1]):
                hook[3] -= 1
                if hook[3] == 0:
                    self.hooks.remove(hook)
                return hook[2](request, lambda: self.handle(request, path, method, query))
        return self.handle(request, path, method, query)

    def handle(self, request, path, method, query):
        if path.endswith('/tenant_access_token/internal'):
            return httpx.Response(200, json={'code': 0, 'tenant_access_token': 't-synthetic', 'expire': 7200})
        parts = path.split('/')
        assert parts[:6] == ['', 'open-apis', 'bitable', 'v1', 'apps', BASE], path
        table, rest = parts[7], parts[8:]
        body = json.loads(request.content) if request.content else {}
        with self.lock:
            if rest == ['records'] and method == 'GET':
                names = set(json.loads(query['field_names'])) if 'field_names' in query else None
                items = [self.render(table, rid, 'list', names) for rid in sorted(self.tables[table])]
                return ok({'items': items, 'has_more': False, 'total': len(items)} if items else
                          {'has_more': False, 'total': 0})
            if rest == ['records', 'search']:
                conditions = body['filter']['conditions']
                hits = [self.render(table, rid, 'search', set(body.get('field_names') or []) or None)
                        for rid, f in sorted(self.tables[table].items())
                        if all(str(f.get(c['field_name'])) == c['value'][0] for c in conditions)]
                return ok({'items': hits, 'has_more': False, 'total': len(hits)} if hits else
                          {'has_more': False, 'total': 0})
            if rest == ['records'] and method == 'POST':
                token = query['client_token']
                if not self.dedupe or token not in self.tokens:
                    self.seq += 1
                    self.tokens[token] = self.add(table, f'recTask{self.seq:04d}', body['fields'])
                return ok({'record': self.render(table, self.tokens[token], 'get')})
            if len(rest) == 2 and method == 'GET':
                if rest[1] not in self.tables[table]:
                    return httpx.Response(200, json={'code': 1254043, 'msg': 'RecordIdNotFound'})
                return ok({'record': self.render(table, rest[1], 'get')})
            if len(rest) == 2 and method == 'PUT':
                if rest[1] not in self.tables[table]:
                    return httpx.Response(200, json={'code': 1254043, 'msg': 'RecordIdNotFound'})
                stored = self.tables[table][rest[1]]
                for name, value in body['fields'].items():
                    if value in (None, [], ''):
                        stored.pop(name, None)
                    else:
                        stored[name] = value
                return ok({'record': self.render(table, rest[1], 'get')})
        raise AssertionError((method, path))


def timeout_after(request, proceed):
    proceed()
    raise httpx.ReadTimeout('synthetic timeout after landing', request=request)


def timeout_before(request, proceed):
    raise httpx.ReadTimeout('synthetic timeout before landing', request=request)


def rejected(request, proceed):
    return httpx.Response(200, json={'code': 1254001, 'msg': 'synthetic WrongRequestBody'})


def crash_after(request, proceed):
    proceed()
    raise Crash()
