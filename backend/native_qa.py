"""Isolated approval transport acceptance. Never imports or mutates workspaces.

QA bindings deliberately lack production project/workspace identity. They cannot
be applied by the production receipt checker. No approve/reject/cancel API exists
here: people use their own Lark account to decide a QA instance.
"""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote
from uuid import uuid4

from .native_approval import digest, verify_definition, verify_instance
from .lark_adapter import RemoteFailure

PURPOSE = 'native_qa_transport_only'
APP_ID = 0x51414150
KINDS = {'extension': {'supervisor'}, 'change': {'pm', 'supervisor'},
         'node_skip': {'pm', 'supervisor'}, 'financial': {'pm', 'admin'}}


class QAError(Exception):
    """Stable safe code only; never expose remote responses or credentials."""


def ensure(value, code):
    if not value:
        raise QAError(code)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def policy(manifest, credentials):
    ensure(isinstance(manifest, dict) and manifest.get('schema_version') == 1
           and manifest.get('purpose') == PURPOSE, 'qa_manifest_required')
    ensure(manifest.get('app_id') == credentials.get('LARK_APP_ID') and manifest.get('app_id')
           and manifest.get('tenant') == credentials.get('LARK_WORKER_ORGANIZATION')
           and manifest.get('tenant') in {x.strip() for x in credentials.get('LARK_ALLOWED_TENANTS', '').split(',')}
           and credentials.get('LARK_WORKER_IDENTITY') == 'application', 'qa_company_mismatch')
    ensure(credentials.get('LARK_APP_SECRET'), 'credentials_missing')
    try:
        production = json.loads(credentials.get('LARK_NATIVE_APPROVAL_MAPPINGS_JSON', '{}'))
        codes = {production[k]['approval_code'] for k in KINDS}
        ensure(all(isinstance(c, str) and c for c in codes), 'production_inventory_required')
    except (ValueError, TypeError, KeyError):
        raise QAError('production_inventory_required') from None
    codes.update(credentials.get(key) for key in ('LARK_CHANGE_APPROVAL_CODE', 'LARK_EXTENSION_APPROVAL_CODE',
                 'LARK_NODE_SKIP_APPROVAL_CODE', 'LARK_FINANCIAL_APPROVAL_CODE') if credentials.get(key))
    mapping = manifest.get('mapping') or {}
    kind = mapping.get('kind')
    ensure(kind in KINDS and isinstance(mapping.get('approval_code'), str)
           and re.fullmatch(r'[A-Za-z0-9_-]{6,128}', mapping['approval_code']), 'qa_mapping_invalid')
    ensure(mapping['approval_code'] not in codes, 'production_definition_forbidden')
    expected_name = manifest.get('definition_name')
    ensure(isinstance(expected_name, str) and ('QA' in expected_name.upper() or '驗收' in expected_name), 'qa_definition_name_required')
    ensure(set(mapping.get('fields', {})) == {'binding', 'content'}, 'qa_two_field_contract_required')
    seats = [seat for node in mapping.get('nodes', []) for seat in node.get('seats', [])]
    ensure(set(seats) == KINDS[kind] and len(seats) == len(KINDS[kind]), 'qa_seats_mismatch')
    participants = manifest.get('participants') or {}
    applicant, approvers = participants.get('applicant'), participants.get('approvers') or {}
    ensure(isinstance(approvers, dict) and set(approvers) == KINDS[kind], 'qa_approvers_mismatch')
    identities = [applicant, *approvers.values()]
    ensure(all(isinstance(x, str) and re.fullmatch(r'ou_[A-Za-z0-9]+', x) for x in identities), 'qa_exact_open_ids_required')
    ensure(len(set(approvers.values())) == len(approvers), 'qa_distinct_approvers_required')
    allowed = participants.get('allowlist')
    ensure(isinstance(allowed, list) and all(isinstance(x, str) for x in allowed)
           and len(allowed) == len(set(allowed)) and set(allowed) == set(identities), 'qa_exact_allowlist_required')
    authorization = manifest.get('authorization') or {}
    ensure(all(isinstance(authorization.get(k), str) and authorization[k].strip()
               for k in ('decision_ref', 'authorized_by', 'reason', 'expires_at')), 'qa_authorization_required')
    try:
        expiry = datetime.fromisoformat(authorization['expires_at'].replace('Z', '+00:00'))
        ensure(expiry.tzinfo is not None and expiry > datetime.now(timezone.utc), 'qa_authorization_expired')
    except (ValueError, TypeError):
        raise QAError('qa_authorization_expired') from None
    return {'manifest_hash': digest(manifest), 'production_inventory_hash': digest(sorted(codes)),
            'app_id': manifest['app_id'], 'tenant': manifest['tenant']}


class QAStore:
    """Dedicated SQLite, durable before POST; never open an application DB."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            app_id = db.execute('PRAGMA application_id').fetchone()[0]
            tables = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            ensure(app_id == APP_ID or (app_id == 0 and not tables), 'not_a_qa_database')
            db.execute(f'PRAGMA application_id={APP_ID}')
            db.execute('''CREATE TABLE IF NOT EXISTS qa_runs (
                run_id TEXT PRIMARY KEY, version INTEGER NOT NULL, binding TEXT NOT NULL,
                attempted INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL,
                receipt TEXT, last_error TEXT, updated_at TEXT NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS qa_audit (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, action TEXT NOT NULL,
                status TEXT NOT NULL, recorded_at TEXT NOT NULL)''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def unpack(row):
        ensure(row is not None, 'qa_run_not_found')
        result = dict(row)
        result['binding'] = json.loads(result['binding'])
        result['receipt'] = json.loads(result['receipt']) if result['receipt'] else None
        return result

    def get(self, run_id):
        with self.connect() as db:
            return self.unpack(db.execute('SELECT * FROM qa_runs WHERE run_id=?', (run_id,)).fetchone())

    def prepare(self, run_id, binding):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM qa_runs WHERE run_id=?', (run_id,)).fetchone()
            if row:
                existing = self.unpack(row)
                ensure(existing['binding']['policy'] == binding['policy'], 'qa_run_policy_changed')
                ensure(existing['binding']['definition_hash'] == binding['definition_hash'], 'qa_definition_changed')
                return existing
            db.execute('INSERT INTO qa_runs VALUES (?,?,?,?,?,?,?,?)',
                       (run_id, 1, json.dumps(binding), 0, 'prepared', None, None, stamp()))
            db.execute('INSERT INTO qa_audit(run_id,action,status,recorded_at) VALUES (?,?,?,?)',
                       (run_id, 'prepare', 'prepared', stamp()))
        return self.get(run_id)

    def claim(self, run_id, expected):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self.unpack(db.execute('SELECT * FROM qa_runs WHERE run_id=?', (run_id,)).fetchone())
            if current['attempted']:
                return current, False
            ensure(current['version'] == expected, 'qa_concurrent_update')
            binding = current['binding']; binding['attempted'] = True
            db.execute('UPDATE qa_runs SET binding=?,attempted=1,status=?,version=version+1,updated_at=? WHERE run_id=?',
                       (json.dumps(binding), 'outcome_unknown', stamp(), run_id))
            db.execute('INSERT INTO qa_audit(run_id,action,status,recorded_at) VALUES (?,?,?,?)',
                       (run_id, 'attempt_committed_before_post', 'outcome_unknown', stamp()))
        return self.get(run_id), True

    def save(self, record, status, *, receipt=None, error=None, binding=None):
        with self.connect() as db:
            cursor = db.execute('''UPDATE qa_runs SET binding=?,status=?,receipt=?,last_error=?,
                version=version+1,updated_at=? WHERE run_id=? AND version=?''',
                (json.dumps(binding or record['binding']), status, json.dumps(receipt) if receipt else None,
                 error, stamp(), record['run_id'], record['version']))
            ensure(cursor.rowcount == 1, 'qa_concurrent_update')
            db.execute('INSERT INTO qa_audit(run_id,action,status,recorded_at) VALUES (?,?,?,?)',
                       (record['run_id'], 'transport_checkpoint', status, stamp()))
        return self.get(record['run_id'])


def receipt_output(record):
    receipt = record.get('receipt') or {}
    return {'purpose': PURPOSE, 'run_id': record['run_id'], 'version': record['version'],
            'attempted': bool(record['attempted']), 'status': record['status'],
            'uuid': record['binding']['payload']['uuid'], 'instance_code': receipt.get('instance_code') or record['binding'].get('instance_code'),
            'external_status': receipt.get('external_status'), 'binding_verified': receipt.get('binding_verified', False),
            'approved': receipt.get('approved', False), 'business_apply_allowed': False,
            'last_error': record.get('last_error')}


class QARunner:
    def __init__(self, store, load_config, adapter_factory):
        self.store, self.load_config, self.adapter_factory = store, load_config, adapter_factory

    def config(self):
        manifest, credentials = self.load_config()
        return manifest, credentials, policy(manifest, credentials)

    def authorize(self, expected):
        manifest, credentials, current = self.config()
        ensure(current == expected, 'qa_policy_changed')
        return manifest, credentials

    def definition(self, adapter, manifest, expected):
        self.authorize(expected)
        definition = adapter.request('GET', '/approval/v4/approvals/' + quote(manifest['mapping']['approval_code'], safe=''),
                                     params={'user_id_type': 'open_id'})
        self.authorize(expected)
        ensure(isinstance(definition, dict) and definition.get('approval_name') == manifest['definition_name'], 'qa_definition_name_mismatch')
        return definition, verify_definition(definition, manifest['mapping'])

    def prepare(self, run_id):
        ensure(isinstance(run_id, str) and re.fullmatch(r'qa-[A-Za-z0-9_-]{3,80}', run_id), 'qa_run_id_required')
        manifest, credentials, expected = self.config()
        adapter = self.adapter_factory(deepcopy(credentials))
        try:
            _, definition_hash = self.definition(adapter, manifest, expected)
            identity = {'schema': 'native-qa-binding-v1', 'purpose': PURPOSE,
                        'app_id': manifest['app_id'], 'tenant': manifest['tenant'],
                        'qa_workspace_id': 'qa:' + manifest['tenant'], 'qa_run_id': run_id,
                        'version': 1, 'policy_hash': digest(expected)}
            mapping = manifest['mapping']; participants = manifest['participants']
            values = {'binding': json.dumps(identity, sort_keys=True, ensure_ascii=False),
                      'content': json.dumps({'purpose': PURPOSE, 'qa_run_id': run_id,
                          'notice': 'QA transport acceptance only. No project, date, finance, or business authorization is changed.',
                          'kind': mapping['kind']}, sort_keys=True)}
            payload = {'approval_code': mapping['approval_code'], 'open_id': participants['applicant'],
                       'uuid': str(uuid4()), 'allow_resubmit': False, 'allow_submit_again': False,
                       'form': json.dumps([{'id': field['id'], 'type': field['type'], 'value': values[key]}
                                           for key, field in mapping['fields'].items()], ensure_ascii=False),
                       'node_approver_open_id_list': [{'key': node['id'],
                           'value': [participants['approvers'][seat] for seat in node['seats']]} for node in mapping['nodes']]}
            binding = {'purpose': PURPOSE, 'identity': identity, 'policy': expected,
                       'kind': mapping['kind'], 'mapping': deepcopy(mapping), 'definition_hash': definition_hash,
                       'approvers': deepcopy(participants['approvers']), 'payload': payload}
            binding['qa_binding_hash'] = digest(binding)
            binding['attempted'] = False
            self.authorize(expected)
            return receipt_output(self.store.prepare(run_id, binding))
        finally:
            adapter.client.close()

    def checked_record(self, run_id):
        record = self.store.get(run_id); binding = record['binding']
        immutable = {k: binding[k] for k in ('purpose', 'identity', 'policy', 'kind', 'mapping', 'definition_hash', 'approvers', 'payload')}
        ensure(binding.get('purpose') == PURPOSE and binding.get('qa_binding_hash') == digest(immutable), 'qa_binding_tampered')
        ensure(binding['identity'].get('qa_run_id') == run_id and 'project_id' not in binding['identity']
               and 'workspace_id' not in binding['identity'], 'qa_namespace_required')
        manifest, credentials = self.authorize(binding['policy'])
        return record, manifest, credentials

    def poll(self, run_id):
        record, manifest, credentials = self.checked_record(run_id)
        if not record['attempted']:
            return receipt_output(record)
        adapter = self.adapter_factory(deepcopy(credentials))
        try:
            try:
                _, fingerprint = self.definition(adapter, manifest, record['binding']['policy'])
                ensure(fingerprint == record['binding']['definition_hash'], 'qa_definition_changed')
                self.authorize(record['binding']['policy'])
                instance = adapter.request('GET', '/approval/v4/instances/' + quote(record['binding']['payload']['uuid'], safe=''),
                                           params={'user_id_type': 'open_id'})
                self.authorize(record['binding']['policy'])
                receipt = verify_instance(record['binding'], instance)
                receipt['verified_at'] = stamp()
                record = self.store.save(record, receipt['external_status'].lower(), receipt=receipt)
            except RemoteFailure:
                record = self.store.save(record, 'outcome_unknown', error='remote_result_unverified')
            except (KeyError,TypeError,ValueError,AttributeError):
                record = self.store.save(record, 'outcome_unknown', error='remote_result_malformed')
            except QAError as exc:
                if str(exc) == 'qa_concurrent_update':
                    raise
                record = self.store.save(record, 'verification_blocked', error=str(exc))
            return receipt_output(record)
        finally:
            adapter.client.close()

    def create(self, run_id, *, allow_create=False):
        ensure(allow_create is True, 'explicit_allow_create_required')
        record, manifest, credentials = self.checked_record(run_id)
        if record['attempted']:
            return self.poll(run_id)
        adapter = self.adapter_factory(deepcopy(credentials))
        try:
            _, fingerprint = self.definition(adapter, manifest, record['binding']['policy'])
            ensure(fingerprint == record['binding']['definition_hash'], 'qa_definition_changed')
            self.authorize(record['binding']['policy'])
            record, claimed = self.store.claim(run_id, record['version'])
            if claimed:
                # This checkpoint survives a crash before, during or after POST.
                # Even a definitive rejection is never automatically retried.
                try:
                    self.authorize(record['binding']['policy'])
                    result = adapter.request('POST', '/approval/v4/instances', json=deepcopy(record['binding']['payload']))
                    self.authorize(record['binding']['policy'])
                    ensure(isinstance(result, dict) and result.get('instance_code'), 'qa_create_result_unknown')
                    binding = deepcopy(record['binding']); binding['instance_code'] = result['instance_code']
                    self.store.save(record, 'outcome_unknown', binding=binding)
                except RemoteFailure:
                    self.store.save(record, 'outcome_unknown', error='remote_create_outcome_unknown')
                except QAError as exc:
                    if str(exc) == 'qa_concurrent_update':
                        raise
                    self.store.save(record, 'outcome_unknown', error=str(exc))
        finally:
            adapter.client.close()
        return self.poll(run_id)
