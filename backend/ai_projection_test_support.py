"""Legacy test names dispatch through the production dataset tool."""
from .ai.tools import execute as production_execute


async def execute(app, cookie, name, args):
    if name in ('search_cases', 'case_progress', 'case_owners', 'attendance_today'):
        params = dict(args)
        offset = params.pop('offset', 0)
        return await production_execute(app, cookie, 'query_dataset', dict(
            id=name, params=params, offset=offset, limit=8 if name == 'search_cases' else 20))
    return await production_execute(app, cookie, name, args)
