"""Stable source fingerprints include mapping/schema but exclude read metadata."""
import hashlib
import json
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

MAPPING_KEYS = ('base_token', 'table_id', 'kind', 'department', 'cost_table_id', 'linked_tables')
SIGNED_QUERY_KEYS = frozenset({'signature', 'sign', 'token', 'expires', 'expire',
                              'timestamp', 'auth', 'auth_key', 'ossaccesskeyid',
                              'policy', 'credential', 'security-token'})


def _attachment(value):
    if isinstance(value, list):
        return [_attachment(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == 'tmp_url':
            continue
        if key == 'url' and isinstance(item, str):
            url = urlsplit(item)
            query = [(name, val) for name, val in parse_qsl(url.query, keep_blank_values=True)
                     if name.lower() not in SIGNED_QUERY_KEYS
                     and not name.lower().startswith(('x-amz-', 'x-goog-', 'x-oss-'))]
            item = urlunsplit((url.scheme, url.netloc, url.path, urlencode(sorted(query)), url.fragment))
        result[key] = _attachment(item)
    return result


def _mapping(item):
    return dict({key: item.get(key) for key in MAPPING_KEYS},
                attachment_fields=sorted(item.get('attachment_fields') or []))


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False)


def fingerprint(snapshot):
    records = []
    for record in snapshot['records']:
        attachments = set(record.get('attachment_fields') or [])
        fields = {key: _attachment(value) if key in attachments else value
                  for key, value in (record.get('fields') or {}).items()}
        records.append(dict(_mapping(record), record_id=record['record_id'], fields=fields))
    tables = []
    for table in snapshot.get('tables') or []:
        tables.append(dict(_mapping(table), name=table.get('name'), count=table.get('count'),
                           status=table.get('status'), field_names=sorted(table.get('field_names') or []),
                           field_schema=sorted(table.get('field_schema') or [], key=_json)))
    canonical = _json(dict(status=snapshot.get('status'), records=sorted(records, key=_json),
                           tables=sorted(tables, key=_json)))
    return 'sha256:' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()
