"""What a case's own live data proves, shared by the node-assignment overlay and GET /progress so both agree.

Pure. A row flagged ``source_missing`` was deleted at the source and is never evidence.
"""
import re

from .sources import normalized_case

C_CODE = re.compile(r'[Cc](\d+)')


def live_confirmation_fields(state, project) -> list[dict]:
    """Field dicts of the case's live confirmations: the workspace rows, else the project's own source records."""
    pid = project.get('id')
    rows = [c for c in (state or {}).get('source_confirmations') or []
            if c.get('project_id') == pid and c.get('source_kind') == 'confirmation' and not c.get('source_missing')]
    if rows:
        return [c.get('fields') or {} for c in rows]
    return [r.get('fields') or {} for r in project.get('source_records') or []
            if isinstance(r, dict) and r.get('kind') == 'confirmation' and not r.get('source_missing')]


def live_contract_lines(state, project) -> list[dict]:
    pid = project.get('id')
    return [c for c in (state or {}).get('contract_items') or [] if c.get('project_id') == pid and not c.get('source_missing')]


def is_c_code(code) -> bool:
    """C + digits (a suffix such as -01 is fine), never the all-zero placeholder the reports register ignores."""
    found = C_CODE.match(normalized_case(code))
    return bool(found) and int(found.group(1)) != 0


def proves_sales_by_code(project) -> bool:
    return project.get('case_type') != 'intake' and is_c_code(project.get('code'))
