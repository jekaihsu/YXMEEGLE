"""Local planning cases: a quote and case created in this app only, never written to the 報價總表.

The production Base is not written: its automations are hidden from this app, 報價編號 is typed by hand with no
uniqueness check, and the source boundary has no outbound writes. A local case carries a reference that cannot be
mistaken for an official number, and holds an official 報價編號 only as a display field after a uniqueness check.
"""
import re

from ..sources import normalized_case
from ..v4_sources import blank_nodes
from . import quotes
from .domain import require

OFFICIAL_NUMBER = re.compile(r'\d{6}(?:-\d{1,2}){0,2}(?:-?[A-Z])?')


def reference(project_id):
    return 'LOCAL-' + project_id[:8].upper()


def official_number(value):
    if value is None or value == '':
        return None
    require(isinstance(value, str), 'quote_number_invalid')
    number = normalized_case(value).upper()
    require(bool(OFFICIAL_NUMBER.fullmatch(number)), 'quote_number_invalid')
    return number


def require_unused(number, state):
    """An official 報價編號 must not exist in the merged source register or on another local case."""
    if number:
        used = set(quotes.groups(state)) | {p.get('official_quote_no') for p in state.get('projects', [])}
        require(number not in used, 'quote_number_taken', 409)


def require_pm(pm_id, users):
    if pm_id:
        require(any(u['id'] == pm_id and u.get('active', True) and u.get('role') in ('pm', 'manager') for u in users),
                'pm_unresolved')


def published_template(state):
    return next(t for t in reversed(state['sop_templates']) if t['status'] == 'published')


def project(project_id, form, actor_id, sop, created_at):
    return {'id': project_id, 'code': reference(project_id), 'local_reference': reference(project_id),
            'official_quote_no': form['official_quote_no'], 'name': form['name'], 'client': form['client'],
            'description': form['description'], 'pm_id': form['pm_id'], 'created_by': actor_id, 'collaborator_ids': [],
            'planning_origin': 'local', 'case_visibility': 'local_planning', 'case_type': 'intake',
            'intake_status': 'local_planning', 'execution_system': 'pending', 'source_kind': 'local',
            'source_model': 'local', 'status': 'pending', 'priority': 'medium', 'due_date': None,
            'original_due_date': None, 'created_at': created_at, 'started_at': None, 'contract_amount': None,
            'estimated_points': None, 'revision': 1, 'quotes': [], 'source_records': [], 'source_record_ids': [],
            'nodes': blank_nodes(project_id, sop), 'files': [], 'comments': [], 'daily_reports': [],
            'sop_version': sop['id']}
