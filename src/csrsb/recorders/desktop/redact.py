"""OCR-based screenshot redaction (Phase 3, opt-in).

The desktop recorder has no DOM, so we can't ask "is the focused element a
password field". Instead we OCR each screenshot, look for likely-secret
substrings (high-entropy tokens, well-known prefixes like ``sk-``, ``ghp_``),
and blur the bounding boxes those words occupy before the PNG is saved.

Both ``pytesseract`` and the ``tesseract`` binary need to be installed for
this to do anything. If either is missing, the function returns the image
unchanged and logs nothing — the user gets the regex/entropy scrub in
``translator/redact.py`` plus the post-LLM secret check, but the screenshot
text remains intact.

Usage from ``session.py``:

    if config.ocr_redact:
        redact_screenshot_file(out)  # mutates the PNG in place

We deliberately keep this out of ``capture.py`` so the test surface stays
small — capture is pure I/O, redaction is policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

# Same regex set as ``translator/redact.py`` so the two layers agree on what
# constitutes a secret. Kept inline rather than imported because the entropy
# check below is desktop-specific (post-OCR, so we know the token boundaries).
_SECRET_PATTERNS = [
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{32,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
]
_HIGH_ENTROPY_MIN_LEN = 20
_HIGH_ENTROPY_THRESHOLD = 3.5


@dataclass
class _OCRWord:
    text: str
    x: int
    y: int
    w: int
    h: int


def redact_screenshot_file(path: Path) -> int:
    """Blur secret-shaped regions in the PNG at ``path``. Returns the count
    of regions blurred (0 if OCR is unavailable or nothing matched).

    Mutates the file in place — caller has already saved it.
    """
    words = _ocr_words(path)
    if not words:
        return 0
    bad = [w for w in words if _is_secret_shaped(w.text)]
    if not bad:
        return 0
    return _blur_regions(path, bad)


def _ocr_words(path: Path) -> list[_OCRWord]:
    try:
        import pytesseract  # type: ignore[import-untyped]
        from PIL import Image
    except ImportError:
        return []
    try:
        with Image.open(path) as img:
            data = pytesseract.image_to_data(
                img, output_type=pytesseract.Output.DICT
            )
    except Exception:
        # tesseract binary missing, image broken, etc. — fail open.
        return []
    out: list[_OCRWord] = []
    n = len(data.get("text", []))
    for i in range(n):
        text = data["text"][i].strip()
        if not text:
            continue
        out.append(
            _OCRWord(
                text=text,
                x=int(data["left"][i]),
                y=int(data["top"][i]),
                w=int(data["width"][i]),
                h=int(data["height"][i]),
            )
        )
    return out


def _is_secret_shaped(text: str) -> bool:
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return True
    if len(text) >= _HIGH_ENTROPY_MIN_LEN and _shannon_entropy(text) >= _HIGH_ENTROPY_THRESHOLD:
        has_alpha = any(c.isalpha() for c in text)
        has_digit = any(c.isdigit() for c in text)
        if has_alpha and has_digit:
            return True
    return False


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    counts: dict[str, int] = {}
    for ch in text:
        counts[ch] = counts.get(ch, 0) + 1
    import math

    total = len(text)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def _blur_regions(path: Path, regions: Iterable[_OCRWord]) -> int:
    try:
        from PIL import Image, ImageFilter
    except ImportError:
        return 0
    with Image.open(path) as img:
        rgba = img.convert("RGBA")
        # Pad each box by 4 pixels so anti-aliased letter edges aren't visible.
        count = 0
        for region in regions:
            box = (
                max(region.x - 4, 0),
                max(region.y - 4, 0),
                min(region.x + region.w + 4, rgba.width),
                min(region.y + region.h + 4, rgba.height),
            )
            if box[2] <= box[0] or box[3] <= box[1]:
                continue
            cropped = rgba.crop(box).filter(ImageFilter.GaussianBlur(radius=8))
            rgba.paste(cropped, box)
            count += 1
        rgba.convert("RGB").save(path, format="PNG", optimize=True)
        return count
