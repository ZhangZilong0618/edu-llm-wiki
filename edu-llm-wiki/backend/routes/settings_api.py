"""API for reading/writing LLM settings to .env file."""

from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

from config import settings as app_settings

router = APIRouter(prefix="/api/settings", tags=["settings"])

ENV_PATH = Path(__file__).parent.parent / ".env"


class LlmSettings(BaseModel):
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = ""
    llm_max_tokens: int = 8192
    llm_temperature: float = 0.3


class EmbeddingSettings(BaseModel):
    embedding_enabled: bool = False
    embedding_endpoint: str = "http://localhost:11434/v1/embeddings"
    embedding_api_key: str = ""
    embedding_model: str = "nomic-embed-text"


class PaddleocrSettings(BaseModel):
    paddleocr_token: str = ""
    paddleocr_model: str = "PaddleOCR-VL-1.6"
    paddleocr_orientation: bool = False
    paddleocr_unwarping: bool = False
    paddleocr_chart: bool = False


class AllSettings(BaseModel):
    llm: LlmSettings
    embedding: EmbeddingSettings
    paddleocr: PaddleocrSettings


def _read_env() -> dict[str, str]:
    """Read .env file into a dict."""
    if not ENV_PATH.exists():
        return {}
    result = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            result[key.strip()] = val.strip().strip('"').strip("'")
    return result


def _write_env(updates: dict[str, str]):
    """Update keys in .env file, preserving existing content and comments."""
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    updated_keys = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        if "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Append keys not found
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # Also update in-memory settings
    _apply_to_app(key=updates)


def _apply_to_app(key: str = None, **updates):
    """Apply config changes to running app (best-effort)."""
    env = _read_env()
    for k, v in env.items():
        k_lower = k.lower()
        if hasattr(app_settings, k_lower):
            try:
                if isinstance(getattr(app_settings, k_lower), bool):
                    setattr(app_settings, k_lower, v.lower() in ("true", "1", "yes"))
                elif isinstance(getattr(app_settings, k_lower), int):
                    setattr(app_settings, k_lower, int(v))
                elif isinstance(getattr(app_settings, k_lower), float):
                    setattr(app_settings, k_lower, float(v))
                else:
                    setattr(app_settings, k_lower, v)
            except (ValueError, TypeError):
                pass


@router.get("/llm")
async def get_llm_settings():
    """Get current LLM configuration."""
    env = _read_env()
    return {
        "llm_provider": env.get("LLM_PROVIDER", "openai"),
        "llm_api_key": env.get("LLM_API_KEY", ""),
        "llm_model": env.get("LLM_MODEL", "gpt-4o-mini"),
        "llm_base_url": env.get("LLM_BASE_URL", ""),
        "llm_max_tokens": int(env.get("LLM_MAX_TOKENS", "8192")),
        "llm_temperature": float(env.get("LLM_TEMPERATURE", "0.3")),
    }


@router.put("/llm")
async def save_llm_settings(data: LlmSettings):
    """Save LLM configuration to .env."""
    updates = {
        "LLM_PROVIDER": data.llm_provider,
        "LLM_API_KEY": data.llm_api_key,
        "LLM_MODEL": data.llm_model,
        "LLM_BASE_URL": data.llm_base_url,
        "LLM_MAX_TOKENS": str(data.llm_max_tokens),
        "LLM_TEMPERATURE": str(data.llm_temperature),
    }
    _write_env(updates)
    return {"status": "saved"}


@router.post("/llm/test")
async def test_llm_connection(data: LlmSettings):
    """Save settings and test the LLM connection with a minimal request."""
    updates = {
        "LLM_PROVIDER": data.llm_provider,
        "LLM_API_KEY": data.llm_api_key,
        "LLM_MODEL": data.llm_model,
        "LLM_BASE_URL": data.llm_base_url,
        "LLM_MAX_TOKENS": str(data.llm_max_tokens),
        "LLM_TEMPERATURE": str(data.llm_temperature),
    }
    _write_env(updates)

    from services.llm_client import test_connection
    ok, message = await test_connection(data)
    return {"ok": ok, "message": message}


@router.get("/embedding")
async def get_embedding_settings():
    """Get embedding configuration."""
    env = _read_env()
    return {
        "embedding_enabled": env.get("EMBEDDING_ENABLED", "false").lower() == "true",
        "embedding_endpoint": env.get("EMBEDDING_ENDPOINT", "http://localhost:11434/v1/embeddings"),
        "embedding_api_key": env.get("EMBEDDING_API_KEY", ""),
        "embedding_model": env.get("EMBEDDING_MODEL", "nomic-embed-text"),
    }


@router.put("/embedding")
async def save_embedding_settings(data: EmbeddingSettings):
    """Save embedding configuration to .env."""
    updates = {
        "EMBEDDING_ENABLED": "true" if data.embedding_enabled else "false",
        "EMBEDDING_ENDPOINT": data.embedding_endpoint,
        "EMBEDDING_API_KEY": data.embedding_api_key,
        "EMBEDDING_MODEL": data.embedding_model,
    }
    _write_env(updates)
    return {"status": "saved"}


@router.get("/paddleocr")
async def get_paddleocr_settings():
    """Get PaddleOCR (document parsing) configuration."""
    env = _read_env()
    return {
        "paddleocr_token": env.get("PADDLEOCR_TOKEN", ""),
        "paddleocr_model": env.get("PADDLEOCR_MODEL", "PaddleOCR-VL-1.6"),
        "paddleocr_orientation": env.get("PADDLEOCR_ORIENTATION", "false").lower() == "true",
        "paddleocr_unwarping": env.get("PADDLEOCR_UNWARPING", "false").lower() == "true",
        "paddleocr_chart": env.get("PADDLEOCR_CHART", "false").lower() == "true",
    }


@router.put("/paddleocr")
async def save_paddleocr_settings(data: PaddleocrSettings):
    """Save PaddleOCR configuration to .env."""
    updates = {
        "PADDLEOCR_TOKEN": data.paddleocr_token,
        "PADDLEOCR_MODEL": data.paddleocr_model,
        "PADDLEOCR_ORIENTATION": "true" if data.paddleocr_orientation else "false",
        "PADDLEOCR_UNWARPING": "true" if data.paddleocr_unwarping else "false",
        "PADDLEOCR_CHART": "true" if data.paddleocr_chart else "false",
    }
    _write_env(updates)
    return {"status": "saved"}
