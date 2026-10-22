from autocut.models import JobOptions
from autocut.presets import PRESETS, apply_preset


def test_custom_preset_keeps_options():
    options = JobOptions(clips=2, style="clean", layout="crop")
    assert apply_preset(options) == options


def test_shorts_preset_overrides_presentation():
    options = JobOptions(clips=2, preset="shorts", style="clean")
    result = apply_preset(options)
    assert result.style == "karaoke"
    assert result.caption_mode == "word"
    assert result.layout == "blur"
    assert result.variation == "strong"
    assert result.min_duration == 8
    assert result.max_duration == 25
    assert result.target_duration == 15


def test_preset_keeps_user_specific_fields():
    options = JobOptions(
        clips=3,
        preset="podcast",
        watermark="@nick",
        ranges=[(1.0, 9.0)],
        proxy="socks5://127.0.0.1:1080",
    )
    result = apply_preset(options)
    assert result.watermark == "@nick"
    assert result.ranges == [(1.0, 9.0)]
    assert result.proxy == "socks5://127.0.0.1:1080"
    assert result.clips == 3


def test_all_presets_are_valid():
    for name, values in PRESETS.items():
        options = apply_preset(JobOptions(preset=name))
        assert options.layout in {"blur", "crop"}
        assert options.style in {"auto", "clean", "bold", "karaoke", "minimal"}
        assert options.caption_mode in {"phrase", "word"}
        assert options.min_duration <= options.target_duration <= options.max_duration
        assert values
