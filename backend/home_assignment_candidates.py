"""Bound mine/assigned chain work while retaining dependencies and duplicates.

This is an input reduction, never an authorization decision. The ordinary Home
projection still verifies visibility, ownership, chain state and action gates.
"""
from .node_assignment.lark_table import _record, users
from .sources import link_ids, normalized_case, text


def assigned_rows(raw_nodes, raw_tasks, viewer):
    # Validate every record envelope before narrowing; malformed source data
    # must not become an apparently complete personal empty list.
    nodes = [(row, *_record(row)) for row in raw_nodes]
    tasks = [(row, *_record(row)) for row in raw_tasks]
    wanted = {rid for _, rid, fields in nodes
              if any(person.open_id == viewer for person in users(fields.get('負責人')))}
    owned_tasks = set()
    for _, rid, fields in tasks:
        assignee = next(iter(users(fields.get('負責人'))), None)
        if assignee and assignee.open_id == viewer:
            owned_tasks.add(rid)
            wanted.update(link_ids(fields.get('節點指派')))
    codes = {normalized_case(fields.get('確認單編號')) for _, rid, fields in nodes if rid in wanted} - {''}
    # All predecessor/successor nodes and their tasks are needed to derive the
    # owned node. Same-code relation groups and duplicate keys stay visible.
    selected = {rid for _, rid, fields in nodes
                if rid in wanted or normalized_case(fields.get('確認單編號')) in codes}
    keys = {text(fields.get('指派鍵')).strip() for _, rid, fields in nodes if rid in selected}
    selected.update(rid for _, rid, fields in nodes if text(fields.get('指派鍵')).strip() in keys)
    return ([row for row, rid, _ in nodes if rid in selected],
            [row for row, rid, fields in tasks
             if rid in owned_tasks or set(link_ids(fields.get('節點指派'))) & selected])
