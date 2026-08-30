import asyncio
import logging
import time
from typing import TypeVar, Callable, Awaitable, Tuple

from .circuit_breaker import CircuitBreaker, CircuitOpenError

logger = logging.getLogger(__name__)

T = TypeVar("T")


def is_retriable_error(exc: BaseException) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
        return True
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return True
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
        return True
    if "timeout" in msg or "timed out" in msg:
        return True
    return False


async def retry_with_backoff(
    coro_factory: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    base_delay_sec: float = 1.0,
    max_delay_sec: float = 30.0,
    jitter: bool = True,
) -> T:
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_factory()
        except CircuitOpenError:
            raise
        except Exception as e:
            last_exc = e
            if attempt == max_retries or not is_retriable_error(e):
                raise
            delay = min(base_delay_sec * (2 ** attempt), max_delay_sec)
            if jitter:
                import random
                delay = delay * (0.5 + random.random())
            logger.warning(
                "LLM call failed (attempt %d/%d), retry in %.1fs: %s",
                attempt + 1, max_retries + 1, delay, e,
            )
            await asyncio.sleep(delay)
    raise last_exc


async def run_health_check(
    base_url: str,
    api_key: str,
    model_name: str,
    timeout_sec: float = 10.0,
) -> Tuple[bool, str]:
    try:
        from agentscope.model import OpenAIChatModel
    except ImportError:
        return False, "AgentScope not installed"

    try:
        model = OpenAIChatModel(
            model_name=model_name,
            api_key=api_key,
            client_kwargs={"base_url": base_url, "timeout": timeout_sec},
            temperature=0,
            max_tokens=5,
        )

        messages = [{"role": "user", "content": "1"}]
        response = await model(messages)

        text = ""
        if hasattr(response, "__aiter__"):
            async for chunk in response:
                if isinstance(chunk, str):
                    text = chunk
                    break
                if hasattr(chunk, "content"):
                    text = getattr(chunk, "content", "") or ""
                    break
        elif hasattr(response, "text"):
            text = response.text
        elif hasattr(response, "content"):
            text = response.content or ""
        elif isinstance(response, dict) and "content" in response:
            text = response["content"] or ""

        if text is not None and len(str(text)) >= 0:
            return True, "ok"
        return True, "ok (no content)"
    except Exception as e:
        return False, str(e)
