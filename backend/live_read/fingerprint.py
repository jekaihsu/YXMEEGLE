"""Content fingerprints ignore read timestamps and Lark pagination order."""
import hashlib
import json


def fingerprint(snapshot):
    """Hash source table/record identities and fields, including formula values."""
    records = [
        (record['table_id'], record['record_id'], record.get('fields') or {})
        for record in snapshot['records']
    ]
    canonical = json.dumps(
        sorted(records, key=lambda record: (record[0], record[1])),
        sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False,
    )
    return 'sha256:' + hashlib.sha256(canonical.encode('utf-8')).hexdigest()
