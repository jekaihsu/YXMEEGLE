"""Copy only the selected case's derived maps in read-only partial captures."""
from copy import deepcopy
from .storage import COLLECTIONS

CASE_MAPS = frozenset({'derived_plan', 'source_work_items_status'})


def root_metadata(data, project_ids, *, scoped=False):
    selected = set(project_ids or ())
    result = {}
    for key, value in data.items():
        if key in COLLECTIONS:
            continue
        if scoped and key in CASE_MAPS and isinstance(value, dict):
            value = {pid: facts for pid, facts in value.items() if pid in selected}
        result[key] = deepcopy(value)
    return result
