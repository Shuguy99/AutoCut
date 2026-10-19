from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from .models import Transcript

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e",
    "ё": "e", "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k",
    "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "",
    "э": "e", "ю": "yu", "я": "ya", "і": "i", "ї": "yi", "є": "ye",
    "ґ": "g",
}


def _transliterate(value: str) -> str:
    lowered = value.lower()
    return "".join(_TRANSLIT.get(char, char) for char in lowered)


def slugify(text: str, ascii_only: bool = False, max_len: int = 60) -> str:
    value = (text or "").strip()
    if ascii_only:
        value = _transliterate(value)
        value = (
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
    value = re.sub(r"[^\w\-]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"[-_]{2,}", "-", value).strip("-_").lower()
    return value[:max_len].strip("-_") or "video"


def create_result_dir(
    output_dir: Path,
    channel: str,
    video_id: str,
    title: str,
    ascii_slug: bool = False,
) -> Path:
    channel_slug = slugify(
        channel or "unknown", ascii_only=ascii_slug, max_len=40
    )
    name = (
        f"{slugify(video_id or 'video', ascii_only=True, max_len=30)}_"
        f"{slugify(title, ascii_only=ascii_slug)}"
    )
    base = Path(output_dir) / channel_slug
    candidate = base / name
    counter = 2
    while candidate.exists():
        candidate = base / f"{name}_{counter}"
        counter += 1
    (candidate / "clips").mkdir(parents=True)
    return candidate


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_transcript(path: Path, transcript: Transcript) -> None:
    write_json(path, transcript.to_dict())


def load_transcript(path: Path) -> Transcript:
    return Transcript.from_dict(read_json(path))


def _word_cues(words, max_words: int = 8, max_chars: int = 42):
    cues = []
    current = []
    for word in words:
        if current:
            pause = word.start - current[-1].end
            joined = " ".join(w.text for w in current + [word])
            if (
                len(current) >= max_words
                or len(joined) > max_chars
                or pause > 0.8
                or current[-1].text.endswith((".", "!", "?", "…"))
            ):
                cues.append(current)
                current = []
        current.append(word)
    if current:
        cues.append(current)
    return cues


def _srt_time(seconds: float) -> str:
    ms = int(round(max(0.0, seconds) * 1000))
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def write_srt(transcript: Transcript, path: Path) -> None:
    lines = []
    for index, cue in enumerate(_word_cues(transcript.words), start=1):
        lines.append(str(index))
        lines.append(f"{_srt_time(cue[0].start)} --> {_srt_time(cue[-1].end)}")
        lines.append(" ".join(w.text for w in cue))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
