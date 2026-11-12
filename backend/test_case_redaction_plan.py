"""Identity and admission plan contracts."""
from copy import deepcopy
from . import case_redaction as cr
from .case_universe import build_universe
from .source_case_policy import filter_visible_cases, identity
from .source_entities import entity_id
from .sources import source_id


def test_identity_forms_use_real_builders():
    state, records, _ = build_universe()
    for record in records:
        if record['kind'] not in ('confirmation', 'quote'):continue
        row = dict(source_identity=record, id=entity_id(record), source_url='https://x?record='+record['record_id'])
        assert {record['record_id'], entity_id(record), identity(record), source_id(record)} <= cr.forms(row)
    assert cr.forms({'url':'https://x?record=recOnlyUrl'}) == {'recOnlyUrl'}
    assert cr.forms({'review_quote_id':'src-only-snapshot'}) == {'src-only-snapshot'}


def test_plan_uses_policy_and_protects_visible_project_collisions():
    state, records, _ = build_universe(); before=cr.snapshot(state)
    after=deepcopy(state);filter_visible_cases(after);plan=cr.make_plan(before,after)
    by_id={r['record_id']:r for r in records}
    assert source_id(by_id['recCaseB']) in plan.hidden
    assert identity(by_id['recCaseB']) in plan.hidden
    assert source_id(by_id['recCaseA']) in plan.admitted
    assert 'C115902' in plan.hidden_codes
    assert 'C115901' not in plan.hidden_codes
    # A visible project's own identity wins even if its entity was withheld.
    p=after['projects'][0];p['source_identity']=by_id['recCaseB'];p['code']='C115902'
    collision=cr.make_plan(before,after)
    assert source_id(by_id['recCaseB']) in collision.admitted
    assert source_id(by_id['recCaseB']) not in collision.hidden
    assert 'C115902' not in collision.hidden_codes
