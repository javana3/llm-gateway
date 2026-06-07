from app.sse import assemble_content_from_sse, replay_content_as_sse


def test_assemble_content_from_openai_style_sse():
    sse = (
        b'data: {"choices":[{"index":0,"delta":{"content":"He"}}]}\n\n'
        b'data: {"choices":[{"index":0,"delta":{"content":"llo"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    assert assemble_content_from_sse(sse) == "Hello"


def test_assemble_ignores_non_data_and_done():
    sse = b": comment\n\ndata: [DONE]\n\n"
    assert assemble_content_from_sse(sse) == ""


def test_replay_roundtrips_through_assemble():
    chunks = list(replay_content_as_sse("Hello world", chunk_size=3))
    body = b"".join(chunks)
    assert b"[DONE]" in body
    assert assemble_content_from_sse(body) == "Hello world"
