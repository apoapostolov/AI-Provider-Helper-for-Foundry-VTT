from __future__ import annotations

CHAT = "chat"
VISION = "vision"
IMAGE_GEN = "image-gen"
IMAGE_EDIT = "image-edit"
MUSIC = "music"
VIDEO = "video"
EMBEDDINGS = "embeddings"
TRANSCRIPTION = "transcription"
ALL = (CHAT, VISION, IMAGE_GEN, IMAGE_EDIT, MUSIC, VIDEO, EMBEDDINGS, TRANSCRIPTION)


def capabilities_from_architecture(arch: dict | None) -> list[str]:
    arch = arch or {}
    input_mods = _list(arch.get("input_modalities"))
    output_mods = _list(arch.get("output_modalities"))
    modality = str(arch.get("modality") or "").lower()
    has_image_in = any(item in {"image", "vision"} for item in input_mods) or "image->" in modality or "vision" in modality
    has_image_out = any(item == "image" for item in output_mods) or "->image" in modality
    has_text_out = any(item == "text" for item in output_mods) or "->text" in modality or not output_mods
    has_audio_in = any(item in {"audio", "speech"} for item in input_mods) or "audio->" in modality or "speech" in modality
    has_audio_out = any(item in {"audio", "music"} for item in output_mods) or "->audio" in modality or "music" in modality
    has_video_out = "video" in output_mods or "->video" in modality or "video" in modality
    caps: list[str] = []
    if has_text_out:
        caps.append(CHAT)
    if has_image_in and has_text_out:
        caps.append(VISION)
    if has_image_out:
        caps.append(IMAGE_GEN)
    if has_image_in and has_image_out:
        caps.append(IMAGE_EDIT)
    if has_audio_out:
        caps.append(MUSIC)
    if has_video_out:
        caps.append(VIDEO)
    if has_audio_in and has_text_out:
        caps.append(TRANSCRIPTION)
    return caps


def capabilities_from_pipeline_tag(tag: str) -> list[str]:
    match str(tag or "").lower():
        case "image-text-to-text" | "visual-question-answering" | "image-to-text":
            return [CHAT, VISION]
        case "text-to-image":
            return [IMAGE_GEN]
        case "image-to-image":
            return [IMAGE_EDIT]
        case "text-generation" | "text2text-generation" | "conversational":
            return [CHAT]
        case "feature-extraction" | "sentence-similarity":
            return [EMBEDDINGS]
        case "automatic-speech-recognition" | "speech-to-text":
            return [TRANSCRIPTION]
        case _:
            return []


def has_capability(values: list[str] | None, capability: str) -> bool:
    return bool(values) and capability in values


def _list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).lower() for item in value]
