"""Task-local collection of successful application reads, never model claims."""
from contextvars import ContextVar
from urllib.parse import unquote

case_reads = ContextVar('ai_case_reads', default=None)


def observed(path, data):
    sink = case_reads.get()
    if sink is None:
        return
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
