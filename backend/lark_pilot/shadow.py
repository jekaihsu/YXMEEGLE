"""Pure projection. Missing fields and denied relationships are not empty data."""
def field(fields, key):
    if key not in fields:
        return {'state': 'omitted'}
    return {'state': 'null'} if fields[key] is None else {'state': 'present', 'value': fields[key]}


def ids(value):
    if isinstance(value, dict):
        value = value.get('record_ids', value.get('link_record_ids', []))
    if not isinstance(value, list):
        return []
    return sorted({item if isinstance(item, str) else item.get('record_id', '') if isinstance(item.get('record_id', ''), str) else ''
                   for item in value if isinstance(item, (str, dict))} - {''})


def identities(value):
    if not isinstance(value, list):
        return {'state': 'category_unknown', 'ids': []}
    keys = sorted({p['id'] for p in value if isinstance(p, dict) and isinstance(p.get('id'), str) and p['id']})
    return {'state': 'id_matched' if keys else 'id_missing', 'ids': keys}


def link(value, found, table_state):
    keys = ids(value)
    state = ('denied' if table_state == 'forbidden' else 'unmapped' if table_state != 'present'
             else 'empty' if value == [] else 'unmapped' if not keys
             else 'resolved' if set(keys) <= set(found) else 'dangling')
    return {'state': state, 'ids': keys}


def project(item, table, fields, source, fetched_at):
    return {'record_id': item['record_id'], 'table_id': table, 'source': source,
            'fetched_at': fetched_at, 'freshness': 'fresh',
            'fields': {key: field(item.get('fields', {}), key) for key in fields}, 'links': {}}
