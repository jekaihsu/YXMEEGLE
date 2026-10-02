"""No remote I/O: verify daily and completion boundaries independently."""
from copy import deepcopy
from .test_new_daily_acceptance import setup,row,link
from .sources import import_sources
from .v4_sources import daily_source_version


def paired():
    ws,records=setup()
    records += [row('daily',ident,{'日期':'2026-09-28','組別':'控制','所屬案件':link('confirmation','recCaseA'),'備註':ident}) for ident in ('d1','d2')]
    import_sources(ws,records)
    p=next(p for p in ws['projects'] if p['code']=='C115901')
    for d in p['daily_reports']:
        ws['daily_reviews'].append({'id':'review-'+d['id'],'daily_id':d['id'],'project_id':p['id'],'status':'approved','source_version':daily_source_version(d)})
    return ws,records,p


def test_one_daily_edit_invalidates_only_its_manual_mapping():
    ws,records,p=paired();records[-1]['fields']['備註']='只修正這一筆'
    import_sources(ws,records)
    assert [r['status'] for r in ws['daily_reviews']]==['approved','invalidated']


def test_unrelated_confirmation_note_preserves_daily_identity_approval():
    ws,records,p=paired();records[0]['fields']['備註']='案件行政說明，未改日報身分'
    import_sources(ws,records)
    assert [r['status'] for r in ws['daily_reviews']]==['approved','approved']


def test_upstream_case_identity_change_revalidates_affected_daily():
    ws,records,p=paired();records[0]['fields']['工程確認單編號']='C115999'
    import_sources(ws,records)
    assert all(r['status']=='invalidated' for r in ws['daily_reviews'])


def test_daily_material_change_reopens_only_the_node_that_explicitly_references_it():
    from .operations import reconcile_daily_evidence
    ws,records,p=paired();d1,d2=p['daily_reports']
    n1=next(n for n in p['nodes'] if n['key']=='control');n2=next(n for n in p['nodes'] if n['key']=='mapping')
    for n,d in ((n1,d1),(n2,d2)):
        n['status']='completed'
        p['evidence'].append({'id':'proof-'+d['id'],'node_id':n['id'],'key':'daily','daily_id':d['id'],
                              'daily_source_version':daily_source_version(d),'status':'accepted'})
    before_tasks=deepcopy([n['tasks'] for n in p['nodes']])
    records[-2]['fields']['備註']='修訂引用中的工作紀錄'
    import_sources(ws,records);reconcile_daily_evidence(ws)
    assert n1['status']=='rework' and n2['status']=='completed'
    assert [e['status'] for e in p['evidence']]==['invalidated','accepted']
    assert before_tasks==[n['tasks'] for n in p['nodes']]
    count=len(ws['events']);reconcile_daily_evidence(ws);assert len(ws['events'])==count
