from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.capabilities import has_capability

DEFAULT_ENDPOINTS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "openai-codex": "https://chatgpt.com/backend-api/codex",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "xai": "https://api.x.ai/v1",
    "xai-oauth": "https://api.x.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "huggingface": "https://router.huggingface.co/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "mistral": "https://api.mistral.ai/v1",
    "zai": "https://api.z.ai/api/coding/paas/v4",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "groq": "https://api.groq.com/openai/v1",
    "moonshot": "https://api.moonshot.ai/v1",
    "minimax": "https://api.minimax.io/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "ollama": "http://127.0.0.1:11434/v1",
    "vllm": "http://127.0.0.1:8000/v1",
    "lmstudio": "http://127.0.0.1:1234/v1",
    "llamacpp": "http://127.0.0.1:8080/v1",
}

SEED: list[dict[str, Any]] = [
    {"id": "openai", "name": "OpenAI", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision", "image-gen", "image-edit", "transcription"]},
    {"id": "anthropic", "name": "Anthropic", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision"]},
    {"id": "gemini", "name": "Google Gemini", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision", "image-gen", "image-edit", "music", "video"]},
    {"id": "openai-codex", "name": "OpenAI Codex", "kind": "cloud", "auth": "oauth", "capabilities": ["chat", "vision", "image-gen", "image-edit"]},
    {"id": "xai", "name": "xAI Grok", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision", "image-gen", "image-edit", "video"]},
    {"id": "xai-oauth", "name": "xAI SuperGrok", "kind": "cloud", "auth": "oauth", "capabilities": ["chat", "vision", "image-gen", "image-edit", "video"]},
    {"id": "openrouter", "name": "OpenRouter", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision", "image-gen", "image-edit"]},
    {"id": "huggingface", "name": "Hugging Face", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision", "image-gen"]},
    {"id": "deepseek", "name": "DeepSeek", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision"]},
    {"id": "mistral", "name": "Mistral", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision"]},
    {"id": "zai", "name": "Z.ai GLM", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision"]},
    {"id": "qwen", "name": "Qwen", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision"]},
    {"id": "groq", "name": "Groq", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision"]},
    {"id": "moonshot", "name": "Moonshot Kimi", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision"]},
    {"id": "minimax", "name": "MiniMax", "kind": "cloud", "auth": "key", "capabilities": ["chat", "vision"]},
    {"id": "cerebras", "name": "Cerebras", "kind": "cloud", "auth": "key", "capabilities": ["chat"]},
    {"id": "ollama", "name": "Ollama", "kind": "local", "auth": "none", "capabilities": ["chat", "vision"]},
    {"id": "vllm", "name": "vLLM", "kind": "local", "auth": "optional", "capabilities": ["chat", "vision"]},
    {"id": "lmstudio", "name": "LM Studio", "kind": "local", "auth": "optional", "capabilities": ["chat", "vision"]},
    {"id": "llamacpp", "name": "llama.cpp", "kind": "local", "auth": "optional", "capabilities": ["chat", "vision"]},
]

CV = ["chat", "vision"]
IG = ["image-gen", "image-edit"]
MUSIC = ["music"]
VIDEO = ["video"]
TR = ["transcription"]
SEED_MODELS: dict[str, list[dict[str, Any]]] = {
    "openai": [
        {"id": "gpt-5.6-luna", "label": "GPT-5.6 Luna", "capabilities": CV},
        {"id": "gpt-5.6-terra", "label": "GPT-5.6 Terra", "capabilities": CV},
        {"id": "gpt-5.6-sol", "label": "GPT-5.6 Sol", "capabilities": CV},
        {"id": "gpt-5.5", "label": "GPT-5.5", "capabilities": CV},
        {"id": "gpt-5.2", "label": "GPT-5.2", "capabilities": CV},
        {"id": "gpt-4.1", "label": "GPT-4.1", "capabilities": CV},
        {"id": "gpt-4o", "label": "GPT-4o", "capabilities": CV},
        {"id": "gpt-4o-transcribe-diarize", "label": "GPT-4o Transcribe Diarize", "capabilities": TR, "recommended": True},
        {"id": "gpt-4o-transcribe", "label": "GPT-4o Transcribe", "capabilities": TR},
        {"id": "gpt-4o-mini-transcribe", "label": "GPT-4o Mini Transcribe", "capabilities": TR},
        {"id": "gpt-image-2", "label": "GPT Image 2", "capabilities": IG, "recommended": True},
        {"id": "gpt-image-1.5", "label": "GPT Image 1.5", "capabilities": IG},
        {"id": "gpt-image-1", "label": "GPT Image 1", "capabilities": IG},
    ],
    "anthropic": [
        {"id": "claude-opus-4-6", "label": "Claude Opus 4.6", "capabilities": CV},
        {"id": "claude-sonnet-4-6", "label": "Claude Sonnet 4.6", "capabilities": CV},
        {"id": "claude-sonnet-4-5", "label": "Claude Sonnet 4.5", "capabilities": CV},
    ],
    "gemini": [
        {"id": "gemini-3-flash", "label": "Gemini 3 Flash", "capabilities": CV},
        {"id": "gemini-3-pro", "label": "Gemini 3 Pro", "capabilities": CV},
        {"id": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "capabilities": CV},
        {"id": "gemini-3-pro-image", "label": "Gemini 3 Pro Image", "capabilities": IG},
        {"id": "gemini-3-pro-image-preview", "label": "Gemini 3 Pro Image Preview", "capabilities": IG},
        {"id": "gemini-2.5-flash-image", "label": "Gemini 2.5 Flash Image", "capabilities": IG},
        {"id": "lyria-3-clip-preview", "label": "Lyria 3 Clip", "capabilities": MUSIC},
        {"id": "lyria-3-pro-preview", "label": "Lyria 3 Pro", "capabilities": MUSIC},
        {"id": "veo-3.1-generate-preview", "label": "Veo 3.1", "capabilities": VIDEO},
    ],
    "xai": [
        {"id": "grok-4.6", "label": "Grok 4.6", "capabilities": CV},
        {"id": "grok-imagine-video", "label": "Grok Imagine Video", "capabilities": VIDEO},
    ],
    "xai-oauth": [
        {"id": "grok-4.6", "label": "Grok 4.6", "capabilities": CV},
        {"id": "grok-imagine-video", "label": "Grok Imagine Video", "capabilities": VIDEO},
    ],
    "openrouter": [
        {"id": "openrouter/free", "label": "Free", "capabilities": CV},
        {"id": "openrouter/auto", "label": "Auto", "capabilities": CV + IG},
        {"id": "openrouter/auto-beta", "label": "Auto Beta", "capabilities": CV + IG},
        {"id": "openrouter/fusion", "label": "Fusion", "capabilities": ["chat"]},
        {"id": "google/gemini-3-flash", "label": "Gemini 3 Flash", "capabilities": CV},
        {"id": "openai/gpt-5.2", "label": "GPT-5.2", "capabilities": CV},
        {"id": "openai/gpt-image-1", "label": "GPT Image 1", "capabilities": IG},
    ],
    "huggingface": [
        {"id": "Qwen/Qwen2.5-VL-7B-Instruct", "label": "Qwen2.5-VL 7B", "capabilities": CV},
        {"id": "black-forest-labs/FLUX.1-schnell", "label": "FLUX.1 Schnell", "capabilities": ["image-gen"]},
    ],
    "ollama": [
        {"id": "qwen3-vl:8b", "label": "Qwen3-VL 8B", "capabilities": CV},
        {"id": "llava", "label": "LLaVA", "capabilities": CV},
    ],
    "groq": [
        {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "label": "Llama 4 Scout", "capabilities": CV},
    ],
    "moonshot": [
        {"id": "kimi-k2.5", "label": "Kimi K2.5", "capabilities": CV},
    ],
    "minimax": [
        {"id": "MiniMax-M2.5", "label": "MiniMax M2.5", "capabilities": CV},
    ],
    "cerebras": [
        {"id": "llama3.1-8b", "label": "Llama 3.1 8B", "capabilities": ["chat"]},
    ],
}


def seed_catalog() -> list[dict[str, Any]]:
    rows = []
    for item in SEED:
        row = deepcopy(item)
        row["defaultEndpoint"] = DEFAULT_ENDPOINTS[item["id"]]
        row["models"] = deepcopy(SEED_MODELS.get(item["id"], []))
        rows.append(row)
    return rows


def filter_catalog(rows: list[dict[str, Any]], capability: str = "") -> list[dict[str, Any]]:
    if not capability:
        return rows
    out = []
    for row in rows:
        if has_capability(row.get("capabilities"), capability):
            copy = deepcopy(row)
            copy["models"] = [
                model for model in copy.get("models") or []
                if has_capability(model.get("capabilities"), capability)
            ]
            out.append(copy)
    return out
