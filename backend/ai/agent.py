"""Bounded tool loop and cancellation-safe question accounting."""
import asyncio
import json
from time import perf_counter

from . import ledger
from .catalog import Usage, cost_micro_usd
from .prompts import system_prompt
from .providers import ProviderError
from .tools import TOOLS, execute


def sse(value):
    return 'data: ' + json.dumps(value, ensure_ascii=False) + '\n\n'


class ChatRun:
    def __init__(self, app, body, data, user, spec, adapter, release):
        self.app, self.body, self.data, self.user = app, body, data, user
        self.spec, self.adapter, self.release = spec, adapter, release
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

    def elapsed(self):
        return int((perf_counter() - self.started) * 1000)

    def cost(self):
        return None if self.unpriced else cost_micro_usd(self.spec, self.usage + self.step_usage)

    def finish(self):
        if self.finished:
            return
        self.finished = True
        usage = self.usage + self.step_usage
        ledger.record(self.app.state.sessions, workspace_id=self.data['wid'], actor_id=self.user['id'],
                      actor_name=self.user.get('name') or '', conversation_id=self.body.conversation_id,
                      provider=self.spec.id, model=self.model, effort=self.spec.effort,
                      input_tokens=usage.input_tokens, cache_read_tokens=usage.cache_read,
                      cache_write_tokens=usage.cache_write, output_tokens=usage.output,
                      cost_micro_usd=self.cost(), price_version=self.spec.price_version,
                      steps=self.steps, tool_calls=self.tool_calls, latency_ms=self.elapsed(),
                      first_token_ms=self.first_token_ms, status=self.status, error_code=self.error_code)
        self.release()

    async def stream(self):
        messages = [m.model_dump() for m in self.body.messages[-20:]]
        cache = {}
        try:
            yield sse(dict(type='start', conversation_id=self.body.conversation_id, provider=self.spec.id))
            system = system_prompt()
            for _ in range(5):
                self.steps += 1
                self.step_usage = Usage()
                calls, content = [], None
                async for event in self.adapter.stream(self.spec, system, messages, TOOLS):
                    if event.kind == 'text':
                        if self.first_token_ms is None:
                            self.first_token_ms = self.elapsed()
                        yield sse(dict(type='text', delta=event.value))
                    elif event.kind == 'usage':
                        self.step_usage = event.value
                        self.model = event.model or self.model
                        self.unpriced |= event.unpriced or self.model != self.spec.model
                    elif event.kind == 'tool':
                        calls.append(event.value)
                    elif event.kind == 'stop':
                        content = event.value
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
                    yield sse(dict(type='tool', id=call.id, name=call.name, label=label, status='error' if error else 'done'))
                self.adapter.continue_with(messages, content, calls, outputs)
            raise ProviderError()
        except (asyncio.CancelledError, GeneratorExit):
            self.status = 'aborted'
            raise
        except Exception as exc:
            self.status = 'error'
            self.error_code = exc.code if isinstance(exc, ProviderError) else 'ai_upstream'
            yield sse(dict(type='error', code=self.error_code, message='助理暫時無法回答，請稍後重試'))
        finally:
            self.finish()
