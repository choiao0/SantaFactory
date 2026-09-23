# -*- coding: utf-8 -*-
"""프레임 저장의 **포맷 결정** — Isaac 없이 돈다.

    python3 -m pytest path/test_shot_format.py -q

왜
--
`headless_pibt._save_one` 은 `.part` 로 쓰고 `os.replace` 로 옮긴다 (원자적 쓰기,
SIGINT 가 PNG 한가운데를 끊는 것을 막는다). 그런데 PIL 은 **확장자로 포맷을
정한다.** 포맷을 명시하지 않으면 `.part` 에서 죽는다 —

    ValueError: unknown file extension: .part

2026-09-23 `r13peak` 에서 측면이 이것으로 20회 실패하고 0 장이 나왔다. 상단은
뷰포트 경로(`capture_viewport_to_file`)라 안 걸렸고, **리플리케이터 경로만**
걸렸다 — 그래서 상단 11,469장 · 측면 0장 이라는 비대칭이 났다.

`headless_pibt.py` 를 통째로 import 하면 Isaac(omni)이 필요하므로, 같은 규칙을
여기서 따로 검증한다.
"""
import os

import pytest

PIL = pytest.importorskip("PIL.Image", reason="Pillow 없는 환경")
np = pytest.importorskip("numpy")

# `headless_pibt.py` 와 **같은 표**여야 한다.
PIL_FORMAT = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG"}


def fmt_for(ext):
    return PIL_FORMAT.get(ext.lower(), ext.upper())


def test_part_suffix_needs_an_explicit_format(tmp_path):
    """확장자 추론에 맡기면 `.part` 에서 죽는다 — 이 테스트가 그 사고를 고정한다."""
    img = PIL.fromarray(np.zeros((4, 4, 3), dtype=np.uint8))
    with pytest.raises(ValueError):
        img.save(str(tmp_path / "f_000000001.png.part"))


@pytest.mark.parametrize("ext", ["png", "jpg"])
def test_atomic_write_round_trip(ext, tmp_path):
    """포맷을 명시하면 `.part` 로 쓰고 옮기는 것이 성립하고, 찌꺼기가 안 남는다."""
    final = tmp_path / f"f_000012345.{ext}"
    tmp = final.with_suffix(final.suffix + ".part")
    PIL.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(str(tmp), format=fmt_for(ext))
    os.replace(tmp, final)

    assert final.is_file() and final.stat().st_size > 0
    assert not tmp.exists()
    assert PIL.open(str(final)).size == (4, 4)


def test_part_files_are_invisible_to_the_assembly_glob(tmp_path):
    """조립은 `f_*.<ext>` 를 찾는다 (`run_record.sh:518`). 끊겨 남은 `.part` 는
    거기 안 걸려야 한다 — 걸리면 ffmpeg 이 반쪽 파일을 읽는다."""
    import glob
    (tmp_path / "f_000000001.png").write_bytes(b"x")
    (tmp_path / "f_000000002.png.part").write_bytes(b"x")
    assert len(glob.glob(str(tmp_path / "f_*.png"))) == 1
