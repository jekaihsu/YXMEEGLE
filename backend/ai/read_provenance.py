"""Server-read scopes follow the authority boundary of the application endpoint."""
from contextvars import ContextVar
from urllib.parse import unquote

case_reads = ContextVar('ai_case_reads', default=None)
workspace_reads = ContextVar('ai_workspace_reads', default=None)


def observed(path, data, params=None):
    sink = case_reads.get()
    workspace_sink = workspace_reads.get()
    if path.startswith('/api/reports/'):
        if workspace_sink is not None:
            workspace_sink('report:' + path.split('/')[3])
        return
    if path in ('/api/projects', '/api/workspace'):
        if workspace_sink is not None:
            workspace_sink('portfolio')
        return
    if path == '/api/people/attendance':
        if workspace_sink is not None:
            workspace_sink('attendance')
        return
    if sink is None:
        return
    for field in ('project_id', 'case_id'):
        if (params or {}).get(field):
            sink(params[field])
            return
    parts = path.strip('/').split('/')
    if len(parts) >= 3 and parts[:2] in (['api', 'projects'], ['api', 'case-detail']):
        sink(unquote(parts[2]))
    elif workspace_sink is not None:
        workspace_sink('daily_reports' if path == '/api/daily-reports' else 'workspace')
