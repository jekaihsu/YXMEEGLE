"""Read-only loader for a yx-workspace-backup archive (never extracts or writes)."""
import hashlib
import json
from collections import defaultdict
from zipfile import BadZipFile, ZipFile

SCHEMAS = ('yx-workspace-backup/1', 'yx-workspace-backup/2', 'yx-workspace-backup/3')
MAX_DATABASE_BYTES = 256 * 1024 * 1024
PROJECT_COLLECTIONS = ('projects', 'approvals', 'sop_requests')


class SnapshotError(ValueError):
    """Input is not a usable snapshot; message is safe to show."""


def read_snapshot(path):
    """Return (sha256 of the archive, {workspace_id: workspace dict})."""
    try:
        with open(path, 'rb') as handle:
            raw = handle.read()
        from io import BytesIO
        with ZipFile(BytesIO(raw)) as archive:
            names = archive.namelist()
            if 'manifest.json' not in names or 'database.json' not in names:
                raise SnapshotError('Snapshot lacks manifest.json or database.json')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('schema') not in SCHEMAS:
                raise SnapshotError('Unsupported snapshot schema')
            if archive.getinfo('database.json').file_size > MAX_DATABASE_BYTES:
                raise SnapshotError('database.json too large')
            payload = archive.read('database.json')
            if hashlib.sha256(payload).hexdigest() != manifest.get('sha256', {}).get('database.json'):
                raise SnapshotError('database.json checksum mismatch')
            rows = json.loads(payload)
    except SnapshotError:
        raise
    except (OSError, BadZipFile, ValueError, KeyError, AttributeError, TypeError) as error:
        raise SnapshotError(f'Cannot read snapshot: {type(error).__name__}') from None
    if not isinstance(rows, dict) or not isinstance(rows.get('workspaces'), list):
        raise SnapshotError('database.json has no workspaces table')
    return hashlib.sha256(raw).hexdigest(), assemble_workspaces(rows)


def assemble_workspaces(rows):
    """Rebuild nested workspaces, mirroring backend.storage.load for schema 2."""
    records = defaultdict(list)
    for row in rows.get('business_records') or []:
        if isinstance(row, dict) and isinstance(row.get('data'), dict):
            records[(row.get('workspace_id'), row.get('kind'), row.get('parent_id'))].append(row)
    result = {}
    for row in rows['workspaces']:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not isinstance(row.get('data'), dict):
            raise SnapshotError('Malformed workspace row')
        wid, data = row['id'], json.loads(json.dumps(row['data']))
        if data.get('storage_schema') == 2:
            def children(kind, parent):
                found = sorted(records.get((wid, kind, parent), []), key=lambda r: (r.get('ordinal', 0), str(r.get('entity_id'))))
                return [r['data'] for r in found]
            for collection in PROJECT_COLLECTIONS + ('users',):
                data[collection] = children(collection, '')
            for project in data['projects']:
                project['nodes'] = children('nodes', str(project.get('id')))
                for node in project['nodes']:
                    node['tasks'] = children('tasks', str(node.get('id')))
        result[wid] = data
    return result
