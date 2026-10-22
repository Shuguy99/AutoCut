from autocut.models import JobOptions
from autocut.variation import (
    STYLE_NAMES,
    build_publish,
    build_variants,
    diversity_report,
    extract_hook,
    text_similarity,
)


def _options(**kwargs) -> JobOptions:
    return JobOptions(clips=2, **kwargs)


def test_extract_hook_removes_fillers_and_truncates():
    hook = extract_hook("Ну вот, это очень важный тест для TikTok!")
    assert hook is not None
    assert not hook.lower().startswith("ну")
    assert len(hook) <= 49

    long_hook = extract_hook(" ".join(["слово"] * 20), max_words=5)
    assert long_hook is not None
    assert long_hook.endswith("…")
    assert len(long_hook.split()) <= 5


def test_extract_hook_returns_none_for_empty_text():
    assert extract_hook("") is None
    assert extract_hook("ну и а") is None


def test_extract_hook_prefers_strong_question():
    hook = extract_hook(
        "И вот мы пошли. Почему это важно? Потому что детали решают всё."
    )
    assert hook is not None
    assert "Почему это важно?" in hook


def test_build_variants_is_deterministic_and_varied():
    options = _options(variation="strong", style="auto", watermark="@nick")
    texts = ["Первая фраза про деньги.", "Вторая фраза про спорт."]
    first = build_variants("video", "job", options, texts)
    second = build_variants("video", "job", options, texts)
    other = build_variants("video", "other-job", options, texts)

    assert first == second
    assert first != other
    assert len(first) == 2
    assert first[0].style in STYLE_NAMES
    assert first[0].style != first[1].style
    assert all(variant.zoom > 1.0 for variant in first)
    assert all(variant.grade.enabled for variant in first)
    assert all(variant.watermark == "@nick" for variant in first)


def test_variation_off_keeps_clean_geometry():
    options = _options(variation="off", style="auto")
    variants = build_variants("video", "job", options, ["тестовый текст"])
    assert variants[0].style == "clean"
    assert variants[0].zoom == 1.0
    assert not variants[0].grade.enabled
    assert variants[0].hook


def test_explicit_style_is_used():
    options = _options(variation="subtle", style="karaoke")
    variants = build_variants("video", "job", options, ["текст"])
    assert variants[0].style == "karaoke"


def test_publish_contains_title_description_and_hashtags():
    options = _options(watermark="@nick")
    variants = build_variants(
        "video", "job", options,
        ["Это важный рассказ про деньги и успех."],
    )
    publish = build_publish(
        "Это важный рассказ про деньги и успех.", variants[0], "Канал", 1
    )
    assert publish["title"]
    assert publish["description"]
    assert publish["hashtags"]
    assert all(tag.startswith("#") for tag in publish["hashtags"])
    assert publish["channel"] == "Канал"


def test_diversity_report_flags_similar_texts():
    same = diversity_report(["один два три четыре", "один два три четыре"])
    assert same["ok"] is False
    assert same["max_similarity"] == 1.0
    assert same["pairs"][0]["a"] == 1

    different = diversity_report(["деньги успех бизнес", "спорт тренировки бег"])
    assert different["ok"] is True
    assert different["score"] == 1.0
    assert text_similarity("деньги успех", "деньги успех") == 1.0
