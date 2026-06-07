from app.cache.embedder import Embedder, FakeEmbedder


def test_fake_embedder_is_deterministic_and_normalized():
    emb = FakeEmbedder(dim=16)
    v1 = emb.embed("hello world")
    v2 = emb.embed("hello world")
    assert v1 == v2  # 确定性
    assert len(v1) == 16
    # 单位向量（L2 范数约等于 1）
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_fake_embedder_similar_text_closer_than_unrelated():
    emb = FakeEmbedder(dim=64)

    def cos(a, b):
        return sum(x * y for x, y in zip(a, b))

    base = emb.embed("the quick brown fox")
    near = emb.embed("the quick brown foxes")  # 仅末尾不同
    far = emb.embed("zzzzz qqqqq")
    assert cos(base, near) > cos(base, far)


def test_embedder_is_abstract():
    import pytest

    with pytest.raises(TypeError):
        Embedder()  # 抽象类不可实例化
