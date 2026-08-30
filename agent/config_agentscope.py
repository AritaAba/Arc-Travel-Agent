import agentscope
from config import LLM_CONFIG

def init_agentscope():
    agentscope.init(
        project="Aligo-Travel-Planning",
        name="multi_agent_system",
        logging_level="INFO"
    )

    print(f"✓ AgentScope initialized (version: {agentscope.__version__})")


def get_model_config():
    return {
        "model_type": "openai_chat",
        "config_name": "doubao_api",
        "model_name": LLM_CONFIG["model_name"],
        "api_key": LLM_CONFIG["api_key"],
        "base_url": LLM_CONFIG["base_url"],
        "temperature": LLM_CONFIG.get("temperature", 0.7),
        "max_tokens": LLM_CONFIG.get("max_tokens", 2000),
    }
