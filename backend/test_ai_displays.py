import json

import httpx2
import pytest
from openai import AsyncOpenAI

from .test_ai_database import app, client, ai_database_url
from .test_ai_api import BODY, events, live_server
from .test_ai_providers import wire
from .test_p2_int_routes import http
from .test_project_progress import progress
from .ai import providers
from .ai.tools import display_table, display_chart


def sdk_tool(app, client, monkeypatch, name, args):
    requests = []
    if name == 'search_cases':
        args = dict(status='all', owner='anyone', overdue=False, offset=0, **args)
    call = dict(type='function_call', id='fc_1', call_id='call_1', name=name,
                arguments=json.dumps(args), status='completed')
    def handler(request):
        requests.append(json.loads(request.content))
        output = [call] if len(requests) == 1 else []
        response = dict(id='resp_1', object='response', model='gpt-6.1-terra', status='completed', output=output,
            usage=dict(input_tokens=10, input_tokens_details=dict(cached_tokens=0), output_tokens=1,
                       output_tokens_details=dict(reasoning_tokens=0), total_tokens=11))
        values = ([dict(type='response.output_item.done', item=call, output_index=0, sequence_number=1)] if output else [])
        values.append(dict(type='response.completed', response=response, sequence_number=2))
        return httpx2.Response(200, headers={'content-type': 'text/event-stream'}, content=wire(values))
    monkeypatch.setattr(providers, 'AsyncOpenAI', lambda **kwargs: AsyncOpenAI(**kwargs,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))))
    app.state.ai_providers = {'gpt': providers.GPT('fictional')}
    result = events(client.post('/api/ai/chat', json=dict(BODY, model='gpt')))
    assert result[-1]['type'] == 'done', result
    sdk_tool.events = result
    done, = [e for e in result if e['type'] == 'tool' and e['status'] == 'done']
    projected = json.loads(requests[1]['input'][-1]['output'])
    return done.get('displays'), projected


def test_search_real_route_sdk_sse(app, client, monkeypatch):
    source = client.get('/api/projects').json()['items'][0]
    displays, projected = sdk_tool(app, client, monkeypatch, 'search_cases', dict(query=source['code']))
    assert displays == [dict(kind='table', title='案件搜尋結果', columns=[dict(key=k, label=v) for k, v in
        [('code', '案號'), ('name', '案名'), ('status_label', '案件狀態'), ('pm_id', 'PM'), ('due_date', '交期')]],
        rows=[{k: row.get(k) for k in ('code', 'name', 'status_label', 'pm_id', 'due_date')} for row in projected['cases']], truncated=False)]
    assert displays[0]['rows'][0]['name'] == source['name']


def test_owners_real_route_sdk_sse(app, client, monkeypatch):
    pid = client.get('/api/projects').json()['items'][0]['id']
    source = client.get('/api/case-detail/' + pid).json()
    displays, projected = sdk_tool(app, client, monkeypatch, 'case_owners', dict(case_id=pid))
    assert displays == [dict(kind='table', title='案件負責人', columns=[dict(key='role', label='職務或節點'),
        dict(key='owner', label='負責人')], rows=[dict(role='PM', owner=source['header']['pm']['name'])],
        truncated=False, note='節點指派資料無法取得')]


def test_progress_real_route_sdk_sse(app, client, monkeypatch):
    pid = client.get('/api/projects').json()['items'][0]['id']
    source = client.get('/api/projects/' + pid + '/progress').json()
    displays, projected = sdk_tool(app, client, monkeypatch, 'case_progress', dict(case_id=pid))
    assert projected['as_of'] == source['as_of']
    assert displays[:1] == [dict(kind='chart', title='案件階段完成百分比', variant='bars', unit='%',
        points=[dict(label='業務', value=100.0)],
        truncated=False, caption='截至 ' + source['as_of'],
        headline=dict(label='整體（已知階段平均；規則推算；另有 6 個階段進度未知）', value='100.0'),
        note='；'.join(g['message_zh'] for g in projected['gaps']))]
    assert projected['gaps']
    assert all(stage['state'] in ('active', 'waiting') for stage in projected['stages'][1:])


def test_display_caps_and_scalar_cells():
    rows = [dict(a='x' * 300, b={'private': True}, c=['private'], d=None, e=1) for _ in range(60)]
    table = display_table('title', [(k, k) for k in 'abcdefghi'], rows, {})
    assert len(table['columns']) == 8 and len(table['rows']) == 50 and table['truncated'] is True
    assert table['rows'][0] == dict(a='x' * 240, b=None, c=None, d=None, e=1, f=None, g=None, h=None)
    chart = display_chart('title', [dict(label=str(i), value=i) for i in range(20)], {})
    assert chart['points'] == [dict(label=str(i), value=i) for i in range(12)]
    assert chart['truncated'] is True
    json.dumps([table, chart], allow_nan=False)
    assert display_table('t', [('v', 'v')], [dict(v=float('nan'))], {})['rows'] == [dict(v=None)]
    safe = display_chart('t', [dict(label='x' * 300, value=1), dict(label='bad', value=float('inf'))], {})
    assert safe['points'] == [dict(label='x' * 240, value=1)] and safe['truncated']


def test_curl_real_app_sse_feedback(app, client, live_server):
    import subprocess
    from .test_ai_api import Fake
    from .ai.providers import ToolCall
    pid = client.get('/api/projects').json()['items'][0]['id']
    app.state.ai_providers = {'claude': Fake(calls=[ToolCall('owners', 'case_owners', dict(case_id=pid))])}
    cookie = '; '.join(f'{k}={v}' for k, v in client.cookies.items())
    base = ['curl', '-sS', '--max-time', '10', '-H', 'Content-Type: application/json', '-b', cookie]
    stream = subprocess.run([*base, '-N', '--data', json.dumps(BODY), live_server + '/api/ai/chat'],
                            capture_output=True, text=True, check=True).stdout
    values = [json.loads(line[6:]) for line in stream.splitlines() if line.startswith('data: ')]
    uid = values[0]['usage_id']
    done, = [v for v in values if v['type'] == 'tool' and v['status'] == 'done']
    assert done['displays'][0]['rows']
    feedback = subprocess.run([*base, '--data', json.dumps(dict(usage_id=uid, rating='up')),
                              live_server + '/api/ai/feedback'], capture_output=True, text=True, check=True).stdout
    assert json.loads(feedback) == dict(usage_id=uid, rating='up', reason=None)
    print('\n$ curl -N -b "$SESSION" -H "Content-Type: application/json" --data "$BODY" ' + live_server + '/api/ai/chat')
    print('data: ' + json.dumps(values[0], ensure_ascii=False))
    print('data: ' + json.dumps(done, ensure_ascii=False))
    print('$ curl -b "$SESSION" -H "Content-Type: application/json" --data \'{"usage_id":"' + uid + '","rating":"up"}\' ' + live_server + '/api/ai/feedback')
    print(feedback)


def test_display_projector_failure_keeps_answer(app, client, monkeypatch, caplog):
    from .ai import tools

    def broken(data):
        raise ValueError('private source content')

    monkeypatch.setitem(tools.DISPLAY_PROJECTORS, 'case_owners', broken)
    pid = client.get('/api/projects').json()['items'][0]['id']
    displays, projected = sdk_tool(app, client, monkeypatch, 'case_owners', dict(case_id=pid))
    assert displays is None
    assert projected['pm']
    texts = [e['delta'] for e in sdk_tool.events if e['type'] == 'text']
    assert any('無法以表格或圖表顯示' in text for text in texts), 'the user is told when a display is missing'
    warnings = [r.getMessage() for r in caplog.records if 'ai_display' in r.getMessage()]
    assert warnings == ['ai_display tool=case_owners exception=ValueError']


def test_search_partial_real_route_sdk_sse(app, client, monkeypatch):
    from copy import deepcopy
    from .test_backend import WorkspaceRow, BusinessRow, storage
    wid = app.state.signer.loads(client.cookies.get('meegle_session'))['wid']
    with app.state.sessions.begin() as db:
        row = db.get(WorkspaceRow, wid)
        state = storage.load(db, BusinessRow, row)
        template = state['projects'][0]
        for i in range(12):
            state['projects'].append(dict(deepcopy(template), id=f'ai-partial-{i}', code=f'AI-PARTIAL-{i}',
                                          nodes=[], quotes=[], daily_reports=[], changes=[]))
        row.data = storage.save(db, BusinessRow, wid, state)
    source = client.get('/api/projects?q=AI-PARTIAL&limit=8').json()
    assert source['total'] == 12 and len(source['items']) == 8
    displays, projected = sdk_tool(app, client, monkeypatch, 'search_cases', dict(query='AI-PARTIAL'))
    assert projected['truncated'] is True
    assert projected['note'] == '符合 12 筆，本頁列出 8 筆，起點 0'
    assert displays[0]['truncated'] is True
    assert displays[0]['note'] == projected['note']
    assert len(displays[0]['rows']) == 8


def test_prompt_repeats_display_caveats():
    from .ai.prompts import system_prompt
    prompt = system_prompt()
    assert 'note' in prompt and '自己的話' in prompt
    assert '部分資料' in prompt and 'truncated=true' in prompt
    assert 'as_of' in prompt and '不可捏造時間' in prompt
    assert 'gaps' in prompt and '摘要' in prompt


@pytest.mark.parametrize('truncated', [False, True])
def test_progress_known_percent_and_gaps_real_route(progress, monkeypatch, truncated):
    from .test_project_progress import chain_state, set_points
    run, client, app = progress
    state, pid, _ = chain_state()
    set_points(state, pid, '外業', [('10', '0'), ('20', '5'), ('4', '4')])
    state['derived_plan'][pid]['truncated'] = truncated
    assert run(state, pid).status_code == 200
    app.state.reports._refresh_error = True
    source = client.get('/api/projects/' + pid + '/progress').json()
    assert 'reports_stale' in {g['id'] for g in source['gaps']}
    displays, projected = sdk_tool(app, client, monkeypatch, 'case_progress', dict(case_id=pid))
    chart = displays[0]
    expected = [dict(label='業務', value=100.0), dict(label='PM', value=100.0), dict(label='確認單', value=100.0)]
    if not truncated:
        expected.append(dict(label='外業', value=73.5))
    assert chart['points'] == expected
    assert chart['headline'] == dict(
        label='整體（已知階段平均；規則推算' + ('；另有 4' if truncated else '、來源證據；另有 3') + ' 個階段進度未知）',
        value='100.0' if truncated else '93.4')
    assert chart['note'] == '；'.join(g['message_zh'] for g in projected['gaps'])
    assert '週報快照已過期，等待重新讀取' in chart['note']
    if truncated:
        assert '合約規劃項目過多，清單已截斷' in chart['note']


def test_prompt_has_no_banned_narration():
    from .ai.prompts import system_prompt
    prompt = system_prompt()
    assert '直接回答' in prompt
    assert '一句自然的話' in prompt
    assert '即使表格或圖表已顯示' not in prompt
    for phrase in ('已整理', '詳見上方結果', '依你可查看的資料'):
        assert phrase not in prompt
