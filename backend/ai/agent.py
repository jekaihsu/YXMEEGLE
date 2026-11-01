"""Bounded tool loop and cancellation-safe question accounting."""
import asyncio
import json
import logging
import math
from uuid import uuid4

import anyio
from starlette.concurrency import run_in_threadpool
from time import perf_counter

from . import ledger
from .catalog import Usage, cost_micro_usd
from .prompts import system_prompt
from .providers import ProviderError, failure_diagnostics
from .tools import TOOLS, execute, displays


QUESTION_TIMEOUT_SECONDS = 120
logger = logging.getLogger(__name__)


def log_failure(provider, step, exc, *, model=None, elapsed_ms=None):
    detail = failure_diagnostics(exc)
    logger.warning('ai_upstream provider=%s model=%s step=%s elapsed_ms=%s exception=%s status_code=%s request_id=%s upstream_code=%s upstream_type=%s upstream_param=%s last_event_type=%s message=%s',
                   provider, model, step, elapsed_ms, getattr(exc, 'exception_class', type(exc).__name__),
                   detail['status_code'], detail['request_id'], detail['upstream_code'],
                   detail['upstream_type'], detail['upstream_param'], detail['last_event_type'], detail['message'])


def sse(value):
    return 'data: ' + json.dumps(value, ensure_ascii=False) + '\n\n'


class ChatRun:
    def __init__(self, app, body, data, user, spec, adapter, release):
        self.app, self.body, self.data, self.user = app, body, data, user
        self.spec, self.adapter, self.release = spec, adapter, release
        self.usage_id = str(uuid4())
        self.started = perf_counter()
        self.usage = Usage()
        self.step_usage = Usage()
        self.steps = self.tool_calls = 0
        self.first_token_ms = None
        self.status, self.error_code = 'aborted', None
        self.model = spec.model
        self.unpriced = False
        self.finished = False
        self.cookie = ''
        self.recorded = lambda: None
        self.step_final_usage = False
        self.streamed_chars = self.input_floor = 0

    def elapsed(self):
        return int((perf_counter() - self.started) * 1000)

    def cost(self):
        return None if self.unpriced else cost_micro_usd(self.spec, self.usage + self.step_usage)

    async def finish(self):
        if self.finished:
            return
        self.finished = True
        if self.status != 'ok' and self.steps and not self.step_final_usage:
            self.step_usage = Usage(
                self.step_usage.uncached_input + max(0, self.input_floor - self.step_usage.input_tokens),
                self.step_usage.cache_read, self.step_usage.cache_write,
                max(self.streamed_chars, self.step_usage.output))
            if self.status == 'aborted' or not self.error_code:
                self.error_code = 'usage_estimated'
        usage = self.usage + self.step_usage
        self.release()
        try:
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(ledger.record, self.app.state.sessions, id=self.usage_id, workspace_id=self.data['wid'], actor_id=self.user['id'],
                      actor_name=self.user.get('name') or '', conversation_id=self.body.conversation_id,
                      provider=self.spec.id, model=self.model, effort=self.spec.effort,
                      input_tokens=usage.input_tokens, cache_read_tokens=usage.cache_read,
                      cache_write_tokens=usage.cache_write, output_tokens=usage.output,
                      cost_micro_usd=self.cost(), price_version=self.spec.price_version,
                      steps=self.steps, tool_calls=self.tool_calls, latency_ms=self.elapsed(),
                      first_token_ms=self.first_token_ms, status=self.status, error_code=self.error_code)
                self.recorded()
        finally:
            self.release()

    async def stream(self):
        try:
            async with asyncio.timeout(float(self.app.state.cfg.get('AI_QUESTION_TIMEOUT_SECONDS', QUESTION_TIMEOUT_SECONDS))):
                async for event in self._stream():
                    yield event
        except TimeoutError as exc:
            self.status, self.error_code = 'error', 'ai_upstream'
            log_failure(self.spec.provider, self.steps, exc, model=self.model, elapsed_ms=self.elapsed())
            yield sse(dict(type='error', code='ai_upstream', message='助理回答逾時，請稍後重試'))
        finally:
            await self.finish()

    async def _stream(self):
        messages = [m.model_dump() for m in self.body.messages]
        cache = {}
        try:
            yield sse(dict(type='start', usage_id=self.usage_id, conversation_id=self.body.conversation_id, provider=self.spec.id))
            system = system_prompt()
            for _ in range(5):
                self.steps += 1
                self.step_usage = Usage()
                self.step_final_usage = False
                self.streamed_chars = 0
                self.input_floor = math.ceil(len(json.dumps(dict(system=system,
                    tools={k: dict(description=t.label, schema=t.schema) for k, t in TOOLS.items()},
                    messages=messages), ensure_ascii=False)) / 2)
                calls, content = [], None
                async for event in self.adapter.stream(self.spec, system, messages, TOOLS):
                    if event.kind == 'text':
                        self.streamed_chars += len(event.value)
                        if self.first_token_ms is None:
                            self.first_token_ms = self.elapsed()
                        yield sse(dict(type='text', delta=event.value))
                    elif event.kind == 'usage':
                        self.step_usage = event.value
                        self.step_final_usage = event.final_usage
                        self.model = event.model or self.model
                        self.unpriced |= event.unpriced or self.model != self.spec.model
                    elif event.kind == 'tool':
                        calls.append(event.value)
                    elif event.kind == 'stop':
                        content = event.value
                        if event.truncated:
                            calls.clear()
                self.usage += self.step_usage
                self.step_usage = Usage()
                if content is None:
                    raise ProviderError()
                if not calls:
                    self.status = 'ok'
                    done = dict(type='done', usage=dict(input_tokens=self.usage.input_tokens, output_tokens=self.usage.output))
                    if self.user['role'] == 'manager':
                        cost = self.cost()
                        done['cost_usd'] = None if cost is None else cost / 1_000_000
                    yield sse(done)
                    return
                if self.steps == 5:
                    raise ProviderError()
                keys = [(c.name, json.dumps(c.args, sort_keys=True, ensure_ascii=False)) for c in calls]
                pending = {}
                for call, key in zip(calls, keys):
                    label = TOOLS[call.name].label if call.name in TOOLS else '查詢資料'
                    yield sse(dict(type='tool', id=call.id, name=call.name, label=label, status='running'))
                    if key not in cache:
                        pending[key] = call

                async def run_tool(call):
                    try:
                        return await asyncio.wait_for(execute(self.app, self.cookie, call.name, call.args), timeout=15)
                    except TimeoutError:
                        return json.dumps({'error': '查詢逾時，請稍後重試'}, ensure_ascii=False), True

                self.tool_calls += len(pending)
                results = await asyncio.gather(*(run_tool(c) for c in pending.values()))
                cache.update(zip(pending, results))
                outputs = []
                for call, key in zip(calls, keys):
                    result, error = cache[key]
                    outputs.append(result)
                    label = TOOLS[call.name].label if call.name in TOOLS else '查詢資料'
                    event = dict(type='tool', id=call.id, name=call.name, label=label, status='error' if error else 'done')
                    display_failed = False
                    if not error:
                        try:
                            event['displays'] = displays(call.name, result)
                        except Exception as exc:
                            display_failed = True
                            logger.warning('ai_display tool=%s exception=%s', call.name, type(exc).__name__)
                    yield sse(event)
                    if display_failed:
                        yield sse(dict(type='text', delta='（此結果無法以表格或圖表顯示，以下以文字說明。）\n\n'))
                self.adapter.continue_with(messages, content, calls, outputs)
            raise ProviderError()
        except (asyncio.CancelledError, GeneratorExit):
            self.status = 'aborted'
            raise
        except Exception as exc:
            log_failure(self.spec.provider, self.steps, exc, model=self.model, elapsed_ms=self.elapsed())
            self.status = 'error'
            self.error_code = exc.code if isinstance(exc, ProviderError) else 'ai_upstream'
            error = dict(type='error', code=self.error_code, message='助理暫時無法回答，請稍後重試')
            if self.user['role'] == 'manager':
                diagnostic = failure_diagnostics(exc)
                parts = [diagnostic['status_code'], diagnostic['upstream_code'] or diagnostic['upstream_type']]
                if any(parts):
                    name = 'OpenAI' if self.spec.provider == 'openai' else 'Anthropic'
                    error['detail'] = ' '.join([name, *(str(p) for p in parts if p)])[:200]
            yield sse(error)
