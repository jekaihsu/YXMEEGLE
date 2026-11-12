"""Mock Lark adapter: per-field CAS, durable operation-ID ledger, fencing and fault injection."""
from dataclasses import dataclass, field

from . import values as V
from .store import MemoryStore

BINDING = 'mock-binding-v1'


class AdapterError(V.OpsError):
    code = 'adapter_error'


class AdapterTimeout(AdapterError):
    """Ambiguous: the write may or may not have committed."""
    code = 'timeout'


class TransientNoCommit(AdapterError):
    """Documented safe failure: the write did not commit."""
    code = 'transient'

    def __init__(self, message='', retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


class ServerError(AdapterError):
    code = 'server_error'


class PermissionDenied(AdapterError):
    code = 'permission_denied'


class SchemaMismatch(AdapterError):
    code = 'schema_binding_mismatch'


class CasMismatch(AdapterError):
    code = 'cas_mismatch'

    def __init__(self, current_revision):
        super().__init__('field revision changed')
        self.current_revision = current_revision


class StaleFence(AdapterError):
    code = 'stale_fence'


@dataclass
class Observation:
    complete: bool
    values: dict = field(default_factory=dict)      # field_id -> SetValue | CLEAR | UNKNOWN
    revisions: dict = field(default_factory=dict)   # field_id -> int (only when readable)
    binding_version: str = BINDING
    reason: str = ''


class MockLarkAdapter:
    """State lives in an injected store (own namespace) so it survives simulated restarts and is shared across processes."""
    live = False

    def __init__(self, store=None):
        self.store = store or MemoryStore()
        self.faults = []   # in-process one-shot faults: dicts {kind, ...}

    # -- test controls -------------------------------------------------------------------
    def inject(self, kind, times=1, **options):
        self.faults.extend(dict(kind=kind, **options) for _ in range(times))

    def _fault(self, *kinds):
        for index, item in enumerate(self.faults):
            if item['kind'] in kinds:
                return self.faults.pop(index)
        return None

    def _state(self, ns):
        ns.setdefault('fields', {})
        ns.setdefault('ledger', {})
        ns.setdefault('fence', {})
        ns.setdefault('binding', BINDING)
        ns.setdefault('write_count', 0)
        return ns

    def set_binding(self, binding):
        self.store.transact(lambda ns: self._state(ns).__setitem__('binding', binding))

    def direct_edit(self, entity_id, field_id, value):
        """A direct Lark editor changes a field outside the controlled writer."""
        V.coerce(field_id, value)

        def edit(ns):
            ns = self._state(ns)
            slot = ns['fields'].setdefault(f'{entity_id}|{field_id}', {'revision': 0, 'value': V.encode(V.CLEAR), 'op_id': None})
            slot.update(revision=slot['revision'] + 1, value=V.encode(value), op_id=None)
            return slot['revision']
        return self.store.transact(edit)

    @property
    def write_count(self):
        return self.store.snapshot().get('write_count', 0)

    # -- reads ---------------------------------------------------------------------------
    def read(self, entity_id, field_ids):
        if self._fault('forbidden_read'):
            raise PermissionDenied('read forbidden')
        partial = self._fault('partial_read')
        ns = self._state(self.store.snapshot())
        obs = Observation(complete=True, binding_version=ns['binding'])
        for index, field_id in enumerate(field_ids):
            if partial and index == 0:
                obs.values[field_id] = V.UNKNOWN
                obs.complete = False
                obs.reason = 'partial_read'
                continue
            slot = ns['fields'].get(f'{entity_id}|{field_id}')
            obs.values[field_id] = V.decode(slot['value']) if slot else V.CLEAR
            obs.revisions[field_id] = slot['revision'] if slot else 0
        return obs

    def ledger_lookup(self, op_id):
        if self._fault('ledger_unreadable'):
            raise PermissionDenied('ledger unreadable')
        return self.store.snapshot().get('ledger', {}).get(op_id)

    def seal(self, entity_id, fence):
        """Reject any in-flight write carrying a lower fence for this entity."""
        def apply(ns):
            ns = self._state(ns)
            ns['fence'][entity_id] = max(ns['fence'].get(entity_id, 0), fence)
        self.store.transact(apply)

    # -- writes --------------------------------------------------------------------------
    def write(self, op_id, entity_id, field_id, expected_revision, value, binding_version, fence):
        if self._fault('permission_lost'):
            raise PermissionDenied('write forbidden')
        if self._fault('timeout_before_commit'):
            raise AdapterTimeout('timeout before commit')
        transient = self._fault('transient')
        if transient:
            raise TransientNoCommit('transient', transient.get('retry_after', 0))
        digest = V.fingerprint({'e': entity_id, 'f': field_id, 'x': expected_revision, 'v': V.encode(value)})

        def apply(ns):
            ns = self._state(ns)
            if binding_version != ns['binding']:
                raise SchemaMismatch(f'binding {binding_version} != {ns["binding"]}')
            if fence < ns['fence'].get(entity_id, 0):
                raise StaleFence('fence is stale')
            ns['fence'][entity_id] = max(ns['fence'].get(entity_id, 0), fence)
            prior = ns['ledger'].get(op_id)
            if prior:
                if prior['fingerprint'] != digest:
                    raise AdapterError('operation id reused with a different payload', 'op_collision')
                return dict(prior)
            slot = ns['fields'].setdefault(f'{entity_id}|{field_id}', {'revision': 0, 'value': V.encode(V.CLEAR), 'op_id': None})
            if slot['revision'] != expected_revision:
                raise CasMismatch(slot['revision'])
            slot.update(revision=slot['revision'] + 1, value=V.encode(value), op_id=op_id)
            receipt = {'op_id': op_id, 'entity_id': entity_id, 'field_id': field_id, 'revision': slot['revision'],
                       'fingerprint': digest}
            ns['ledger'][op_id] = receipt
            ns['write_count'] += 1
            return dict(receipt)
        receipt = self.store.transact(apply)
        if self._fault('timeout_after_commit'):
            raise AdapterTimeout('timeout after commit')
        if self._fault('server_error_after_commit'):
            raise ServerError('500 after commit')
        if self._fault('malformed_after_commit'):
            return {'garbled': True}
        return receipt
