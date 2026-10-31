"""SDK streams normalized to cumulative usage snapshots and complete tool calls."""
from dataclasses import dataclass
import json
from typing import Any, Literal

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from .catalog import Usage


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass(frozen=True)
class Event:
    kind: Literal['text', 'tool', 'usage', 'stop']
    value: Any = None
    model: str | None = None
    unpriced: bool = False
    final_usage: bool = True
    truncated: bool = False


class ProviderError(Exception):
    def __init__(self, code='ai_upstream'):
        self.code = code
        super().__init__(code)


def claude_usage(value):
    return Usage(value.input_tokens, value.cache_read_input_tokens or 0,
                 value.cache_creation_input_tokens or 0, value.output_tokens)


def claude_usage_event(value, model, requested, *, final_usage=True):
    iterations = getattr(value, 'iterations', None)
    if iterations:
        total = Usage()
        for entry in iterations:
            total += claude_usage(entry)
        return Event('usage', total, model, any((getattr(e, 'model', None) or model) != requested for e in iterations), final_usage)
    return Event('usage', claude_usage(value), model, model != requested, final_usage)


class Claude:
    def __init__(self, key):
        self.key = key

    async def stream(self, spec, system, messages, tools):
        definitions = [dict(name=name, description=t.label, input_schema=t.schema, strict=True)
                       for name, t in tools.items()]
        definitions[-1]['cache_control'] = {'type': 'ephemeral'}
        async with AsyncAnthropic(api_key=self.key, max_retries=0, timeout=60) as client:
            async with client.beta.messages.stream(
                model=spec.model, max_tokens=16000, output_config={'effort': spec.effort},
                system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
                tools=definitions, messages=messages,
                betas=['server-side-fallback-2026-07-01'], fallbacks='default',
            ) as stream:
                async for event in stream:
                    if event.type == 'message_start':
                        yield claude_usage_event(event.message.usage, event.message.model, spec.model, final_usage=False)
                    elif event.type == 'content_block_start' and event.content_block.type == 'fallback':
                        snapshot = stream.current_message_snapshot
                        yield claude_usage_event(snapshot.usage, snapshot.model, spec.model, final_usage=False)
                    elif event.type == 'message_delta':
                        snapshot = stream.current_message_snapshot
                        yield claude_usage_event(snapshot.usage, snapshot.model, spec.model)
                    elif event.type == 'content_block_delta' and event.delta.type == 'text_delta':
                        yield Event('text', event.delta.text)
                message = await stream.get_final_message()
                yield claude_usage_event(message.usage, message.model, spec.model)
                if message.stop_reason == 'refusal':
                    raise ProviderError('ai_refused')
                content = [b.model_dump(exclude_none=True) for b in message.content]
                boundary = max((i for i, b in enumerate(content) if b['type'] == 'fallback'), default=-1)
                if boundary >= 0:
                    content = [b for i, b in enumerate(content)
                               if i > boundary or b['type'] == 'text']
                for block in content:
                    if block['type'] == 'tool_use':
                        yield Event('tool', ToolCall(block['id'], block['name'], block['input']))
                if message.stop_reason == 'max_tokens':
                    yield Event('text', '（回答太長，已截斷）')
                    yield Event('stop', content, truncated=True)
                    return
                if message.stop_reason not in ('end_turn', 'tool_use'):
                    raise ProviderError()
                yield Event('stop', content)

    def continue_with(self, messages, content, calls, results):
        messages.append({'role': 'assistant', 'content': content})
        messages.append({'role': 'user', 'content': [
            {'type': 'tool_result', 'tool_use_id': call.id, 'content': result}
            for call, result in zip(calls, results)]})


def openai_usage(value):
    cached = value.input_tokens_details.cached_tokens or 0
    return Usage(value.input_tokens - cached, cached, 0, value.output_tokens)


class GPT:
    def __init__(self, key):
        self.key = key

    async def stream(self, spec, system, messages, tools):
        definitions = [dict(type='function', name=name, description=t.label, parameters=t.schema, strict=True)
                       for name, t in tools.items()]
        async with AsyncOpenAI(api_key=self.key, max_retries=0, timeout=60) as client:
            stream = await client.responses.create(
                model=spec.model, reasoning={'effort': spec.effort}, instructions=system,
                input=messages, tools=definitions, stream=True, store=False,
                include=['reasoning.encrypted_content'], max_output_tokens=16000,
            )
            dropped_call = False
            async with stream:
                async for event in stream:
                    if event.type == 'response.output_text.delta':
                        yield Event('text', event.delta)
                    elif event.type == 'response.output_item.done' and event.item.type == 'function_call':
                        call = event.item
                        if call.status != 'completed':
                            dropped_call = True
                            continue
                        try:
                            arguments = json.loads(call.arguments)
                        except (ValueError, TypeError):
                            dropped_call = True
                            continue
                        yield Event('tool', ToolCall(call.call_id, call.name, arguments))
                    elif event.type in ('response.completed', 'response.incomplete', 'response.failed'):
                        response = event.response
                        if response.usage is not None:
                            yield Event('usage', openai_usage(response.usage), response.model)
                        truncated = event.type == 'response.incomplete' and getattr(response.incomplete_details, 'reason', None) == 'max_output_tokens'
                        if event.type != 'response.completed' and not truncated:
                            raise ProviderError()
                        if truncated or dropped_call:
                            yield Event('text', '（回答太長，已截斷）')
                        yield Event('stop', [item.model_dump(exclude_none=True) for item in response.output],
                                    truncated=truncated or dropped_call)
                    elif event.type == 'error':
                        raise ProviderError()

    def continue_with(self, messages, content, calls, results):
        messages.extend(content)
        messages.extend({'type': 'function_call_output', 'call_id': call.id, 'output': result}
                        for call, result in zip(calls, results))


ADAPTERS = {'anthropic': Claude, 'openai': GPT}
