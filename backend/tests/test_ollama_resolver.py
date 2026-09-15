import ollama_resolver as r


def test_pick_prefers_configured():
    assert r._pick(["llama3.2:3b", "qwen2.5:7b-instruct", "qwen2.5:0.5b"], "qwen2.5:7b-instruct") == "qwen2.5:7b-instruct"


def test_pick_same_family_fallback():
    # 7b нет — подбираем из qwen2.5 (предпочтение размера 7b/8b/...)
    chosen = r._pick(["qwen2.5:0.5b", "qwen2.5:32b", "qwen2.5:14b"], "qwen2.5:7b-instruct")
    assert chosen == "qwen2.5:14b"


def test_pick_any_instruct():
    chosen = r._pick(["llama3.2:1b", "gemma2:9b-instruct"], "qwen2.5:7b-instruct")
    assert chosen == "gemma2:9b-instruct"


def test_pick_first_when_nothing_fits():
    assert r._pick(["llama3.2:1b"], "qwen2.5:7b-instruct") == "llama3.2:1b"


def test_pick_empty_returns_preferred():
    assert r._pick([], "qwen2.5:7b-instruct") == "qwen2.5:7b-instruct"


def test_resolve_cache_uses_models(monkeypatch):
    monkeypatch.setattr(r, "available_models", lambda timeout=3.0: ["qwen2.5:32b"])
    r._CACHE_MODEL = None
    assert r.resolve_model() == "qwen2.5:32b"
    # кэш: без повторного запроса
    monkeypatch.setattr(r, "available_models", lambda timeout=3.0: [])
    assert r.resolve_model() == "qwen2.5:32b"