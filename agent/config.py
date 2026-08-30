import os


def _load_dotenv():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    except ImportError:
        pass


_load_dotenv()


def _env(key, default):
    val = os.environ.get(key)
    return val if val not in (None, "") else default


LLM_CONFIG = {
    "api_key": _env("LLM_API_KEY", ""),
    "model_name": _env("LLM_MODEL", "deepseek-chat"),
    "base_url": _env("LLM_BASE_URL", "https://api.deepseek.com/v1"),
    "temperature": float(_env("LLM_TEMPERATURE", "0.7")),
    "max_tokens": int(_env("LLM_MAX_TOKENS", "8192")),
}


SYSTEM_CONFIG = {
    "enable_llm": True,
    "log_level": "INFO",
    "max_retries": 3,
    "timeout": 60,
}


RAG_CONFIG = {
    "embedding_model": "data/models/bge-small-zh-v1.5",
}


RESILIENCE_CONFIG = {
    "max_retries": 3,
    "retry_base_delay_sec": 1.0,
    "retry_max_delay_sec": 30.0,
    "circuit_failure_threshold": 5,
    "circuit_recovery_timeout_sec": 60.0,
    "circuit_half_open_successes": 2,
    "health_check_timeout_sec": 10.0,
}
