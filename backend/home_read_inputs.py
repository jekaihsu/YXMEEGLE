"""Assigned work uses imported chain evidence and separate LocalTask rows.

Other panels retain the full native workflow inputs. Keep approval facts for
explicit skips, daily evidence and all source identities used by visibility.
"""
from .storage import COLLECTIONS


def assigned_omissions():
    keep = {'users', 'projects', 'approvals', 'source_confirmations', 'contract_items'}
    return tuple(kind for kind in COLLECTIONS if kind not in keep)


def probe_root(row):
    """The initial availability/header probe never evaluates plan evidence."""
    from types import SimpleNamespace
    return SimpleNamespace(id=row.id, version=row.version,
        data={k:v for k,v in row.data.items() if k not in ('derived_plan','source_work_items_status')})
