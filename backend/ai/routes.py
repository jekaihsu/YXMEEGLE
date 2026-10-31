"""Authenticated AI endpoints; provider substitution lives on app.state."""
import asyncio
from collections import deque
from time import monotonic
from datetime import date, timedelta
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from . import ledger
from .agent import ChatRun
from .catalog import ModelId, registry
from .providers import ADAPTERS


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=20000)

    @model_validator(mode='after')
    def role_limit(self):
        if self.role == 'user' and len(self.content) > 4000:
            raise ValueError('user content exceeds 4000 characters')
        return self


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: ModelId
    conversation_id: str = Field(min_length=1, max_length=120)
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


def register(app, *, identity, sessions, cfg):
    models = registry(cfg.get('AI_PRICE_TABLE_JSON'))
    app.state.ai_providers = {key: ADAPTERS[spec.provider](cfg[spec.key_env])
                              for key, spec in models.items() if cfg.get(spec.key_env)}
    active = {}
    feedback_writes = {}
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

        run = ChatRun(app, body, data, user, models[body.model], adapter, release)
        run.cookie = request.headers.get('cookie', '')
        return ChatResponse(run)

    @app.post('/api/ai/feedback')
    async def feedback(body: FeedbackRequest, auth=Depends(authenticated)):
        data, user = auth
        now = monotonic()
        key = (data['wid'], user['id'])
        writes = feedback_writes.setdefault(key, deque())
        while writes and writes[0] <= now - 60:
            writes.popleft()
        if len(writes) >= 60:
            raise HTTPException(429, '評分過於頻繁')
        writes.append(now)
        deadline = now + 3
        while not await run_in_threadpool(ledger.owns_usage, sessions, data['wid'], user['id'], body.usage_id):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise HTTPException(404, '找不到提問')
            await asyncio.sleep(min(.05, remaining))
        await run_in_threadpool(ledger.feedback, sessions, body.usage_id, user['id'], body.rating, body.reason)
        return body.model_dump()

    @app.get('/api/ai/usage')
    def usage(request: Request, from_: date | None = Query(None, alias='from'), to: date | None = None,
              rating: Literal['up', 'down', 'none'] | None = None,
              actor: str | None = Query(None, max_length=120), provider: ModelId | None = None,
              auth=Depends(authenticated)):
        data, user = auth
        if user['role'] != 'manager':
            raise HTTPException(403, '僅主管可查看 AI 用量')
        end = to or date.fromisoformat(ledger.today())
        start = from_ or end - timedelta(days=29)
        if start > end or (end - start).days >= 366:
            raise HTTPException(422, '日期範圍錯誤')
        return ledger.query(sessions, data['wid'], start.isoformat(), end.isoformat(), actor, provider, rating)
