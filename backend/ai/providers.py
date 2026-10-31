"""SDK streams normalized to cumulative usage snapshots and complete tool calls."""
from dataclasses import dataclass
import json
import re
import httpx2 as httpx
from functools import wraps
from typing import Any, Literal

from anthropic import AsyncAnthropic, APIError as AnthropicAPIError
from openai import AsyncOpenAI, APIError as OpenAIAPIError
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


def private_strings(value):
    if isinstance(value, str):
        if value.lstrip().startswith(('{', '[')):
            try:
                return [value, *private_strings(json.loads(value))]
            except ValueError:
                pass
        return [value]
    if isinstance(value, dict):
        return [text for v in value.values() for text in private_strings(v)]
    if isinstance(value, (list, tuple)):
        return [text for v in value for text in private_strings(v)]
    return []


def sanitize(value, sensitive=()):
    if value is None:
        return None
    text = ' '.join(str(value).split())
    secrets = sorted({' '.join(v.split()) for v in sensitive if v.strip()}, key=len, reverse=True)
    patterns = [re.escape(v) if len(v) >= 4 else r'(?<!\w)' + re.escape(v) + r'(?!\w)' for v in secrets]
    if patterns:
        text = re.sub('|'.join(patterns), '[redacted]', text)
    text = re.sub(r'(?i)bearer\s+[^\s,;]+|sk-[\w-]+', '[redacted]', text)
    text = re.sub(r'(?i)(?:headers?|cookies?|authorization|encrypted_content)\s*[:=].*', '[redacted]', text)
    return text[:200]


def failure_diagnostics(source, *, last_event_type=None, sensitive=()):
    if isinstance(source, ProviderError):
        return {k: sanitize(v, sensitive) for k, v in source.diagnostics.items()}
    def field(value, key):
        return value.get(key) if isinstance(value, dict) else getattr(value, key, None)
    body = field(source, 'body')
    error = field(source, 'error') or field(body, 'error') or body or source
    reason = field(field(source, 'incomplete_details'), 'reason')
    return dict(status_code=field(source, 'status_code'),
                upstream_code=sanitize(field(error, 'code') or reason, sensitive),
                upstream_type=sanitize(field(error, 'type'), sensitive),
                upstream_param=sanitize(field(error, 'param'), sensitive),
                request_id=sanitize(field(source, 'request_id'), sensitive),
                last_event_type=last_event_type,
                message=sanitize(field(error, 'message') if error is not source or isinstance(error, dict) or isinstance(source, (OpenAIAPIError, AnthropicAPIError)) else None, sensitive))


class ProviderError(Exception):
    def __init__(self, code='ai_upstream', *, source=None, last_event_type=None, sensitive=()):
        self.code = code
        self.diagnostics = failure_diagnostics(source, last_event_type=last_event_type, sensitive=sensitive)
        self.exception_class = type(source).__name__ if isinstance(source, Exception) else type(self).__name__
        super().__init__(code)


def provider_failures(stream):
    @wraps(stream)
    async def wrapped(self, spec, system, messages, tools):
        sensitive = [self.key, system, *private_strings(messages)]
        try:
            async for event in stream(self, spec, system, messages, tools):
                if event.kind == 'stop':
                    sensitive.extend(private_strings(event.value))
                yield event
        except (ProviderError, OpenAIAPIError, AnthropicAPIError) as exc:
            failure = exc if isinstance(exc, ProviderError) else ProviderError(source=exc, sensitive=sensitive)
            failure.diagnostics = failure_diagnostics(failure, sensitive=sensitive)
            raise failure from None
    return wrapped


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

    @provider_failures
    async def stream(self, spec, system, messages, tools):
        definitions = [dict(name=name, description=t.label, input_schema=t.schema, strict=True)
                       for name, t in tools.items()]
        if definitions:
            definitions[-1]['cache_control'] = {'type': 'ephemeral'}
        async with AsyncAnthropic(api_key=self.key, max_retries=0, timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10)) as client:
            async with client.beta.messages.stream(
                model=spec.model, max_tokens=16000, output_config={'effort': spec.effort},
                system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
                messages=messages, **({'tools': definitions} if definitions else {}),
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


def openai_usage(value, spec=None):
    cached = value.input_tokens_details.cached_tokens or 0
    written = getattr(value.input_tokens_details, 'cache_write_tokens', 0) or 0
    if spec is None or spec.prices is None or not spec.prices[2]:
        written = 0
    return Usage(value.input_tokens - cached - written, cached, written, value.output_tokens)


class GPT:
    def __init__(self, key):
        self.key = key

    @provider_failures
    async def stream(self, spec, system, messages, tools):
        definitions = [dict(type='function', name=name, description=t.label, parameters=t.schema, strict=True)
                       for name, t in tools.items()]
        last_event_type = None
        sensitive = [self.key, system, *private_strings(messages)]
        try:
            async with AsyncOpenAI(api_key=self.key, max_retries=0, timeout=httpx.Timeout(connect=10, read=60, write=10, pool=10)) as client:
                stream = await client.responses.create(
                    model=spec.model, reasoning={'effort': spec.effort}, instructions=system,
                    input=messages, stream=True, store=False, **({'tools': definitions} if definitions else {}),
                    include=['reasoning.encrypted_content'], max_output_tokens=16000,
                )
                dropped_call = False
                async with stream:
                    async for event in stream:
                        last_event_type = event.type
                        if hasattr(event, 'item'):
                            sensitive.extend(private_strings(event.item.model_dump()))
                        if event.type == 'response.output_text.delta':
                            yield Event('text', event.delta)
                        elif event.type in ('response.refusal.delta', 'response.refusal.done'):
                            raise ProviderError('ai_refused')
                        elif event.type == 'response.output_item.done' and event.item.type == 'function_call':
                            call = event.item
                            if call.status == 'incomplete':
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
                                yield Event('usage', openai_usage(response.usage, spec), response.model)
                            if any(block.type == 'refusal' for item in response.output if item.type == 'message'
                                   for block in item.content):
                                raise ProviderError('ai_refused')
                            truncated = event.type == 'response.incomplete' and getattr(response.incomplete_details, 'reason', None) == 'max_output_tokens'
                            if event.type != 'response.completed' and not truncated:
                                raise ProviderError(source=response, last_event_type=event.type,
                                                    sensitive=[*sensitive, *private_strings(response.model_dump().get('output'))])
                            if truncated or dropped_call:
                                yield Event('text', '（回答太長，已截斷）')
                            yield Event('stop', [item.model_dump(exclude_none=True, by_alias=True) for item in response.output],
                                        truncated=truncated or dropped_call)
                        elif event.type == 'error':
                            raise ProviderError(source=event.model_dump(), last_event_type=event.type, sensitive=sensitive)
        except OpenAIAPIError as exc:
            if isinstance(exc.body, dict) and not getattr(exc, 'status_code', None):
                last_event_type = 'error'
            raise ProviderError(source=exc, last_event_type=last_event_type, sensitive=sensitive) from None

    def continue_with(self, messages, content, calls, results):
        messages.extend(content)
        messages.extend({'type': 'function_call_output', 'call_id': call.id, 'output': result}
                        for call, result in zip(calls, results))


ADAPTERS = {'anthropic': Claude, 'openai': GPT}
