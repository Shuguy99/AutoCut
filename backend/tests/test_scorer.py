import scorer


def test_merge_into_chunks_respects_time_bound():
    # редкая речь: сегменты по 5 слов, но разбросаны на 80 секунд — не должны слиться в один чанк
    segs = [
        {"start": i * 80.0, "end": i * 80.0 + 5.0, "text": "слово слово слово слово слово",
         "words": [{"w": "слово", "start": 0, "end": 1}] * 5}
        for i in range(3)
    ]
    chunks = scorer.merge_into_chunks(segs)
    assert len(chunks) == 3


def test_scores_are_monotone():
    assert scorer._scores_are_monotone([{"score": 5}, {"score": 8}, {"score": 9}]) is True
    assert scorer._scores_are_monotone([{"score": 1}, {"score": 88}, {"score": 50}]) is False
    assert scorer._scores_are_monotone([{"score": 42}]) is False


def test_to_score_clamps():
    assert scorer._to_score(150) == 99
    assert scorer._to_score("0") == 1
    assert scorer._to_score(10) == 10
    assert scorer._to_score("мусор") == 1


def test_score_chunks_retries_on_monotone(monkeypatch):
    calls = []

    def fake_call(chunks, force_spread=False):
        calls.append(force_spread)
        if force_spread:
            return [{"chunk_id": c["chunk_id"], "score": 5 + i * 10} for i, c in enumerate(chunks)]
        return [{"chunk_id": c["chunk_id"], "score": 5} for c in chunks]

    monkeypatch.setattr(scorer, "_call_ollama", fake_call)
    chunks = [{"start": float(i), "end": float(i) + 1.0, "text": "а б в", "segments": []} for i in range(5)]
    out = scorer.score_chunks(chunks)
    assert calls == [False, True]
    scores = [c["score"] for c in out]
    assert len(set(scores)) > 1
    assert min(scores) > 0


def test_score_chunks_reports_progress(monkeypatch):
    def fake_call(chunks, force_spread=False):
        return [{"chunk_id": c["chunk_id"], "score": 5} for c in chunks]

    monkeypatch.setattr(scorer, "_call_ollama", fake_call)
    chunks = [{"start": float(i), "end": float(i) + 1.0, "text": "а б в", "segments": []} for i in range(3)]
    reported: list[int] = []
    scorer.score_chunks(chunks, progress_cb=lambda done: reported.append(done))
    assert reported == [3]