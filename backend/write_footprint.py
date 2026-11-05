"""Which part of a workspace each write action reads and writes.

A write that declares a footprint is loaded and saved as that part only: the named
collections whole, the named project trees whole, and nothing else. It runs on a
WorkspaceView that raises FootprintViolation the moment the mutation reaches anything
outside the declaration, so a partial view can never be saved by mistake. An action
without a rule here, or a request the rule cannot resolve, keeps the full load and save.
"""
from collections.abc import MutableMapping
from dataclasses import dataclass

from .storage import COLLECTIONS, FootprintViolation

# Records any mutation of a case may consult. All are small next to project trees; the large
# or unrelated collections (events, daily_unmatched, source rows, schedules) are left out.
CASE_RECORDS = frozenset({'users', 'approvals', 'delegations', 'approved_leave_delegations', 'input_revisions',
                          'financial_requests', 'sop_templates'})


@dataclass(frozen=True)
class Footprint:
    collections: frozenset
    project_ids: tuple


@dataclass(frozen=True)
class Rule:
    """collections are loaded whole; project says where the one case comes from; extra adds collections a payload needs."""
    collections: frozenset
    project: str = 'body'
    extra: object = None


class Lookup:
    """Primary key reads inside the write transaction, for rules whose case is found through a record."""

    def __init__(self, db, model, wid):
        self.db, self.model, self.wid = db, model, wid

    def row(self, kind, entity_id):
        from sqlalchemy import select
        m = self.model
        return self.db.execute(select(m.parent_id, m.data).where(m.workspace_id == self.wid, m.kind == kind, m.entity_id == str(entity_id))).first()


def _case_project(body, lookup):
    return (body.get('project_id'),) if body.get('project_id') else None


def _daily_projects(body, lookup):
    """The case a daily report is mapped to and the case that holds it now (a daily id exists once)."""
    payload = body.get('payload') or {}
    if body.get('action') == 'daily_propose':
        target, daily = body.get('project_id'), payload.get('daily_id')
    else:
        review = lookup.row('daily_reviews', payload.get('id'))
        if review is None: return None
        target, daily = review.data.get('project_id'), review.data.get('daily_id')
    held = lookup.row('project_daily_reports', daily) if daily else None
    projects = [target] + ([held.parent_id] if held else [])
    return tuple(dict.fromkeys(projects)) if all(projects) else None


PROJECT_RESOLVERS = {'body': _case_project, 'daily': _daily_projects}

RULES = {
    'task_start': Rule(CASE_RECORDS),
    'task_complete': Rule(CASE_RECORDS),
    'task_return': Rule(CASE_RECORDS),
    'task_add': Rule(CASE_RECORDS),
    'task_update': Rule(CASE_RECORDS),
    'comment_add': Rule(CASE_RECORDS, extra=lambda body: {'jobs'} if (body.get('payload') or {}).get('mentions') else ()),
    'node_complete': Rule(CASE_RECORDS),
    'review_submit': Rule(CASE_RECORDS),
    'review_vote': Rule(CASE_RECORDS),
    'evidence_submit': Rule(CASE_RECORDS),
    'evidence_approve': Rule(CASE_RECORDS),
    'file_link': Rule(CASE_RECORDS),
    'participants_update': Rule(CASE_RECORDS),
    'daily_propose': Rule(CASE_RECORDS | {'daily_unmatched', 'daily_reviews', 'source_work_items'}, project='daily'),
    'daily_approve': Rule(CASE_RECORDS | {'daily_unmatched', 'daily_reviews', 'source_work_items'}, project='daily'),
    'document_withdraw': Rule(CASE_RECORDS),
    'project_roles': Rule(CASE_RECORDS),
    'delegation_set': Rule(CASE_RECORDS),
    **{name: Rule(CASE_RECORDS) for name in ('node_skip_create', 'node_skip_submit', 'node_skip_vote', 'node_skip_apply', 'node_skip_withdraw')},
    'delivery_submit': Rule(CASE_RECORDS),
    'delivery_review': Rule(CASE_RECORDS),
}


def resolve(body, lookup=None):
    """The footprint for one /api/actions body, or None when the full path must run."""
    rule = RULES.get(body.get('action'))
    if rule is None: return None
    projects = PROJECT_RESOLVERS[rule.project](body, lookup)
    if not projects: return None
    extra = frozenset(rule.extra(body)) if rule.extra else frozenset()
    return Footprint(rule.collections | extra, tuple(projects))


class UnloadedProject(dict):
    """Stands in for a project outside the footprint: it has an id and nothing else."""
    unloaded = True

    def __init__(self, ident):
        super().__init__(); dict.__setitem__(self, 'id', ident)

    def _refuse(self, *args, **kwargs):
        raise FootprintViolation(f'project {dict.__getitem__(self, "id")} is outside the footprint')

    def __getitem__(self, key):
        if key == 'id': return dict.__getitem__(self, 'id')
        self._refuse()

    def get(self, key, default=None):
        if key == 'id': return dict.__getitem__(self, 'id')
        self._refuse()

    __contains__ = __iter__ = __len__ = __setitem__ = __delitem__ = __deepcopy__ = __copy__ = _refuse
    keys = values = items = pop = popitem = setdefault = update = copy = clear = _refuse


class ProjectList(list):
    """Every project in workspace order, the footprint's real and the rest unloaded; its shape is fixed."""

    def _refuse(self, *args, **kwargs):
        raise FootprintViolation('a partial write cannot add, remove or reorder projects')

    append = extend = insert = pop = remove = clear = sort = reverse = __setitem__ = __delitem__ = __iadd__ = _refuse


class EventLog(list):
    """New events only: history is never loaded, so a mutation may add to it but not search it."""

    def _refuse(self, *args, **kwargs):
        raise FootprintViolation('events are write-only in a partial write')

    __iter__ = __contains__ = index = count = sort = reverse = remove = pop = clear = _refuse

    def new(self):
        """The events added by this write, oldest last (the order event() inserts them)."""
        return [list.__getitem__(self, i) for i in range(list.__len__(self))]


class WorkspaceView(MutableMapping):
    """The state a partial mutation sees: allowed collections, the project list, root keys.

    `raw` is the plain loaded state that gets saved; the view shares its objects, so
    in-place edits land there, while whole-state operations are refused outright.
    """

    already_upgraded = True  # the state was upgraded when it was loaded; upgrade() would only touch collections that are not here

    def __init__(self, raw, allowed, project_order):
        self.raw = raw
        self.allowed = frozenset(allowed)
        real = {p['id']: p for p in raw['projects']}
        self._projects = ProjectList(real.get(pid) or UnloadedProject(pid) for pid in project_order)
        self._events = EventLog(raw['events'])
        raw['events'] = self._events

    def _check(self, key):
        if key in COLLECTIONS and key not in self.allowed and key not in ('projects', 'events'):
            raise FootprintViolation(f'{key} is outside the footprint')

    def __getitem__(self, key):
        self._check(key)
        if key == 'projects': return self._projects
        return self.raw[key]

    def get(self, key, default=None):
        self._check(key)
        if key == 'projects': return self._projects
        return self.raw.get(key, default)

    def __contains__(self, key):
        self._check(key)
        return key in self.raw

    def __setitem__(self, key, value):
        self._check(key)
        if key in ('projects', 'events'): raise FootprintViolation(f'{key} cannot be replaced by a partial write')
        self.raw[key] = value

    def __delitem__(self, key):
        self._check(key)
        if key in COLLECTIONS: raise FootprintViolation(f'{key} cannot be removed by a partial write')
        del self.raw[key]

    def setdefault(self, key, default=None):
        self._check(key)
        if key == 'projects': return self._projects
        return self.raw.setdefault(key, default)

    def __iter__(self):
        raise FootprintViolation('a partial write cannot walk the whole workspace')

    def __len__(self):
        raise FootprintViolation('a partial write cannot walk the whole workspace')

    def __bool__(self):
        return True

    def _whole(self, *args, **kwargs):
        raise FootprintViolation('a partial write cannot copy the whole workspace')

    copy = __copy__ = __deepcopy__ = _whole
