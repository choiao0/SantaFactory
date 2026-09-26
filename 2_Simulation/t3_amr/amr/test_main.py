# -*- coding: utf-8 -*-
"""amr/main.py 씬 빌드 판정 (-280).

씬 빌드는 USD 를 저장한 **뒤** Kit 종료 단계에서 코드 1 로 죽을 수 있다(carb "Destroying busy TaskGroup!").
씬 파일이 이번 빌드에서 새로 저장됐으면 계속 가고, 아니면 지금처럼 멈춘다.

    python -m pytest t3_amr/amr/test_main.py -q        # 기본 수집(edge/tests) 밖 — 직접 지목
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from amr import main as M                                     # noqa: E402


class TestSceneSaved:
    def test_missing_file_is_not_saved(self, tmp_path):
        assert not M.scene_saved(str(tmp_path / "pibt10.usd"), since=time.time())

    def test_empty_file_is_not_saved(self, tmp_path):
        usd = tmp_path / "pibt10.usd"
        since = time.time()
        usd.write_bytes(b"")
        assert not M.scene_saved(str(usd), since)

    def test_file_from_an_earlier_build_is_not_saved(self, tmp_path):
        usd = tmp_path / "pibt10.usd"
        usd.write_bytes(b"#usda 1.0\n")
        old = time.time() - 60
        os.utime(usd, (old, old))
        assert not M.scene_saved(str(usd), since=time.time())

    def test_file_written_by_this_build_is_saved(self, tmp_path):
        usd = tmp_path / "pibt10.usd"
        since = time.time()
        usd.write_bytes(b"#usda 1.0\n")
        assert M.scene_saved(str(usd), since)


class TestBuildScene:
    def test_clean_exit_passes(self, tmp_path):
        usd = tmp_path / "pibt10.usd"
        M.build_scene(f"printf x > '{usd}'", str(tmp_path), str(usd))
        assert usd.read_bytes() == b"x"

    def test_crash_after_saving_keeps_going(self, tmp_path, capsys):
        """est_21 10대(09-27 00:59): 저장 · DONE 뒤 Kit 종료 assert 로 코드 1."""
        usd = tmp_path / "pibt10.usd"
        M.build_scene(f"printf x > '{usd}'; exit 1", str(tmp_path), str(usd))
        assert "코드 1" in capsys.readouterr().out

    def test_crash_before_saving_stops(self, tmp_path):
        usd = tmp_path / "pibt10.usd"
        with pytest.raises(SystemExit, match="씬 빌드 실패"):
            M.build_scene("exit 1", str(tmp_path), str(usd))

    def test_crash_with_only_an_old_scene_stops(self, tmp_path):
        """지난 빌드의 USD 가 남아 있어도 이번 빌드가 못 썼으면 멈춘다 — 옛 궤적으로 주행하면 안 된다."""
        usd = tmp_path / "pibt10.usd"
        usd.write_bytes(b"#usda 1.0\n")
        old = time.time() - 60
        os.utime(usd, (old, old))
        with pytest.raises(SystemExit, match="씬 빌드 실패"):
            M.build_scene("exit 1", str(tmp_path), str(usd))
