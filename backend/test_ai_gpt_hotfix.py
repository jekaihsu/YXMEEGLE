"""Offline regressions using the SDK audit wire fixtures."""
import asyncio
import copy
import json
from dataclasses import replace

import httpx2
import pytest
from openai import AsyncOpenAI
from pydantic import TypeAdapter
from openai.types.responses.response_create_params import ResponseCreateParamsStreaming

from .ai import providers
from .ai.catalog import MODELS, Usage, prices, cost_micro_usd
from .ai.tools import TOOLS
from .test_ai_providers import wire
from .test_ai_database import app, client, ai_database_url

FIXTURES = {'tool-async-field': [{'type': 'response.created',
                       'response': {'id': 'resp_1',
                                    'object': 'response',
                                    'created_at': 1793404800,
                                    'model': 'gpt-6.1-terra',
                                    'status': 'in_progress',
                                    'output': [],
                                    'parallel_tool_calls': True,
                                    'tool_choice': 'auto',
                                    'tools': [],
                                    'usage': None,
                                    'error': None,
                                    'incomplete_details': None},
                       'sequence_number': 0},
                      {'type': 'response.output_item.added',
                       'output_index': 0,
                       'item': {'id': 'rs_1',
                                'type': 'reasoning',
                                'summary': [],
                                'encrypted_content': 'offline-placeholder',
                                'status': 'completed'},
                       'sequence_number': 1},
                      {'type': 'response.output_item.done',
                       'output_index': 0,
                       'item': {'id': 'rs_1',
                                'type': 'reasoning',
                                'summary': [],
                                'encrypted_content': 'offline-placeholder',
                                'status': 'completed'},
                       'sequence_number': 2},
                      {'type': 'response.output_item.added',
                       'output_index': 1,
                       'item': {'id': 'fc_1',
                                'type': 'function_call',
                                'call_id': 'call_1',
                                'name': 'search_cases',
                                'arguments': '{"query":"demo"}',
                                'status': 'completed',
                                'async': False},
                       'sequence_number': 3},
                      {'type': 'response.function_call_arguments.delta',
                       'item_id': 'fc_1',
                       'output_index': 1,
                       'delta': '{"query":"demo"}',
                       'sequence_number': 4},
                      {'type': 'response.function_call_arguments.done',
                       'item_id': 'fc_1',
                       'output_index': 1,
                       'arguments': '{"query":"demo"}',
                       'name': 'search_cases',
                       'sequence_number': 5},
                      {'type': 'response.output_item.done',
                       'output_index': 1,
                       'item': {'id': 'fc_1',
                                'type': 'function_call',
                                'call_id': 'call_1',
                                'name': 'search_cases',
                                'arguments': '{"query":"demo"}',
                                'status': 'completed',
                                'async': False},
                       'sequence_number': 6},
                      {'type': 'response.completed',
                       'response': {'id': 'resp_1',
                                    'object': 'response',
                                    'created_at': 1793404800,
                                    'model': 'gpt-6.1-terra',
                                    'status': 'completed',
                                    'output': [{'id': 'rs_1',
                                                'type': 'reasoning',
                                                'summary': [],
                                                'encrypted_content': 'offline-placeholder',
                                                'status': 'completed'},
                                               {'id': 'fc_1',
                                                'type': 'function_call',
                                                'call_id': 'call_1',
                                                'name': 'search_cases',
                                                'arguments': '{"query":"demo"}',
                                                'status': 'completed',
                                                'async': False}],
                                    'parallel_tool_calls': True,
                                    'tool_choice': 'auto',
                                    'tools': [],
                                    'usage': {'input_tokens': 100,
                                              'input_tokens_details': {'cached_tokens': 20,
                                                                       'cache_write_tokens': 30},
                                              'output_tokens': 12,
                                              'output_tokens_details': {'reasoning_tokens': 8},
                                              'total_tokens': 112},
                                    'error': None,
                                    'incomplete_details': None},
                       'sequence_number': 7}],
 'text': [{'type': 'response.created',
           'response': {'id': 'resp_1',
                        'object': 'response',
                        'created_at': 1793404800,
                        'model': 'gpt-6.1-terra',
                        'status': 'in_progress',
                        'output': [],
                        'parallel_tool_calls': True,
                        'tool_choice': 'auto',
                        'tools': [],
                        'usage': None,
                        'error': None,
                        'incomplete_details': None},
           'sequence_number': 0},
          {'type': 'response.output_item.added',
           'output_index': 0,
           'item': {'id': 'msg_1',
                    'type': 'message',
                    'role': 'assistant',
                    'status': 'completed',
                    'content': [{'type': 'output_text', 'text': 'Hello', 'annotations': [], 'logprobs': []}]},
           'sequence_number': 1},
          {'type': 'response.output_text.delta',
           'item_id': 'msg_1',
           'output_index': 0,
           'content_index': 0,
           'delta': 'Hello',
           'logprobs': [],
           'sequence_number': 2},
          {'type': 'response.output_item.done',
           'output_index': 0,
           'item': {'id': 'msg_1',
                    'type': 'message',
                    'role': 'assistant',
                    'status': 'completed',
                    'content': [{'type': 'output_text', 'text': 'Hello', 'annotations': [], 'logprobs': []}]},
           'sequence_number': 3},
          {'type': 'response.completed',
           'response': {'id': 'resp_1',
                        'object': 'response',
                        'created_at': 1793404800,
                        'model': 'gpt-6.1-terra',
                        'status': 'completed',
                        'output': [{'id': 'msg_1',
                                    'type': 'message',
                                    'role': 'assistant',
                                    'status': 'completed',
                                    'content': [{'type': 'output_text',
                                                 'text': 'Hello',
                                                 'annotations': [],
                                                 'logprobs': []}]}],
                        'parallel_tool_calls': True,
                        'tool_choice': 'auto',
                        'tools': [],
                        'usage': {'input_tokens': 100,
                                  'input_tokens_details': {'cached_tokens': 20, 'cache_write_tokens': 30},
                                  'output_tokens': 12,
                                  'output_tokens_details': {'reasoning_tokens': 8},
                                  'total_tokens': 112},
                        'error': None,
                        'incomplete_details': None},
           'sequence_number': 4}],
 'failed': [{'type': 'response.created',
             'response': {'id': 'resp_1',
                          'object': 'response',
                          'created_at': 1793404800,
                          'model': 'gpt-6.1-terra',
                          'status': 'in_progress',
                          'output': [],
                          'parallel_tool_calls': True,
                          'tool_choice': 'auto',
                          'tools': [],
                          'usage': None,
                          'error': {'code': 'server_error',
                                    'message': 'Synthetic backend error',
                                    'type': 'server_error',
                                    'param': None},
                          'incomplete_details': None},
             'sequence_number': 0},
            {'type': 'response.failed',
             'response': {'id': 'resp_1',
                          'object': 'response',
                          'created_at': 1793404800,
                          'model': 'gpt-6.1-terra',
                          'status': 'failed',
                          'output': [],
                          'parallel_tool_calls': True,
                          'tool_choice': 'auto',
                          'tools': [],
                          'usage': {'input_tokens': 100,
                                    'input_tokens_details': {'cached_tokens': 20, 'cache_write_tokens': 30},
                                    'output_tokens': 12,
                                    'output_tokens_details': {'reasoning_tokens': 8},
                                    'total_tokens': 112},
                          'error': {'code': 'server_error',
                                    'message': 'Synthetic backend error',
                                    'type': 'server_error',
                                    'param': None},
                          'incomplete_details': None},
             'sequence_number': 1}],
 'error-flat': [{'type': 'error',
                 'code': 'server_error',
                 'message': 'Synthetic stream error',
                 'param': None,
                 'sequence_number': 0}],
 'error-nested': [{'type': 'error',
                   'error': {'code': 'server_error',
                             'message': 'Synthetic stream error',
                             'type': 'server_error'}}],
 'incomplete-filter': [{'type': 'response.created',
                        'response': {'id': 'resp_1',
                                     'object': 'response',
                                     'created_at': 1793404800,
                                     'model': 'gpt-6.1-terra',
                                     'status': 'in_progress',
                                     'output': [],
                                     'parallel_tool_calls': True,
                                     'tool_choice': 'auto',
                                     'tools': [],
                                     'usage': None,
                                     'error': None,
                                     'incomplete_details': {'reason': 'content_filter'}},
                        'sequence_number': 0},
                       {'type': 'response.incomplete',
                        'response': {'id': 'resp_1',
                                     'object': 'response',
                                     'created_at': 1793404800,
                                     'model': 'gpt-6.1-terra',
                                     'status': 'incomplete',
                                     'output': [],
                                     'parallel_tool_calls': True,
                                     'tool_choice': 'auto',
                                     'tools': [],
                                     'usage': {'input_tokens': 100,
                                               'input_tokens_details': {'cached_tokens': 20,
                                                                        'cache_write_tokens': 30},
                                               'output_tokens': 12,
                                               'output_tokens_details': {'reasoning_tokens': 8},
                                               'total_tokens': 112},
                                     'error': None,
                                     'incomplete_details': {'reason': 'content_filter'}},
                        'sequence_number': 1}],
 'refusal': [{'type': 'response.created',
              'response': {'id': 'resp_1',
                           'object': 'response',
                           'created_at': 1793404800,
                           'model': 'gpt-6.1-terra',
                           'status': 'in_progress',
                           'output': [],
                           'parallel_tool_calls': True,
                           'tool_choice': 'auto',
                           'tools': [],
                           'usage': None,
                           'error': None,
                           'incomplete_details': None},
              'sequence_number': 0},
             {'type': 'response.output_item.added',
              'output_index': 0,
              'item': {'id': 'msg_1',
                       'type': 'message',
                       'role': 'assistant',
                       'status': 'completed',
                       'content': [{'type': 'refusal', 'refusal': 'I cannot comply.'}]},
              'sequence_number': 1},
             {'type': 'response.output_item.done',
              'output_index': 0,
              'item': {'id': 'msg_1',
                       'type': 'message',
                       'role': 'assistant',
                       'status': 'completed',
                       'content': [{'type': 'refusal', 'refusal': 'I cannot comply.'}]},
              'sequence_number': 2},
             {'type': 'response.refusal.done',
              'item_id': 'msg_1',
              'output_index': 0,
              'content_index': 0,
              'refusal': 'I cannot comply.',
              'sequence_number': 4},
             {'type': 'response.completed',
              'response': {'id': 'resp_1',
                           'object': 'response',
                           'created_at': 1793404800,
                           'model': 'gpt-6.1-terra',
                           'status': 'completed',
                           'output': [{'id': 'msg_1',
                                       'type': 'message',
                                       'role': 'assistant',
                                       'status': 'completed',
                                       'content': [{'type': 'refusal', 'refusal': 'I cannot comply.'}]}],
                           'parallel_tool_calls': True,
                           'tool_choice': 'auto',
                           'tools': [],
                           'usage': {'input_tokens': 100,
                                     'input_tokens_details': {'cached_tokens': 20, 'cache_write_tokens': 30},
                                     'output_tokens': 12,
                                     'output_tokens_details': {'reasoning_tokens': 8},
                                     'total_tokens': 112},
                           'error': None,
                           'incomplete_details': None},
              'sequence_number': 3}],
 'tool-no-status': [{'type': 'response.created',
                     'response': {'id': 'resp_1',
                                  'object': 'response',
                                  'created_at': 1793404800,
                                  'model': 'gpt-6.1-terra',
                                  'status': 'in_progress',
                                  'output': [],
                                  'parallel_tool_calls': True,
                                  'tool_choice': 'auto',
                                  'tools': [],
                                  'usage': None,
                                  'error': None,
                                  'incomplete_details': None},
                     'sequence_number': 0},
                    {'type': 'response.output_item.added',
                     'output_index': 0,
                     'item': {'id': 'rs_1',
                              'type': 'reasoning',
                              'summary': [],
                              'encrypted_content': 'offline-placeholder',
                              'status': 'completed'},
                     'sequence_number': 1},
                    {'type': 'response.output_item.done',
                     'output_index': 0,
                     'item': {'id': 'rs_1',
                              'type': 'reasoning',
                              'summary': [],
                              'encrypted_content': 'offline-placeholder',
                              'status': 'completed'},
                     'sequence_number': 2},
                    {'type': 'response.output_item.added',
                     'output_index': 1,
                     'item': {'id': 'fc_1',
                              'type': 'function_call',
                              'call_id': 'call_1',
                              'name': 'search_cases',
                              'arguments': '{"query":"demo"}'},
                     'sequence_number': 3},
                    {'type': 'response.function_call_arguments.delta',
                     'item_id': 'fc_1',
                     'output_index': 1,
                     'delta': '{"query":"demo"}',
                     'sequence_number': 4},
                    {'type': 'response.function_call_arguments.done',
                     'item_id': 'fc_1',
                     'output_index': 1,
                     'arguments': '{"query":"demo"}',
                     'name': 'search_cases',
                     'sequence_number': 5},
                    {'type': 'response.output_item.done',
                     'output_index': 1,
                     'item': {'id': 'fc_1',
                              'type': 'function_call',
                              'call_id': 'call_1',
                              'name': 'search_cases',
                              'arguments': '{"query":"demo"}'},
                     'sequence_number': 6},
                    {'type': 'response.completed',
                     'response': {'id': 'resp_1',
                                  'object': 'response',
                                  'created_at': 1793404800,
                                  'model': 'gpt-6.1-terra',
                                  'status': 'completed',
                                  'output': [{'id': 'rs_1',
                                              'type': 'reasoning',
                                              'summary': [],
                                              'encrypted_content': 'offline-placeholder',
                                              'status': 'completed'},
                                             {'id': 'fc_1',
                                              'type': 'function_call',
                                              'call_id': 'call_1',
                                              'name': 'search_cases',
                                              'arguments': '{"query":"demo"}'}],
                                  'parallel_tool_calls': True,
                                  'tool_choice': 'auto',
                                  'tools': [],
                                  'usage': {'input_tokens': 100,
                                            'input_tokens_details': {'cached_tokens': 20,
                                                                     'cache_write_tokens': 30},
                                            'output_tokens': 12,
                                            'output_tokens_details': {'reasoning_tokens': 8},
                                            'total_tokens': 112},
                                  'error': None,
                                  'incomplete_details': None},
                     'sequence_number': 7}]}


def install(monkeypatch, values, requests=None):
    def handler(request):
        if requests is not None:
            requests.append(json.loads(request.content))
        return httpx2.Response(200, headers={'content-type': 'text/event-stream'}, content=wire(values))
    monkeypatch.setattr(providers, 'AsyncOpenAI', lambda **kw: AsyncOpenAI(**kw,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))))


def collect(name='gpt', messages=None):
    async def run():
        return [e async for e in providers.GPT('fictional').stream(MODELS[name], 'SYSTEM_SENTINEL', messages or [], TOOLS)]
    return asyncio.run(run())


def test_replayed_items_preserve_wire_keys_and_validate_second_request(monkeypatch):
    requests = []
    values = copy.deepcopy(FIXTURES['tool-async-field'])
    message = FIXTURES['text'][-1]['response']['output'][0]
    values[-1]['response']['output'].append(message)
    install(monkeypatch, values, requests)
    first = collect()
    messages = [{'role': 'user', 'content': 'hello'}]
    providers.GPT('').continue_with(messages, first[-1].value,
        [e.value for e in first if e.kind == 'tool'], ['result'])
    collect(messages=messages)
    body = requests[-1]
    adapter = TypeAdapter(ResponseCreateParamsStreaming)
    validated = adapter.validate_python(body)
    def materialize(value):
        if isinstance(value, dict):
            return {k: materialize(v) for k, v in value.items()}
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        return [materialize(v) for v in value]
    assert body == materialize(validated)
    replay = body['input'][1:4]
    assert [v['type'] for v in replay] == ['reasoning', 'function_call', 'message']
    assert replay[0]['encrypted_content'] == 'offline-placeholder'
    assert replay[1]['async'] is False and 'async_' not in replay[1]


@pytest.mark.parametrize('source', ['refusal', 'delta', 'done', 'content'])
def test_gpt_refusal_ends_with_ai_refused(monkeypatch, source):
    values = copy.deepcopy(FIXTURES['refusal'])
    if source == 'content':
        values = [values[-1]]
    elif source in ('delta', 'done'):
        values = [dict(type='response.refusal.' + source, delta='no', refusal='no',
            item_id='msg_1', output_index=0, content_index=0, sequence_number=0)]
    install(monkeypatch, values)
    with pytest.raises(providers.ProviderError) as failure:
        collect()
    assert failure.value.code == 'ai_refused'


def test_gpt_function_call_without_status_is_complete(monkeypatch):
    values = copy.deepcopy(FIXTURES['tool-async-field'])
    for event in values:
        if event.get('item', {}).get('type') == 'function_call':
            event['item'].pop('status', None)
    values[-1]['response']['output'][1].pop('status', None)
    install(monkeypatch, values)
    result = collect()
    assert [e.value.id for e in result if e.kind == 'tool'] == ['call_1']
    assert not result[-1].truncated


@pytest.mark.parametrize('source,code,message', [
    ('failed', 'server_error', 'Synthetic backend error'),
    ('error-flat', 'server_error', 'Synthetic stream error'),
    ('error-nested', 'server_error', 'Synthetic stream error'),
    ('incomplete-filter', 'content_filter', None),
])
def test_stream_failure_diagnostics(monkeypatch, caplog, source, code, message):
    from .ai.agent import log_failure
    install(monkeypatch, FIXTURES[source])
    with pytest.raises(providers.ProviderError) as failure:
        collect()
    log_failure('openai', 2, failure.value, model=MODELS['gpt'].model, elapsed_ms=123)
    assert 'provider=openai model=gpt-6.1-terra step=2 elapsed_ms=123' in caplog.text
    assert 'upstream_code=' + code in caplog.text
    assert 'last_event_type=' + ('error' if source.startswith('error') else 'response.' + ('failed' if source == 'failed' else 'incomplete')) in caplog.text
    if message:
        assert message in caplog.text


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
def test_sdk_status_diagnostics_and_redaction(monkeypatch, caplog, provider):
    from anthropic import AsyncAnthropic
    from .ai.agent import log_failure
    message = 'Access denied SYSTEM_SENTINEL PROMPT_SENTINEL TOOL_SENTINEL sk-secret Bearer token-secret cookie: COOKIE_SENTINEL'
    def handler(request):
        return httpx2.Response(404, headers={'x-request-id': 'req_test', 'request-id': 'req_test'},
            json={'error': {'message': message, 'type': 'invalid_request_error', 'code': 'model_not_found', 'param': 'model'}})
    cls = AsyncOpenAI if provider == 'openai' else AsyncAnthropic
    monkeypatch.setattr(providers, 'AsyncOpenAI' if provider == 'openai' else 'AsyncAnthropic',
        lambda **kw: cls(**kw, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))))
    async def run():
        adapter = providers.GPT('fictional') if provider == 'openai' else providers.Claude('fictional')
        return [e async for e in adapter.stream(MODELS['gpt' if provider == 'openai' else 'claude'],
            'SYSTEM_SENTINEL', [{'role': 'user', 'content': 'PROMPT_SENTINEL'},
            {'type': 'function_call_output', 'call_id': 'x', 'output': 'TOOL_SENTINEL'}], TOOLS)]
    with pytest.raises(providers.ProviderError) as failure:
        asyncio.run(run())
    log_failure(provider, 1, failure.value, model='model', elapsed_ms=10)
    assert 'status_code=404' in caplog.text and 'request_id=req_test' in caplog.text
    assert 'upstream_type=invalid_request_error' in caplog.text
    assert 'upstream_param=model' in caplog.text
    assert 'upstream_code=model_not_found' in caplog.text
    assert len(caplog.records) == 1
    assert '\n' not in caplog.records[0].getMessage()
    for secret in ['SYSTEM_SENTINEL', 'PROMPT_SENTINEL', 'TOOL_SENTINEL', 'sk-secret', 'token-secret', 'COOKIE_SENTINEL']:
        assert secret not in caplog.text
    assert len(failure.value.diagnostics['message']) <= 200


@pytest.mark.parametrize('user,visible', [('u-manager', True), ('u-control', False)])
def test_upstream_detail_only_visible_to_manager(app, client, user, visible):
    from .test_backend import role
    from .test_ai_api import Fake, BODY, events
    class Failed(Fake):
        async def stream(self, *args):
            raise providers.ProviderError(source={'status_code': 404, 'code': 'model_not_found'})
            yield
    role(client, user)
    app.state.ai_providers = {'gpt': Failed()}
    result = events(client.post('/api/ai/chat', json=dict(BODY, model='gpt')))[-1]
    assert result['code'] == 'ai_upstream'
    if visible:
        assert result['detail'] == 'OpenAI 404 model_not_found'
    else:
        assert 'detail' not in result


@pytest.mark.parametrize('source', ['failed', 'error-flat', 'error-nested'])
def test_stream_diagnostics_redact_echoed_private_input_before_bounding(monkeypatch, caplog, source):
    from .ai.agent import log_failure
    values = copy.deepcopy(FIXTURES[source])
    secret = 'PROMPT_SENTINEL_' + 'x' * 250
    error = values[-1].get('response', values[-1])
    error = error.get('error', error)
    error['message'] = 'failure\n  SYSTEM_SENTINEL ' + secret + ' sk-secret Bearer token-secret'
    install(monkeypatch, values)
    with pytest.raises(providers.ProviderError) as failure:
        collect(messages=[{'role': 'user', 'content': secret}])
    log_failure('openai', 1, failure.value)
    assert 'failure' in caplog.text and 'PROMPT_SENTINEL' not in caplog.text
    assert 'SYSTEM_SENTINEL' not in caplog.text and 'sk-secret' not in caplog.text
    assert 'token-secret' not in caplog.text and len(caplog.records) == 1
    assert len(failure.value.diagnostics['message']) <= 200


@pytest.mark.parametrize('provider', ['openai', 'anthropic'])
def test_sdk_timeout_construction_fits_question_deadline(monkeypatch, provider):
    from anthropic import AsyncAnthropic
    from .test_ai_providers import anthropic_events
    observed = []
    cls = AsyncOpenAI if provider == 'openai' else AsyncAnthropic
    values = FIXTURES['text'] if provider == 'openai' else anthropic_events()
    def handler(request):
        return httpx2.Response(200, headers={'content-type': 'text/event-stream'}, content=wire(values))
    def client(**kwargs):
        observed.append(kwargs)
        return cls(**kwargs, http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)))
    monkeypatch.setattr(providers, 'AsyncOpenAI' if provider == 'openai' else 'AsyncAnthropic', client)
    async def run():
        adapter = providers.GPT('fictional') if provider == 'openai' else providers.Claude('fictional')
        return [e async for e in adapter.stream(MODELS['gpt' if provider == 'openai' else 'claude'], 'system', [], TOOLS)]
    asyncio.run(run())
    timeout = observed[0]['timeout']
    assert isinstance(timeout, httpx2.Timeout)
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (10, 60, 10, 10)
    assert observed[0]['max_retries'] == 0


@pytest.mark.parametrize('write_rate,expected,cost', [(0, Usage(80, 20, 0, 12), 141),
    (2, Usage(50, 20, 30, 12), 171), (None, Usage(80, 20, 0, 12), None)])
def test_cache_write_tokens_use_write_rate_or_count_as_uncached_input(monkeypatch, write_rate, expected, cost):
    install(monkeypatch, FIXTURES['tool-async-field'])
    monkeypatch.setitem(MODELS, 'gpt', replace(MODELS['gpt'], prices=None if write_rate is None else prices(1, .05, write_rate, 5)))
    result = collect()
    usage = next(e.value for e in result if e.kind == 'usage')
    assert usage == expected and usage.input_tokens == 100
    assert cost_micro_usd(MODELS['gpt'], usage) == cost


@pytest.mark.parametrize('source', ['failed', 'error-flat', 'error-nested'])
def test_diagnostics_redact_tool_json_values_and_encrypted_reasoning(monkeypatch, caplog, source):
    from .ai.agent import log_failure
    values = copy.deepcopy(FIXTURES[source])
    error = values[-1].get('response', values[-1])
    error = error.get('error', error)
    error['message'] = 'failure ARG_SENTINEL RESULT_SENTINEL ENCRYPTED_SENTINEL'
    install(monkeypatch, values)
    messages = [dict(type='function_call', call_id='c', name='search_cases', arguments='{"query":"ARG_SENTINEL"}'),
                dict(type='function_call_output', call_id='c', output='{"result":"RESULT_SENTINEL"}'),
                dict(type='reasoning', id='r', summary=[], encrypted_content='ENCRYPTED_SENTINEL')]
    with pytest.raises(providers.ProviderError) as failure:
        collect(messages=messages)
    log_failure('openai', 1, failure.value)
    for value in ['ARG_SENTINEL', 'RESULT_SENTINEL', 'ENCRYPTED_SENTINEL']:
        assert value not in caplog.text
