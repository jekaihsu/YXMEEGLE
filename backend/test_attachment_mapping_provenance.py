"""Attachment ownership follows exact source IDs, never display metadata."""
from .source_projection import update_attachments
from .sources import import_sources, source_id
from .test_new_daily_acceptance import daily, link, setup


def record(*, file_token='token', field_present=True):
    fields = {'附件': [{'file_token': file_token, 'name': 'same.pdf'}]} if field_present else {}
    return {'base_token': 'base', 'table_id': 'table', 'record_id': 'recDaily',
            'kind': 'daily', 'attachment_fields': ['附件'], 'fields': fields}


def workspace():
    return {'projects': [{'id': 'case-a', 'source_records': [], 'nodes': []},
                         {'id': 'case-b', 'source_records': [], 'nodes': []}]}


def test_exact_daily_assignment_and_unresolved_reference_keep_explicit_mapping_state():
    ws = workspace(); daily = record(); sid = source_id(daily)
    update_attachments(ws, [daily], project_by_source={sid: 'case-a'})
    attachment = ws['source_attachment_index'][0]
    assert (attachment['project_id'], attachment['mapping_status'], attachment['status']) == ('case-a', 'matched', 'indexed')
    assert [a['id'] for a in ws['projects'][0]['source_attachments']] == [attachment['id']]
    update_attachments(ws, [daily], project_by_source={})
    attachment = ws['source_attachment_index'][0]
    assert (attachment['project_id'], attachment['mapping_status']) == (None, 'unmatched')
    assert all(not p['source_attachments'] for p in ws['projects'])


def test_imported_daily_native_record_link_controls_attachment_case():
    ws, records = setup()
    report = daily(**{'所屬案件': link('confirmation', 'recCaseA'),
                      '附件': [{'file_token': 'source-token', 'name': 'report.pdf'}]})
    report['attachment_fields'] = ['附件']
    import_sources(ws, records + [report])
    attachment = ws['source_attachment_index'][0]
    first_case = next(p for p in ws['projects'] if p['code'] == 'C115901')
    assert attachment['source_record_id'] == source_id(report)
    assert (attachment['project_id'], attachment['mapping_status']) == (first_case['id'], 'matched')
    report['fields']['所屬案件'] = link('confirmation', 'recUnknown')
    import_sources(ws, records + [report])
    attachment = ws['source_attachment_index'][0]
    assert (attachment['project_id'], attachment['mapping_status']) == (None, 'unmatched')
    assert all(not p['source_attachments'] for p in ws['projects'])
    report['fields']['所屬案件'] = link('confirmation', 'recCaseB')
    import_sources(ws, records + [report])
    second_case = next(p for p in ws['projects'] if p['code'] == 'C115902')
    attachment = ws['source_attachment_index'][0]
    assert (attachment['project_id'], attachment['mapping_status']) == (second_case['id'], 'matched')


def test_current_source_without_attachment_token_never_promotes_stale_metadata_to_case():
    ws = workspace(); daily = record(); sid = source_id(daily)
    update_attachments(ws, [daily], project_by_source={sid: 'case-a'})
    daily['fields'] = {}
    update_attachments(ws, [daily], project_by_source={sid: 'case-b'})
    attachment = ws['source_attachment_index'][0]
    assert (attachment['project_id'], attachment['mapping_status'], attachment['status']) == (None, 'unmatched', 'metadata_unavailable')
    assert not ws['projects'][0]['source_attachments']
    assert not ws['projects'][1]['source_attachments']
    update_attachments(ws, [daily], project_by_source={})
    attachment = ws['source_attachment_index'][0]
    assert (attachment['project_id'], attachment['mapping_status'], attachment['status']) == (None, 'unmatched', 'metadata_unavailable')
    assert all(not p['source_attachments'] for p in ws['projects'])
    table = {'base_token': 'base', 'table_id': 'table', 'status': 'ready', 'attachment_fields': ['附件']}
    update_attachments(ws, [daily], complete_tables=[table], project_by_source={sid: 'case-b'})
    attachment = ws['source_attachment_index'][0]
    assert (attachment['project_id'], attachment['mapping_status'], attachment['status']) == (None, 'unmatched', 'source_missing')
    daily['fields'] = {'附件': [{'file_token': 'token', 'name': 'same.pdf'}]}
    update_attachments(ws, [daily], complete_tables=[table], project_by_source={sid: 'case-b'})
    attachment = ws['source_attachment_index'][0]
    assert (attachment['project_id'], attachment['mapping_status'], attachment['status']) == ('case-b', 'matched', 'indexed')


def test_absent_source_in_partial_fetch_keeps_prior_mapping_and_complete_absence_marks_missing():
    ws = workspace(); daily = record(); sid = source_id(daily)
    update_attachments(ws, [daily], project_by_source={sid: 'case-a'})
    update_attachments(ws, [], project_by_source={})
    attachment = ws['source_attachment_index'][0]
    assert (attachment['project_id'], attachment['mapping_status'], attachment['status']) == ('case-a', 'matched', 'indexed')
    table = {'base_token': 'base', 'table_id': 'table', 'status': 'ready', 'attachment_fields': ['附件']}
    update_attachments(ws, [], complete_tables=[table], project_by_source={})
    attachment = ws['source_attachment_index'][0]
    assert (attachment['project_id'], attachment['mapping_status'], attachment['status']) == ('case-a', 'matched', 'source_missing')
    update_attachments(ws, [daily], complete_tables=[table], project_by_source={})
    attachment = ws['source_attachment_index'][0]
    assert (attachment['project_id'], attachment['mapping_status'], attachment['status']) == (None, 'unmatched', 'indexed')
