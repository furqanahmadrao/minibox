"""Agent management and model provider API."""

from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/agent", tags=["agent"])


class ModelProvider(BaseModel):
    """AI model provider configuration."""
    id: str
    name: str
    base_url: str
    models: list[dict] = []
    requires_api_key: bool = True


class AgentInfo(BaseModel):
    """Agent runtime information."""
    id: str
    name: str
    description: str
    install_cmd: str
    providers: list[str] = []


# Built-in providers
PROVIDERS: dict[str, ModelProvider] = {
    "openai": ModelProvider(
        id="openai",
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        models=[
            {"id": "gpt-4o", "name": "GPT-4o", "context": 128000},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "context": 128000},
            {"id": "gpt-4-turbo", "name": "GPT-4 Turbo", "context": 128000},
            {"id": "o1", "name": "o1", "context": 200000},
            {"id": "o1-mini", "name": "o1 Mini", "context": 128000},
        ],
    ),
    "anthropic": ModelProvider(
        id="anthropic",
        name="Anthropic",
        base_url="https://api.anthropic.com/v1",
        models=[
            {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "context": 200000},
            {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "context": 200000},
            {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "context": 200000},
            {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus", "context": 200000},
        ],
    ),
    "google": ModelProvider(
        id="google",
        name="Google AI",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        models=[
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "context": 1000000},
            {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "context": 2000000},
            {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "context": 1000000},
        ],
    ),
    "openrouter": ModelProvider(
        id="openrouter",
        name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        models=[
            {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4 (via OpenRouter)", "context": 200000},
            {"id": "openai/gpt-4o", "name": "GPT-4o (via OpenRouter)", "context": 128000},
            {"id": "google/gemini-2.0-flash-001", "name": "Gemini 2.0 Flash (via OpenRouter)", "context": 1000000},
        ],
    ),
    "deepseek": ModelProvider(
        id="deepseek",
        name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        models=[
            {"id": "deepseek-chat", "name": "DeepSeek Chat", "context": 64000},
            {"id": "deepseek-coder", "name": "DeepSeek Coder", "context": 64000},
        ],
    ),
    "groq": ModelProvider(
        id="groq",
        name="Groq",
        base_url="https://api.groq.com/openai/v1",
        models=[
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B", "context": 128000},
            {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B", "context": 32768},
        ],
    ),
    "custom": ModelProvider(
        id="custom",
        name="Custom Provider",
        base_url="",
        models=[],
        requires_api_key=True,
    ),
}

# Built-in agents — exactly 4 coding agents + manual (no agent)
AGENTS: dict[str, AgentInfo] = {
    "claude-code": AgentInfo(
        id="claude-code",
        name="Claude Code",
        description="Anthropic's official CLI agent",
        install_cmd="npm install -g @anthropic-ai/claude-code",
        providers=["anthropic", "custom"],
    ),
    "opencode": AgentInfo(
        id="opencode",
        name="OpenCode",
        description="Open source AI coding agent",
        install_cmd="npm install -g opencode",
        providers=["openai", "anthropic", "google", "openrouter", "deepseek", "groq", "custom"],
    ),
    "codex": AgentInfo(
        id="codex",
        name="Codex",
        description="OpenAI's coding agent",
        install_cmd="npm install -g @openai/codex",
        providers=["openai", "custom"],
    ),
    "pi": AgentInfo(
        id="pi",
        name="Pi",
        description="Pi coding agent by Earendil",
        install_cmd="npm install -g @earendil-works/pi-coding-agent",
        providers=["anthropic", "openai", "google", "custom"],
    ),
    "manual": AgentInfo(
        id="manual",
        name="Manual",
        description="No agent — manual terminal access only",
        install_cmd="",
        providers=[],
    ),
}


@router.get("/providers")
async def list_providers() -> list[ModelProvider]:
    """List all supported model providers."""
    return list(PROVIDERS.values())


@router.get("/providers/{provider_id}")
async def get_provider(provider_id: str) -> ModelProvider:
    """Get provider details including available models."""
    if provider_id not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    return PROVIDERS[provider_id]


@router.get("/list")
async def list_agents() -> list[AgentInfo]:
    """List all supported agent runtimes."""
    return list(AGENTS.values())


@router.get("/{agent_id}")
async def get_agent(agent_id: str) -> AgentInfo:
    """Get agent details."""
    if agent_id not in AGENTS:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    return AGENTS[agent_id]


@router.post("/fetch-models")
async def fetch_models(body: dict = Body(...)) -> list[dict]:
    """Fetch available models from a provider's API."""
    import httpx

    provider_id = body.get("provider_id", "")
    base_url = body.get("base_url", "")
    api_key = body.get("api_key", "")

    if provider_id == "custom" and not base_url:
        raise HTTPException(status_code=400, detail="base_url required for custom provider")

    provider = PROVIDERS.get(provider_id)
    if provider_id != "custom" and provider:
        base_url = provider.base_url

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            headers = {}
            if api_key:
                if provider_id == "anthropic":
                    headers["x-api-key"] = api_key
                    headers["anthropic-version"] = "2023-06-01"
                else:
                    headers["Authorization"] = f"Bearer {api_key}"

            resp = await client.get(f"{base_url}/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()

            models = []
            for m in data.get("data", []):
                models.append({
                    "id": m.get("id", ""),
                    "name": m.get("id", ""),
                    "context": m.get("context_length", 0),
                })
            return models
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch models: {str(e)}")
