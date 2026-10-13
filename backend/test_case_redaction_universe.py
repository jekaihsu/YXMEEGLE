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


@pytest.mark.parametrize('path',LEAK_PATHS)
@pytest.mark.xfail(strict=True,reason='0716328 copied identity holder leaks')
def test_known_holder(isolated_http,path):
    app,client,_,signin=isolated_http
    state,records,_=build_universe();install(app,state);signin('u-manager')
    response=client.get('/api/workspace');assert response.status_code==200
    needles=forbidden(state,records)|{'recGhostX'}
    hits=[(p,s) for p,s in walk(response.json()) if '.'.join(p).startswith(path) and any(n in s for n in needles)]
    assert not hits,hits
