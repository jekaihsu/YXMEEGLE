"""Authenticated AI endpoints; provider substitution lives on app.state."""
import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from time import monotonic, perf_counter
from datetime import date, timedelta
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.concurrency import run_in_threadpool

from . import ledger
from .agent import QUESTION_TIMEOUT_SECONDS, ChatRun
from .catalog import ModelId, registry
from .providers import ADAPTERS
from .project_context import ProjectContextCache, ContextUnavailable
from .tools import ReadDenied, valid_case_id


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=20000)

    @model_validator(mode='after')
    def role_limit(self):
        if '\x00' in self.content:
            raise ValueError('content contains NUL')
        if self.role == 'user' and len(self.content) > 4000:
            raise ValueError('user content exceeds 4000 characters')
        return self


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: ModelId
    conversation_id: str = Field(min_length=1, max_length=120)
    project_id: str | None = None

    @field_validator('project_id')
    @classmethod
    def project_id_valid(cls, value):
        if value is not None and not valid_case_id(value):
            raise ValueError('invalid project id')
        return value

    messages: list[Message] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def last_is_user(self):
        if self.messages[-1].role != 'user':
            raise ValueError('last message must be user')
        return self


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    usage_id: str = Field(min_length=1, max_length=36)
    rating: Literal['up', 'down', 'none']
    reason: Literal['wrong', 'incomplete', 'slow', 'other'] | None = None

    @model_validator(mode='after')
    def reason_only_down(self):
        if self.reason is not None and self.rating != 'down':
            raise ValueError('reason is only allowed with down')
        return self


@dataclass
class PendingRun:
    actor: tuple[str, str]
    expires: float = 0
    ready: asyncio.Event = field(default_factory=asyncio.Event)


class ChatResponse(StreamingResponse):
    def __init__(self, run):
        self.run = run
        super().__init__(run.stream(), media_type='text/event-stream',
                         headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no'})

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.body_iterator.aclose()
            await self.run.finish()

RUN_REGISTRATION_SECONDS = QUESTION_TIMEOUT_SECONDS + 60


def register(app, *, identity, sessions, cfg):
    app.state.ai_store_content = ledger.stores_content(cfg)
    app.state.ai_content_retention_days = ledger.content_retention(cfg)
    models = registry(cfg.get('AI_PRICE_TABLE_JSON'))
    app.state.ai_providers = {key: ADAPTERS[spec.provider](cfg[spec.key_env])
                              for key, spec in models.items() if cfg.get(spec.key_env)}
    contexts = ProjectContextCache()
    app.state.ai_project_contexts = contexts
    active = {}
    feedback_writes = {}
    feedback_lock = asyncio.Lock()
    pending = {}

    def remember(usage_id, entry, ttl):
        entry.expires = monotonic() + ttl
        pending[usage_id] = entry

        def expire():
            if pending.get(usage_id) is entry and entry.expires <= monotonic():
                del pending[usage_id]

        asyncio.get_running_loop().call_later(ttl, expire)
    limit = int(cfg.get('AI_DAILY_TOKEN_LIMIT_PER_USER', '400000'))

    def authenticated(request: Request):
        return identity(request)

    @app.get('/api/ai/models')
    def get_models(auth=Depends(authenticated)):
        return {'default': 'claude', 'models': [dict(id=key, label=spec.label,
                available=key in app.state.ai_providers) for key, spec in models.items()]}

    @app.post('/api/ai/chat')
    async def chat(request: Request, body: ChatRequest, auth=Depends(authenticated)):
        data, user = auth
        adapter = app.state.ai_providers.get(body.model)
        if adapter is None:
            return JSONResponse({'code': 'ai_unconfigured', 'message': '此模型尚未設定金鑰'}, status_code=503)
        used = await run_in_threadpool(ledger.daily_tokens, sessions, data['wid'], user['id'])
        if used >= limit:
            return JSONResponse({'code': 'ai_quota', 'message': '今日用量已達上限'}, status_code=429)
        key = (data['wid'], user['id'])
        if active.get(key, 0) >= 2:
            return JSONResponse({'code': 'ai_busy', 'message': '最多同時進行兩個提問'}, status_code=429)
        active[key] = active.get(key, 0) + 1

        released = False

        def release():
            nonlocal released
            if released:
                return
            released = True
            remaining = active[key] - 1
            if remaining:
                active[key] = remaining
            else:
                del active[key]

        started = perf_counter()
        context = None
        if body.project_id is not None:
            try:
                context = await contexts.get(app, request.headers.get('cookie', ''), data['wid'], user['id'], body.project_id)
            except ReadDenied:
                release()
                return JSONResponse({'code': 'ai_forbidden', 'message': '找不到或沒有權限查看這個案件'}, status_code=403)
            except ContextUnavailable:
                release()
                return JSONResponse({'code': 'ai_upstream', 'message': '助理暫時無法回答，請稍後重試'}, status_code=503)
            except BaseException:
                release()
                raise
        run = ChatRun(app, body, data, user, models[body.model], adapter, release)
        run.started = started
        run.project_context = context
        entry = PendingRun(key)
        remember(run.usage_id, entry, RUN_REGISTRATION_SECONDS)

        def recorded():
            remember(run.usage_id, entry, 30)
            entry.ready.set()

        run.recorded = recorded
        run.cookie = request.headers.get('cookie', '')
        return ChatResponse(run)

    @app.post('/api/ai/feedback')
    async def feedback(body: FeedbackRequest, auth=Depends(authenticated)):
        data, user = auth
        key = (data['wid'], user['id'])
        owned = await run_in_threadpool(ledger.owns_usage, sessions, *key, body.usage_id)
        if not owned:
            entry = pending.get(body.usage_id)
            if entry is None or entry.actor != key or entry.expires <= monotonic():
                raise HTTPException(404, '找不到提問')
            try:
                await asyncio.wait_for(entry.ready.wait(), timeout=3)
            except TimeoutError:
                raise HTTPException(404, '找不到提問') from None
            if not await run_in_threadpool(ledger.owns_usage, sessions, *key, body.usage_id):
                raise HTTPException(404, '找不到提問')
        async with feedback_lock:
            now = monotonic()
            for actor_key, writes in list(feedback_writes.items()):
                while writes and writes[0] <= now - 60:
                    writes.popleft()
                if not writes:
                    del feedback_writes[actor_key]
            writes = feedback_writes.get(key)
            if writes is not None and len(writes) >= 60:
                raise HTTPException(429, '評分過於頻繁')
            await run_in_threadpool(ledger.feedback, sessions, body.usage_id, user['id'], body.rating, body.reason)
            feedback_writes.setdefault(key, deque()).append(monotonic())
        return body.model_dump()

    @app.get('/api/ai/usage/export')
    @app.get('/api/ai/usage')
    def usage(request: Request, from_: date | None = Query(None, alias='from'), to: date | None = None,
              rating: Literal['up', 'down', 'none'] | None = None,
              scope: Literal['global', 'project'] | None = None,
              actor: str | None = Query(None, max_length=120), provider: ModelId | None = None,
              q: str | None = Query(None, max_length=200),
              auth=Depends(authenticated)):
        data, user = auth
        if user['role'] != 'manager':
            raise HTTPException(403, '僅主管可查看 AI 用量')
        end = to or date.fromisoformat(ledger.today())
        start = from_ or end - timedelta(days=29)
        if start > end or (end - start).days >= 366:
            raise HTTPException(422, '日期範圍錯誤')
        try:
            ledger.cleanup_content(sessions, app.state.ai_content_retention_days if app.state.ai_store_content else 0)
        except Exception:
            ledger.logger.error('ai_content_cleanup_failed')
        exporting = request.url.path.endswith('/export')
        result = ledger.query(sessions, data['wid'], start.isoformat(), end.isoformat(), actor, provider, rating, scope, q,
            content_enabled=app.state.ai_store_content, retention_days=app.state.ai_content_retention_days, export=exporting)
        if exporting:
            return Response(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in result),
                            media_type='application/x-ndjson', headers={'Cache-Control': 'no-store'})
        return result

    @app.get('/api/ai/usage/{usage_id}/exchange')
    def get_exchange(usage_id: str, auth=Depends(authenticated)):
        data, user = auth
        if user['role'] != 'manager':
            raise HTTPException(403, '僅主管可查看 AI 用量')
        result = ledger.exchange(sessions, data['wid'], usage_id, content_enabled=app.state.ai_store_content,
                                 retention_days=app.state.ai_content_retention_days)
        if result is None:
            raise HTTPException(404, '找不到提問')
        return result
