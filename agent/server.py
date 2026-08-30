

import asyncio
import json
import os
import sys

project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from core import AligoCore, render_result_plain
from config import LLM_CONFIG, RESILIENCE_CONFIG
from utils.llm_resilience import run_health_check

app = FastAPI(title="Aligo Travel Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_cores: dict = {}
_cores_lock = asyncio.Lock()


async def _get_or_create_core(user_id: str) -> AligoCore:
    async with _cores_lock:
        core = _cores.get(user_id)
        if core is None:
            core = AligoCore(user_id=user_id)
            await core.initialize()
            _cores[user_id] = core
    return core


def _extract_messages(messages) -> tuple:
    web_context = ""
    user_text = ""
    for m in messages or []:
        role = m.get("role", "")
        content = m.get("content", "")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        content = (content or "").strip()
        if role == "system":
            web_context = content or web_context
        elif role == "user":
            user_text = content or user_text
    if not user_text:
        user_text = web_context or ""
        web_context = ""
    return user_text, web_context


def _safe_user_id(raw: str) -> str:
    cleaned = "".join(c for c in (raw or "") if c.isalnum() or c in "-_")[:64]
    return cleaned or "web_user"


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _sse_delta(content: str) -> str:
    return _sse({"choices": [{"delta": {"content": content}}]})


@app.get("/health")
async def health():
    ok, msg = await run_health_check(
        base_url=LLM_CONFIG["base_url"],
        api_key=LLM_CONFIG["api_key"],
        model_name=LLM_CONFIG["model_name"],
        timeout_sec=RESILIENCE_CONFIG.get("health_check_timeout_sec", 10.0),
    )
    return {"ok": ok, "message": msg}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = bool(body.get("stream", False))

    user_text, web_context = _extract_messages(messages)
    user_id = _safe_user_id(request.headers.get("x-client-id", ""))

    core = await _get_or_create_core(user_id)

    if stream:
        async def gen():
            yield _sse_delta("")
            result = await core.process_query(user_text, web_context=web_context)
            yield _sse_delta(result.get("message") if not result.get("ok") else render_result_plain(result["data"]))
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    result = await core.process_query(user_text, web_context=web_context)
    content = result.get("message") if not result.get("ok") else render_result_plain(result["data"])
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}
