from __future__ import annotations

from pathlib import Path

from PIL import Image

from csrsb.recorders.desktop.capture import average_hash, hamming_distance


def _solid(path: Path, color: tuple[int, int, int], size: int = 32) -> None:
    Image.new("RGB", (size, size), color).save(path)


def test_identical_images_have_zero_hamming(tmp_path: Path) -> None:
    a, b = tmp_path / "a.png", tmp_path / "b.png"
    _solid(a, (255, 255, 255))
    _solid(b, (255, 255, 255))
    ha, hb = average_hash(a), average_hash(b)
    assert ha is not None and hb is not None
    assert hamming_distance(ha, hb) == 0


def test_solid_color_difference_falls_below_threshold(tmp_path: Path) -> None:
    # All-white vs all-black both have the same flat aHash (every pixel is at
    # the mean), so the heuristic deliberately ignores them. This documents
    # that — major changes only show up when the *spatial* distribution shifts.
    white = tmp_path / "white.png"
    black = tmp_path / "black.png"
    _solid(white, (255, 255, 255))
    _solid(black, (0, 0, 0))
    hw, hb = average_hash(white), average_hash(black)
    assert hw is not None and hb is not None
    assert hamming_distance(hw, hb) < 12


def test_layout_change_exceeds_threshold(tmp_path: Path) -> None:
    """A genuinely different layout (half black + half white) shifts most bits
    relative to a uniform image — that's the case the heuristic targets.
    """
    uniform = tmp_path / "uniform.png"
    half = tmp_path / "half.png"
    _solid(uniform, (200, 200, 200))
    img = Image.new("RGB", (32, 32), (0, 0, 0))
    for x in range(16, 32):
        for y in range(0, 32):
            img.putpixel((x, y), (255, 255, 255))
    img.save(half)
    hu, hh = average_hash(uniform), average_hash(half)
    assert hu is not None and hh is not None
    assert hamming_distance(hu, hh) >= 12
