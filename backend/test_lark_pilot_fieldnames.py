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
