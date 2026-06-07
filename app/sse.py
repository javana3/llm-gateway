import json
from collections.abc import Iterator


def assemble_content_from_sse(raw: bytes) -> str:
    """从 OpenAI 风格 SSE 字节流里拼出完整 assistant 文本。"""
    parts: list[str] = []
    for line in raw.split(b"\n"):
        line = line.strip()
        if not line.startswith(b"data:"):
            continue
        payload = line[len(b"data:") :].strip()
        if payload == b"[DONE]" or not payload:
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for choice in obj.get("choices", []):
            piece = choice.get("delta", {}).get("content")
            if piece:
                parts.append(piece)
    return "".join(parts)


def replay_content_as_sse(content: str, chunk_size: int = 16) -> Iterator[bytes]:
    """把缓存的完整文本切块，合成 OpenAI 风格 SSE 逐块吐，模拟流式体验。"""
    for i in range(0, len(content), chunk_size):
        piece = content[i : i + chunk_size]
        obj = {"choices": [{"index": 0, "delta": {"content": piece}}]}
        yield f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")
    yield b"data: [DONE]\n\n"
