from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Project
    data_dir: str = str(Path(__file__).parent.parent / "data")
    projects_dir: str = str(Path(data_dir) / "projects")

    # LLM
    llm_provider: str = "openai"  # openai | anthropic | ollama | custom
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = ""  # for ollama/custom: http://localhost:11434/v1
    llm_max_tokens: int = 8192
    llm_temperature: float = 0.3

    # Embedding (optional)
    embedding_enabled: bool = False
    embedding_endpoint: str = "http://localhost:11434/v1/embeddings"
    embedding_api_key: str = ""
    embedding_model: str = "nomic-embed-text"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    api_token: str = ""

    # CORS
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]


settings = Settings()
