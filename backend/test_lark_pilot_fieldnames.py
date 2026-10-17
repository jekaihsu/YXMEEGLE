"""VCC-119: Lark search takes field NAMES; a transport that behaves like Lark must read cleanly."""
import json
import re

import httpx

from .test_live_read_client import CFG, Clock
from .live_read.rate_limit import TokenBucket
from .live_read.token_cache import TenantTokenCache

NAMES = {'tblmSQrcCs9vPQZx': ['工程確認單編號', '外業工作單'],
         'tbl5zPLS0ExWNEty': ['工作單號', '組長人員-津貼來源V2', '組員人員-津貼來源V2', '組長帳號-津貼自動化', '組員帳號-津貼自動化'],
         'tblfaCO2xPUNptQH': ['Lark帳號']}
ROWS = {'tblmSQrcCs9vPQZx': {'record_id': 'rec_SYN_c', 'fields': {'工程確認單編號': 'SYN', '外業工作單': ['rec_SYN_w']}},
        'tbl5zPLS0ExWNEty': {'record_id': 'rec_SYN_w', 'fields': {'工作單號': 1, '組長人員-津貼來源V2': ['rec_SYN_p']}},
        'tblfaCO2xPUNptQH': {'record_id': 'rec_SYN_p', 'fields': {'Lark帳號': [{'id': 'ou_SYN'}]}}}


def lark_like(request):
    if '/auth/' in request.url.path:
        return httpx.Response(200, json={'code': 0, 'tenant_access_token': 'SYN_token', 'expire': 7200})
    table = next((t for t in NAMES if t in request.url.path), None)
    if table is None:
        return httpx.Response(200, json={'code': 0, 'data': {'items': []}})
    wanted = json.loads(request.content)['field_names']
    if any(re.fullmatch(r'fld[A-Za-z0-9]+', name) or name not in NAMES[table] for name in wanted):
        return httpx.Response(400, json={'code': 1254045, 'msg': 'FieldNameNotFound'})
    row = ROWS[table]
    return httpx.Response(200, json={'code': 0, 'data': {'has_more': False, 'items': [
        {'record_id': row['record_id'], 'fields': {k: v for k, v in row['fields'].items() if k in wanted}}]}})


def test_pilot_read_against_name_only_lark_is_not_an_error():
    from .lark_pilot.sample import PilotReader
    clock = Clock()
    with PilotReader(CFG, transport=httpx.MockTransport(lark_like), clock=clock, sleep=clock.sleep,
                     bucket=TokenBucket(10, clock=clock, sleep=clock.sleep),
                     token_cache=TenantTokenCache(clock=clock)) as reader:
        result = reader.read()
    assert result['status'] in ('fresh', 'partial')
    assert result['table_states'] == {'cases': 'present', 'work_orders': 'present', 'people': 'present'}
    # Response keys are mapped back to field IDs for projection.
    case = result['records']['cases'][0]['fields']
    assert case['fldgZDflpb'] == {'state': 'present', 'value': 'SYN'}
    assert case['flddfFq9zI']['state'] == 'present'
    assert result['records']['people'][0]['identity']['ids'] == ['ou_SYN']


def test_unexpected_response_field_key_is_a_clear_error_code():
    from .lark_pilot.sample import PilotReader
    def drifted(request):
        res = lark_like(request)
        if res.status_code == 200 and b'record_id' in res.content:
            return httpx.Response(200, json={'code': 0, 'data': {'items': [{'record_id': 'rec_SYN', 'fields': {'fldgZDflpb': 'x'}}]}})
        return res
    clock = Clock()
    with PilotReader(CFG, transport=httpx.MockTransport(drifted), clock=clock, sleep=clock.sleep,
                     bucket=TokenBucket(10, clock=clock, sleep=clock.sleep),
                     token_cache=TenantTokenCache(clock=clock)) as reader:
        result = reader.read()
    assert result['status'] == 'error' and result['receipt']['outcome'] == 'partial'


def read_with(handler):
    from .lark_pilot.sample import PilotReader
    clock = Clock()
    with PilotReader(CFG, transport=httpx.MockTransport(handler), clock=clock, sleep=clock.sleep,
                     bucket=TokenBucket(10, clock=clock, sleep=clock.sleep),
                     token_cache=TenantTokenCache(clock=clock)) as reader:
        return reader.read()


def test_receipt_carries_non_secret_upstream_diagnostics():
    from .lark_pilot.sample import CASES
    def reject(request):
        if CASES in request.url.path and request.url.path.endswith('/search'):
            return httpx.Response(400, json={'code': 1254045, 'msg': 'SYN_body_secret'})
        return lark_like(request)
    result = read_with(reject)
    assert result['receipt']['upstream_status'] == 400 and result['receipt']['lark_code'] == 1254045
    assert result['receipt']['error_kind'] == 'field_not_found' and result['code'] == 'lark_field_not_found'
    denied = read_with(lambda r: httpx.Response(403, json={'code': 1254302}) if r.url.path.endswith('/tables') else lark_like(r))
    assert (denied['receipt']['upstream_status'], denied['receipt']['lark_code']) == (403, 1254302)
    assert denied['receipt']['error_kind'] == 'permission_denied'
    timeout = read_with(lambda r: (_ for _ in ()).throw(httpx.ReadTimeout('SYN_t')) if '/auth/' not in r.url.path else lark_like(r))
    assert timeout['receipt']['error_kind'] == 'transient' and '逾時' in timeout['last_error']
    assert len({result['last_error'], denied['last_error'], timeout['last_error']}) == 3
    assert not any(s in json.dumps([result, denied, timeout]) for s in ('SYN_body_secret', 'SYN_token', 'Bearer'))


def test_live_link_shape_link_record_ids_is_extracted():
    """Live Lark link cells are {"link_record_ids": [...]}; an empty link is {}."""
    from .lark_pilot.shadow import field, ids, link
    live = {'flddfFq9zI': {'link_record_ids': ['recB', 'recA']}, 'fldlqnGoTh': {'link_record_ids': ['recA']}, 'fldvSpUqa9': {}}
    assert ids(live['flddfFq9zI']) == ['recA', 'recB'] and ids(live['fldlqnGoTh']) == ['recA']
    assert ids({}) == [] and ids(live.get('missing')) == []
    assert ids({'record_ids': ['recC']}) == ['recC'] and ids(['recD']) == ['recD']  # existing shapes still work
    present = field(live, 'flddfFq9zI')['value']
    assert link(present, ['recA', 'recB'], 'present') == {'state': 'resolved', 'ids': ['recA', 'recB']}
    assert link(present, ['recA'], 'present')['state'] == 'dangling'
    assert link(live['fldvSpUqa9'], [], 'present') == {'state': 'unmapped', 'ids': []}
    assert link(field(live, 'fldJs4RTUm').get('value'), [], 'present')['state'] == 'unmapped'  # omitted field


def cases_only(link_ids):
    def handler(request):
        res = lark_like(request)
        if 'tblmSQrcCs9vPQZx' in request.url.path and b'record_id' in res.content:
            return httpx.Response(200, json={'code': 0, 'data': {'has_more': False, 'items': [
                {'record_id': 'rec_SYN_c', 'fields': {'工程確認單編號': 'SYN', '外業工作單': link_ids}}]}})
        return res
    return handler


def test_cases_without_links_reason_is_no_linked_records_not_failure():
    result = read_with(cases_only([]))
    assert result['status'] == 'partial' and 'code' not in result and result['last_error'] is None
    assert result['table_reasons'] == {'work_orders': 'no_linked_records', 'people': 'no_linked_records'}
    assert result['table_states']['cases'] == 'present' and result['table_states']['work_orders'] == 'not_read'


def test_linked_filter_rejected_1254018_reason_is_traversal_unavailable():
    def handler(request):
        if 'tbl5zPLS0ExWNEty' in request.url.path and b'"filter"' in request.content:
            return httpx.Response(400, json={'code': 1254018, 'msg': 'SYN_body'})
        return lark_like(request)
    result = read_with(handler)
    assert result['table_reasons']['work_orders'] == 'traversal_unavailable'
    assert result['receipt']['lark_code'] == 1254018 and result['status'] == 'partial'


def test_people_1254302_reason_is_access_denied_with_permission_needed():
    def handler(request):
        if 'tblfaCO2xPUNptQH' in request.url.path:
            return httpx.Response(403, json={'code': 1254302, 'msg': 'RolePermNotAllow'})
        return lark_like(request)
    result = read_with(handler)
    assert result['table_reasons']['people'] == 'access_denied'
    assert result['receipt']['permission_needed'] and result['receipt']['lark_code'] == 1254302
    assert result['table_states']['people'] == 'forbidden'


def test_transport_failure_reason_is_read_failed():
    def handler(request):
        if 'tbl5zPLS0ExWNEty' in request.url.path:
            return httpx.Response(200, json={'code': 0, 'data': {'items': [{'fields': {}}]}})
        return lark_like(request)
    assert read_with(handler)['table_reasons']['work_orders'] == 'read_failed'
