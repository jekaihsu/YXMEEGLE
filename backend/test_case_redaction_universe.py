"""Public response oracle over a real-builder universe."""
import json
import pytest
from .case_universe import build_universe, forbidden, walk
from .test_public_case_http_boundaries import isolated_http
from .app import WorkspaceRow, BusinessRow
from . import storage

LEAK_PATHS=[
 'contract_items.[].history.[].snapshot.confirmation_ids.[]',
 'source_quotes.[].history.[].snapshot.confirmation_ids.[]',
 'source_quotes.[].history.[].snapshot.fields.此案確認單.[].record_ids.[]',
 'projects.[].source_entity_ids.source_confirmations.[]',
 'projects.[].source_entity_ids.source_quotes.[]',
 'projects.[].source_record_ids.[]',
 'projects.[].quotes.[].id','projects.[].quotes.[].source_url',
 'projects.[].source_record_history.[].id','projects.[].source_record_history.[].url',
 'projects.[].source_conflicts.quote:', 'policy_summary.[].source_conflicts.quote:',
 'policy_summary.[].closure.financial.incoming.quotes.[].quote_id',
 'policy_summary.[].closure.financial.incoming.quotes.[].source_url',
 'policy_summary.[].closure.missing.[]',
 'daily_reviews.[].entry.source_provenance.records.[].id',
 'daily_reviews.[].entry.source_provenance.unresolved.[].record_id',
 'source_case_review.[].identity','source_case_review.[].code.[]']


def install(app,state):
    with app.state.sessions.begin() as db:
        row=db.get(WorkspaceRow,'lark-boundary');row.data=storage.save(db,BusinessRow,row.id,state)


PENDING={'policy_summary.[].closure.missing.[]','daily_reviews.[].entry.source_provenance.unresolved.[].record_id'}
@pytest.mark.parametrize('path',[pytest.param(p,marks=pytest.mark.xfail(strict=True,reason='typed handler pending')) if p in PENDING else p for p in LEAK_PATHS])

def test_known_holder(isolated_http,path):
    app,client,_,signin=isolated_http
    state,records,_=build_universe();install(app,state);signin('u-manager')
    response=client.get('/api/workspace');assert response.status_code==200
    needles=forbidden(state,records)|{'recGhostX'}
    hits=[(p,s) for p,s in walk(response.json()) if '.'.join(p).startswith(path) and any(n in s for n in needles)]
    assert not hits,hits


def test_generic_net_preserves_unknown_containers():
    from . import case_redaction as cr
    hidden='recNonAdmitted'
    out={'rows':[{'id':'keep-row','unknown':hidden,'refs':[hidden,'safe'],hidden:1,
        'url':'https://x.test/base/b?record='+hidden}]}
    plan=cr.Plan(frozenset(),frozenset({hidden}),frozenset())
    cr.apply(out,plan)
    assert out == {'rows':[{'id':'keep-row','unknown':None,'refs':['safe'],'url':None}]}
    assert plan.fallback == 4


def test_differential_planting_every_collection(isolated_http):
    from copy import deepcopy
    from . import case_redaction as cr
    from .storage import COLLECTIONS
    app,client,_,signin=isolated_http
    original,records,_=build_universe();needles=forbidden(original,records)
    # Both runs preserve all real builder output and differ only in probe slots.
    from .source_case_policy import filter_visible_cases
    public=deepcopy(original);filter_visible_cases(public)
    responses=[]
    for token in (sorted(n for n in needles if not n.startswith('record=')),['NEUTRAL-PROBE']):
        state=deepcopy(public)
        def plant(value):
            if isinstance(value,dict):
                for child in list(value.values()):plant(child)
                value.update(zz_probe_s=token[0],zz_probe_l=list(token),zz_probe_k={x:1 for x in token})
            elif isinstance(value,list):
                for child in value:plant(child)
        for collection in set(COLLECTIONS)|{'projects'}:
            plant(state.setdefault(collection,[]))
        cr.apply(state,cr.make_plan(cr.snapshot(original),public))
        responses.append(state)
    def strip(value):
        if isinstance(value,dict):return {k:strip(v) for k,v in value.items() if not k.startswith('zz_probe')}
        if isinstance(value,list):return [strip(v) for v in value]
        return value
    assert strip(responses[0]) == strip(responses[1])
    # Scan probe slots independently of any legacy holders still awaiting L1/L2.
    probe_values=[s for path,s in walk(responses[0]) if any(k.startswith('zz_probe') for k in path)]
    assert not any(n in s for n in needles for s in probe_values)
