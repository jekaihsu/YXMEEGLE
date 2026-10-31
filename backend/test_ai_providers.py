"""Exercise real SDK parsing against in-memory SSE responses."""
import asyncio
import json

import httpx2
import pytest
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from .ai import providers
from .ai.catalog import MODELS, Usage
from .ai.tools import TOOLS


def assert_strict_schema(value):
    if isinstance(value, dict):
        assert not set(value) & {'minLength', 'maxLength', 'pattern', 'format', 'minimum', 'maximum',
                                 'exclusiveMinimum', 'exclusiveMaximum', 'minItems', 'maxItems', 'uniqueItems'}
        if value.get('type') == 'object':
            assert value['additionalProperties'] is False
            assert set(value['required']) == set(value['properties'])
        for child in value.values():
            assert_strict_schema(child)
    elif isinstance(value, list):
        for child in value:
            assert_strict_schema(child)


def wire(events):
    return ''.join('event: ' + e['type'] + '\ndata: ' + json.dumps(e) + '\n\n' for e in events).encode()


def anthropic_events(reason='end_turn', fallback=False):
    model = 'claude-sonnet-5-5'
    result = [dict(type='message_start', message=dict(id='msg_test', type='message', role='assistant', model=model,
        content=[], stop_reason=None, stop_sequence=None, usage=dict(input_tokens=10, output_tokens=0,
        cache_read_input_tokens=20, cache_creation_input_tokens=30))),
        dict(type='content_block_start', index=0, content_block=dict(type='text', text='')),
        dict(type='content_block_delta', index=0, delta=dict(type='text_delta', text='查詢')),
        dict(type='content_block_stop', index=0)]
    iterations = None
    if fallback:
        result.extend([dict(type='content_block_start', index=1, content_block={'type': 'fallback',
            'from': {'model': model}, 'to': {'model': 'claude-opus-4-8'}}),
            dict(type='content_block_stop', index=1),
            dict(type='content_block_start', index=2, content_block=dict(type='text', text='')),
            dict(type='content_block_delta', index=2, delta=dict(type='text_delta', text='完成')),
            dict(type='content_block_stop', index=2)])
        iterations = [dict(type='message', model=model, input_tokens=10, output_tokens=5,
                          cache_read_input_tokens=20, cache_creation_input_tokens=30),
                      dict(type='fallback_message', model='claude-opus-4-8', input_tokens=100, output_tokens=40,
                           cache_read_input_tokens=0, cache_creation_input_tokens=0)]
    usage = dict(input_tokens=100 if fallback else 10, output_tokens=40,
                 cache_read_input_tokens=0 if fallback else 20, cache_creation_input_tokens=0 if fallback else 30)
    if iterations:
        usage['iterations'] = iterations
    result += [dict(type='message_delta', delta=dict(stop_reason=reason, stop_sequence=None), usage=usage),
               dict(type='message_stop')]
    return result


@pytest.mark.parametrize('reason', ['end_turn', 'max_tokens'])
@pytest.mark.parametrize('fallback', [False, True])
def test_claude_request_usage_fallback_and_stream(monkeypatch, fallback, reason):
    requests = []
    def handler(request):
        requests.append((json.loads(request.content), request.headers))
        return httpx2.Response(200, headers={'content-type': 'text/event-stream'}, content=wire(anthropic_events(reason=reason, fallback=fallback)))
    monkeypatch.setattr(providers, 'AsyncAnthropic', lambda **kwargs: AsyncAnthropic(**kwargs,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))))
    async def run():
        return [e async for e in providers.Claude('fictional').stream(MODELS['claude'], 'system',
            [{'role': 'user', 'content': 'question'}], TOOLS)]
    events = asyncio.run(run())
    request, headers = requests[0]
    assert request['max_tokens'] == 16000
    for tool in request['tools']:
        assert_strict_schema(tool['input_schema'])
    assert request['model'] == 'claude-sonnet-5-5'
    assert request['output_config'] == {'effort': 'medium'}
    assert not {'thinking', 'temperature', 'top_p', 'tool_choice'} & request.keys()
    assert request['fallbacks'] == 'default'
    assert 'server-side-fallback-2026-07-01' in headers['anthropic-beta']
    assert request['system'][0]['cache_control'] == {'type': 'ephemeral'}
    assert request['tools'][-1]['cache_control'] == {'type': 'ephemeral'}
    assert all(t['strict'] and t['input_schema']['additionalProperties'] is False for t in request['tools'])
    assert events[0].kind == 'usage' and events[0].value == Usage(10, 20, 30, 0)
    assert [e.value for e in events if e.kind == 'text'] == (['查詢', '完成'] if fallback else ['查詢']) + (['（回答太長，已截斷）'] if reason == 'max_tokens' else [])
    if fallback:
        switched = next(e for e in events if e.kind == 'usage' and e.unpriced)
        assert switched.model == 'claude-opus-4-8'
        assert switched.value == Usage(10, 20, 30, 0)
    usage = [e for e in events if e.kind == 'usage'][-1]
    assert usage.value == (Usage(110, 20, 30, 45) if fallback else Usage(10, 20, 30, 40))
    assert usage.unpriced is fallback
    assert usage.model == ('claude-opus-4-8' if fallback else 'claude-sonnet-5-5')
    assert events[-1].kind == 'stop'


def test_claude_refusal_becomes_ai_refused(monkeypatch):
    def handler(request):
        return httpx2.Response(200, headers={'content-type': 'text/event-stream'}, content=wire(anthropic_events('refusal')))
    monkeypatch.setattr(providers, 'AsyncAnthropic', lambda **kwargs: AsyncAnthropic(**kwargs,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))))
    async def run():
        return [e async for e in providers.Claude('fictional').stream(MODELS['claude'], 'system', [], TOOLS)]
    with pytest.raises(providers.ProviderError) as failure:
        asyncio.run(run())
    assert failure.value.code == 'ai_refused'


@pytest.mark.parametrize('length', [False, True])
def test_gpt_responses_request_events_usage_and_tool_call(monkeypatch, length):
    requests = []
    call = dict(type='function_call', id='fc_1', call_id='call_1', name='attendance_today', arguments='{}', status='completed')
    response = dict(id='resp_1', object='response', model='gpt-6.1-terra', status='completed', output=[call],
                    usage=dict(input_tokens=150, input_tokens_details=dict(cached_tokens=100),
                               output_tokens=70, output_tokens_details=dict(reasoning_tokens=50), total_tokens=220))
    values = [dict(type='response.output_text.delta', delta='查詢', item_id='item', output_index=0, content_index=0, sequence_number=1),
              dict(type='response.output_item.done', item=call, output_index=0, sequence_number=2),
              dict(type='response.completed', response=response, sequence_number=3)]
    if length:
        values[-1]['type'] = 'response.incomplete'
        response.update(status='incomplete', incomplete_details={'reason': 'max_output_tokens'})
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx2.Response(200, headers={'content-type': 'text/event-stream'}, content=wire(values))
    monkeypatch.setattr(providers, 'AsyncOpenAI', lambda **kwargs: AsyncOpenAI(**kwargs,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))))
    async def run():
        return [e async for e in providers.GPT('fictional').stream(MODELS['gpt'], 'system',
            [{'role': 'user', 'content': 'question'}], TOOLS)]
    events = asyncio.run(run())
    request = requests[0]
    assert request['max_output_tokens'] == 16000
    for tool in request['tools']:
        assert_strict_schema(tool['parameters'])
    if length:
        assert events[-2].value == '（回答太長，已截斷）'
    assert request['model'] == 'gpt-6.1-terra'
    assert request['reasoning'] == {'effort': 'medium'}
    assert request['store'] is False and request['stream'] is True
    assert request['tools'][0]['type'] == 'function'
    assert events[0].kind == 'text' and events[0].value == '查詢'
    assert events[1].value == providers.ToolCall('call_1', 'attendance_today', {})
    assert events[2].value == Usage(50, 100, 0, 70)
    assert events[-1].kind == 'stop'
    messages = []
    providers.GPT('').continue_with(messages, events[-1].value, [events[1].value], ['result'])
    assert messages[-1] == {'type': 'function_call_output', 'call_id': 'call_1', 'output': 'result'}
