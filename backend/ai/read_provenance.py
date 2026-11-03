"""Task-local collection of successful application reads, never model claims."""
from contextvars import ContextVar
from urllib.parse import unquote

case_reads = ContextVar('ai_case_reads', default=None)
case_code_reads = ContextVar('ai_case_code_reads', default=None)


def observed(path, data, params=None):
    sink = case_reads.get()
    if sink is None:
        return
    for field in ('project_id', 'case_id'):
        if (params or {}).get(field):
            sink(params[field])
    code_sink = case_code_reads.get()
    if path.startswith('/api/reports/') and code_sink is not None:
        from ..reports.compute import case_codes
        for row in data.get('items', []):
            codes = case_codes(row.get('case_code') or (row.get('code') if path == '/api/reports/sales' else ''))
            for code in codes:
                code_sink(code)
            if not codes and (path == '/api/reports/sales' or row.get('case_name')):
                # A named report case without a resolvable code cannot be
                # silently treated as a workspace-only read.
                code_sink('')
    parts = path.strip('/').split('/')
    if len(parts) >= 3 and parts[:2] in (['api', 'projects'], ['api', 'case-detail']):
        sink(unquote(parts[2]))
    if path == '/api/projects':
        for project in data.get('items', []):
            if project.get('id'):
                sink(project['id'])
    def walk(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('project_id', 'case_id') and isinstance(child, str) and child:
                    sink(child)
                elif key in ('project_ids', 'projects') and isinstance(child, list):
                    for project in child:
                        ident = project.get('id') if isinstance(project, dict) else project
                        if isinstance(ident, str) and ident:
                            sink(ident)
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(data)
