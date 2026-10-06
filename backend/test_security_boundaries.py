"""Regression coverage for hostile input, notifications and public projections."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import pytest
from fastapi import HTTPException
from .input_validation import validate_action, safe_reference_url
from .mention_notifications import notification_text, reserve_mentions
from .workspace_projection import public_person, public_source_cache, filter_private_workspace
from .business_policy import can_business_override, can_manage_roles, refresh_business_authority, ORDINARY_BACKUP_SCOPE
from .seed import seed
from .policy import upgrade
from .workflow import apply_action, is_pm


@pytest.mark.parametrize('payload', [
    {'title': {'text':'broken'}}, {'title':['broken']}, {'body':{'text':'not text'}},
    {'title':'x'*241}, {'body':'x'*10001}, {'mentions':'u-pm'},
    {'mentions':[{'id':'u-pm'}]}, {'nodes':['wrong']}, {'required':'false'},
    {'_business_authority':{}}, {'oauth_identity':{}}, {'points':float('nan')},
])
def test_action_rejects_hostile_payload_before_mutation(payload):
    with pytest.raises(HTTPException) as error:
        validate_action({'action':'task_add','payload':payload})
    assert error.value.status_code == 422


def test_aggregate_payload_has_byte_limit():
    with pytest.raises(HTTPException) as error:
        validate_action({'action':'input_draft','payload':{'parts':['x'*10000]*30}})
    assert error.value.status_code == 413


def test_object_title_cannot_be_persisted_by_direct_domain_call():
    state=upgrade(seed()); before=deepcopy(state); p=state['projects'][0]
    actor=next(u for u in state['users'] if u['id']==p['pm_id'])
    with pytest.raises(HTTPException):
        apply_action(state,actor,{'action':'task_add','project_id':p['id'],'node_id':p['nodes'][0]['id'],'payload':{'title':{'bad':'object'}}})
    assert state == before


@pytest.mark.parametrize('url', [
    'javascript:alert(1)','http://example.com','https://localhost/a','https://127.0.0.1',
    'https://10.0.0.1/a','https://192.168.1.1/a','https://[::1]/a',
    'https://2130706433/','https://0177.0.0.1/','https://admin@example.com/',
    'https://example.com:444/a','https://example.com\\@127.0.0.1/',
    'https://example.com/\u202etest', {'url':'https://example.com'},
])
def test_reference_url_rejects_unsafe_values(url):
    with pytest.raises(HTTPException):safe_reference_url(url)


def test_reference_url_preserves_public_https():
    url='https://yong-xiang-survey.jp.larksuite.com/base/verified?record=one#view'
    assert safe_reference_url(url)==url


def test_notification_has_only_one_server_link_even_with_spoofed_all_display_fields():
    evil='https://phishing.invalid/login'
    result=notification_text({'id':'p','code':evil,'name':evil},{'id':'c','body':evil}, {},
                             {'PUBLIC_APP_URL':'https://work.example/'},{'name':evil})
    assert evil not in result
    assert result.count('https://')==1 and 'https://work.example/#view=project' in result


def test_notification_reservation_is_all_or_nothing_and_expires():
    state={}; instant=datetime(2026,9,30,tzinfo=timezone.utc)
    for i in range(20):reserve_mentions(state,{'id':'actor'},['u'+str(i)],clock=instant)
    before=deepcopy(state)
    with pytest.raises(HTTPException) as error:reserve_mentions(state,{'id':'actor'},['new'],clock=instant)
    assert error.value.status_code==429 and state==before
    reserve_mentions(state,{'id':'actor'},['new'],clock=instant+timedelta(seconds=61))
    assert len(state['_mention_reservations'])==1


def test_notification_recipient_limit_spans_different_actors():
    state={}
    for i in range(10):reserve_mentions(state,{'id':str(i)},['recipient'])
    with pytest.raises(HTTPException) as error:reserve_mentions(state,{'id':'eleven'},['recipient'])
    assert error.value.status_code==429


def test_source_response_uses_allowlist_and_leaves_authoritative_cache_intact():
    original={'configured':True,'records':[
        {'kind':'daily','record_id':'rec1','base_token':'private','fields':{'工作內容':'觀測','薪資':88888,'工作日期-薪資':123,'組長帳號-津貼自動化':'private','new_unknown_payroll':999}},
        {'kind':'quote','record_id':'rec2','fields':{'契約價格(未稅)':12345,'案件負責人':[{'name':'同事','email':'private','salary':88888}]}}]}
    copy=deepcopy(original); public=public_source_cache(original)
    assert public['records'][0]['fields']=={'工作內容':'觀測'}
    assert public['records'][1]['fields']=={'契約價格(未稅)':12345,'案件負責人':[{'name':'同事'}]}
    assert original==copy and 'base_token' not in public['records'][0]


def test_person_public_allowlist_never_exposes_grant_or_other_person_authority():
    person={'id':'u','name':'同事','role':'manager','capabilities':['manage_people'],'oauth_identity':{},'_business_authority':{},'salary':99,'new_salary_formula':100,'directory_source':{},'identity_app_id':'app'}
    assert public_person(person)=={'id':'u','name':'同事','role':'manager'}
    assert public_person(person,include_authority=True)['capabilities']==['manage_people']


def test_workspace_keeps_normalized_daily_but_hides_raw_personnel_fields():
    state=upgrade(seed()); p=state['projects'][0];actor=state['users'][0]
    p['daily_reports']=[{'id':'day','description':'觀測','date':'2026-09-30','source_fields':{'薪資':88888}}]
    p['source_records']=[{'fields':{'薪資':88888}}]
    state['_mention_reservations']=[{'actor_id':'private'}]
    public=filter_private_workspace(state,actor)
    assert public['projects'][0]['daily_reports']==[{'id':'day','description':'觀測','date':'2026-09-30'}]
    assert 'source_records' not in public['projects'][0] and '_mention_reservations' not in public


def test_manager_role_alone_is_not_any_project_pm():
    manager={'id':'admin','role':'manager','active':True}
    assert can_manage_roles(manager) and not can_business_override(manager)
    assert not is_pm(manager,{'pm_id':'actual-pm'})


def test_explicit_backup_grant_is_recomputed_and_revocable():
    grant={'open_id':'admin','app_id':'app','tenant':'tenant','role':'manager','enabled':True,'grant_id':'g',
           'authorized_at':'2026-01-01T00:00:00+00:00','authorized_by':'owner','decision_ref':'owner-decision',
           'reason':'ordinary backup only','scopes':[ORDINARY_BACKUP_SCOPE]}
    cfg={'LARK_APP_ID':'app','LARK_WORKER_ORGANIZATION':'tenant','LARK_ALLOWED_TENANTS':'tenant','LARK_COMPANY_ADMIN_GRANTS_JSON':json.dumps([grant])}
    user={'id':'admin','role':'manager','active':True,'identity_app_id':'app','bootstrap_admin':True,
          'oauth_identity':{'open_id':'admin','app_id':'app','tenant':'tenant','source':'oauth_user_info','verified_at':'2026-01-01'}}
    refresh_business_authority(user,cfg)
    assert can_business_override(user) and is_pm(user,{'pm_id':'someone-else'})
    from .workflow import is_owner
    from .operations import can_vote
    state=upgrade(seed());state['users'].append(user);project=state['projects'][0]
    task=project['nodes'][0]['tasks'][0]
    assert is_owner(user,task,state,project)
    assert not can_vote(state,user,project,'pm',project['pm_id'])
    assert task['owner_id']!=user['id'] and project['pm_id']!=user['id']
    cfg['LARK_COMPANY_ADMIN_GRANTS_JSON']='[]'
    refresh_business_authority(user,cfg)
    assert not can_business_override(user) and not is_pm(user,{'pm_id':'someone-else'})


@pytest.mark.parametrize('length,ok', [(120, True), (121, False), (10000, False)])
def test_action_name_bounded_to_audit_column(length, ok):
    body = {'action': 'x'*length, 'payload': {}}
    if ok:
        assert validate_action(body) is body
        return
    with pytest.raises(HTTPException) as error:
        validate_action(body)
    assert error.value.status_code == 422


@pytest.mark.parametrize('action', ['x'*10000, 'task_add\x00evil', 'task\x1b[31m', 'a\u202eb', 'x'*121])
def test_audit_record_replaces_unsafe_action_with_digest(action):
    from . import audit
    class Row:
        def __init__(self, **kw): self.__dict__.update(kw)
    row = audit.record(Row, 'w', 'u', action, result='denied', request_id='r\x00id')
    assert row.action.startswith('rejected_action:') and len(row.action) <= 120
    assert row.data['action_rejected'] and row.data['action_length'] == len(action)
    assert row.data['request_id'] == 'rid'
    assert action not in json.dumps(row.data) and '\x00' not in json.dumps(row.data, ensure_ascii=False)


@pytest.mark.parametrize('action', ['x'*10000, 'task_add\x00evil', 'task_add\x1f'])
def test_actions_endpoint_rejects_hostile_action_with_safe_denied_audit(tmp_path, action):
    from fastapi.testclient import TestClient
    from sqlalchemy import select
    from .app import create_app, AuditRow
    from .test_backend import workspace
    app = create_app({'DATABASE_URL': f'sqlite:///{tmp_path}/a.db', 'UPLOAD_DIR': str(tmp_path/'u'),
                      'SESSION_SECRET': 'test-secret'*5, 'APP_ENV': 'development', 'DEMO_MODE': 'true'})
    client = TestClient(app); client.get('/api/session')
    response = client.post('/api/actions', json={'action': action, 'version': workspace(client)['version'],
                                                 'request_id': 'req\x00-1', 'payload': {}})
    assert response.status_code == 422
    with app.state.sessions() as db:
        rows = [r for r in db.scalars(select(AuditRow)) if r.data.get('result') == 'denied']
    assert len(rows) == 1
    row = rows[0]
    assert row.action.startswith('rejected_action:') and len(row.action) <= 120
    assert row.data['status'] == 422 and row.data['action_length'] == len(action)
    assert not any(c in json.dumps(row.data, ensure_ascii=False) for c in ('\x00', '\x1f'))
    assert action not in json.dumps(row.data)
