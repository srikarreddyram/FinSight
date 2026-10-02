"""Central settings. Every value can be overridden with a FINSIGHT_* env var or a .env file."""

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
# Provider SDKs read their keys (GEMINI_API_KEY, ANTHROPIC_API_KEY) from the environment, so load .env into it.
load_dotenv(ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FINSIGHT_", env_file=ROOT / ".env", extra="ignore")

    # Paths
    data_dir: Path = ROOT / "data"
    filings_dir: Path = ROOT / "data" / "filings"
    parsed_dir: Path = ROOT / "data" / "parsed"
    cache_dir: Path = ROOT / "data" / "cache"

    # Qdrant: set qdrant_url to use the Docker server; otherwise an embedded on-disk store is used.
    qdrant_url: str | None = None
    qdrant_path: Path = ROOT / "data" / "qdrant"
    collection: str = "finsight"

    # Local models (all run through fastembed / ONNX, no torch needed at query time)
    dense_model: str = "BAAI/bge-base-en-v1.5"
    sparse_model: str = "Qdrant/bm25"
    reranker_model: str = "BAAI/bge-reranker-base"
    # Bulk document embedding: "auto" uses torch on Apple MPS / CUDA when available (~4x faster than
    # ONNX on CPU, same vectors to 1e-5), else fastembed. Queries always use fastembed.
    embed_device: str = "auto"

    # LLM roles as "provider:model" (providers: gemini, ollama, anthropic), sized to the Gemini API
    # free tier (per AI Studio, Sep 2026): Flash models allow only 20 requests/day, Flash-Lite 500/day,
    # Gemma 4 14,400/day but 16K tokens/minute. Gemini 2.5 models are closed to new keys.
    answer_model: str = "gemini:gemini-3.5-flash-lite"
    fast_model: str = "gemini:gemma-4-26b-a4b-it"  # query parsing (high daily quota)
    judge_model: str = "gemini:gemma-4-26b-a4b-it"  # eval grading: a different model family from the answerer
    # One-off table summaries at index time: ~240 large batched calls for the FinanceBench corpus. Flash-Lite's
    # 250K tokens/minute finishes in ~20 minutes; Gemma's 16K/minute would take ~4 hours (but costs no Flash-Lite quota).
    summary_model: str = "gemini:gemini-3.5-flash-lite"
    summary_batch_tokens: int = 12_000
    gemini_fallback_model: str | None = "gemma-4-26b-a4b-it"  # used when a model keeps returning 503s
    # When a model's daily free-tier quota is spent, the live app switches to this one instead of failing.
    # The eval harness disables it so a benchmark run always uses a single answer model.
    quota_fallback_model: str | None = "gemini:gemma-4-26b-a4b-it"
    # Route every role to one model, e.g. "ollama:llama3.1:8b" for unlimited local dev runs.
    model_override: str | None = None
    # Free-tier limits per model: requests/minute and input tokens/minute.
    llm_rpm: dict[str, int] = {
        "gemini-3.8-flash": 5,
        "gemini-3.7-flash": 5,
        "gemini-3.5-flash": 5,
        "gemini-3.5-flash-lite": 15,
        "gemini-3.1-flash-lite": 15,
        "gemma-4-26b-a4b-it": 30,
        "gemma-4-31b-it": 30,
    }
    llm_tpm: dict[str, int] = {
        "gemini-3.8-flash": 250_000,
        "gemini-3.7-flash": 250_000,
        "gemini-3.5-flash": 250_000,
        "gemini-3.5-flash-lite": 250_000,
        "gemini-3.1-flash-lite": 250_000,
        "gemma-4-26b-a4b-it": 16_000,
        "gemma-4-31b-it": 16_000,
    }
    llm_timeout_s: int = 45
    ollama_url: str = "http://localhost:11434"
    ollama_num_ctx: int = 16384

    # Chunking
    chunk_tokens: int = 500
    chunk_overlap: float = 0.15
    table_max_tokens: int = 1800  # larger tables are split into row groups that repeat the header

    # Retrieval
    retrieve_k: int = 30
    rerank_k: int = 8
    rrf_k: int = 60
    # Final ranking = blend * reranker score + (1 - blend) * normalised fusion score. 1.0 = pure reranker.
    # Tuned on half of FinanceBench (eval/tune_retrieval.py): held-out recall@10 76.0% -> 78.7%.
    rerank_blend: float = 0.6
    # Reserve this many of the final slots for the best-scoring tables (cross-encoders underrate grids).
    table_slots: int = 4
    # Minimum sigmoid(reranker logit) of the best passage before we attempt an answer.
    evidence_threshold: float = 0.05

    # SEC EDGAR requires a User-Agent with a contact, e.g. "FinSight research you@example.com"
    sec_user_agent: str | None = None
    chrome_path: str = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


@lru_cache
def get_settings() -> Settings:
    return Settings()
