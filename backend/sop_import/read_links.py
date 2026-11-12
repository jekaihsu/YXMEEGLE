"""Linear association of already-scoped, ordinal-sorted task links."""
from collections import defaultdict


def links_by_task(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.task_id].append(row)
    return grouped
