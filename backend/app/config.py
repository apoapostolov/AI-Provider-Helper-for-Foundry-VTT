from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    host: str = "127.0.0.1"
    port: int = 8090
    cache_dir: Path = Path("cache")
    debug: bool = False
    cors_origins: str = ""
    openrouter_key: str = ""
    hf_token: str = ""
    artificial_analysis_key: str = ""
    zeroeval_key: str = ""

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            host=os.environ.get("APL_HOST", "127.0.0.1"),
            port=int(os.environ.get("APL_PORT", "8090")),
            cache_dir=Path(os.environ.get("APL_CACHE", "cache")),
            debug=os.environ.get("APL_DEBUG", "0") == "1",
            cors_origins=os.environ.get("APL_CORS_ORIGINS", ""),
            openrouter_key=os.environ.get("OPENROUTER_API_KEY", ""),
            hf_token=os.environ.get("HF_TOKEN", ""),
            artificial_analysis_key=os.environ.get("ARTIFICIAL_ANALYSIS_API_KEY", ""),
            zeroeval_key=os.environ.get("ZEROEVAL_API_KEY", ""),
        )
