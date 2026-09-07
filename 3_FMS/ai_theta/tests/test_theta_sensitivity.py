# -*- coding: utf-8 -*-
# ============================================================
# θ 감도 실험의 판정 로직 검증 (S15P21A106-138)
#
# 판정을 출력에서 분리한 이유가 여기 있다 — 같은 원자료로 "실효 0개"와 "실효 3개"가
# 갈렸던 적이 있어(문서 §1), 기준이 무엇을 신호로 보고 무엇을 잡음으로 보는지
# 고정해 두지 않으면 결론이 조용히 바뀐다.
#
# 실행: python ai_theta/tests/test_theta_sensitivity.py
# ============================================================
import os
import sys
import unittest

_AI_THETA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_AI_THETA, "experiments"), _AI_THETA):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from theta_sensitivity import classify, paired_diffs, verdicts  # noqa: E402


def _case(name, base, per_seed, param="p"):
    """per_seed = {시드: tasks_per_h}. 판정에 필요한 최소 형태만 만든다."""
    full = {s: {"tasks_per_h": v, "lead_mean_s": 0.0} for s, v in per_seed.items()}
    return {"case": name, "base": base, "param": param, "n_ok": len(per_seed),
            "_per_seed": full, "mean_tasks_per_h": sum(per_seed.values()) / len(per_seed)}


class ClassifyTest(unittest.TestCase):
    def test_같은_부호에_폭보다_크면_실효(self):
        # 세 시드 모두 비슷하게 올랐다 — 파라미터가 만든 차이로 본다
        self.assertEqual(classify([49.9, 46.4, 46.7]), ("실효", True))

    def test_부호가_갈리면_잡음(self):
        self.assertEqual(classify([12.0, -8.0, 3.0]), ("잡음", False))

    def test_부호는_같아도_폭이_크면_방향만_일관(self):
        # 평균 10, 폭 18 — 방향은 일정하나 크기를 신뢰할 수 없다
        self.assertEqual(classify([1.0, 19.0, 10.0]), ("방향만 일관", False))

    def test_변화가_전혀_없으면_잡음(self):
        # 구조적 0 (통로 교번 계열). all(d>0) 도 all(d<0) 도 아니다
        self.assertEqual(classify([0.0, 0.0, 0.0]), ("잡음", False))


class PairedDiffsTest(unittest.TestCase):
    def test_같은_시드끼리_뺀다(self):
        by_case = {"neutral": _case("neutral", "neutral", {42: 100.0, 43: 200.0})}
        row = _case("x", "neutral", {42: 110.0, 43: 205.0})
        self.assertEqual(paired_diffs(by_case, row), [10.0, 5.0])

    def test_시드가_어긋나면_겹치는_것만_쓴다(self):
        # 한 시드가 실패한 케이스. 남은 시드로만 짝을 짓는다
        by_case = {"neutral": _case("neutral", "neutral", {42: 100.0, 43: 200.0})}
        row = _case("x", "neutral", {43: 210.0})
        self.assertEqual(paired_diffs(by_case, row), [10.0])

    def test_겹치는_시드가_없으면_None(self):
        by_case = {"neutral": _case("neutral", "neutral", {42: 100.0})}
        row = _case("x", "neutral", {99: 110.0})
        self.assertIsNone(paired_diffs(by_case, row))


class VerdictsTest(unittest.TestCase):
    def setUp(self):
        self.rows = [
            _case("neutral", "neutral", {42: 100.0, 43: 100.0, 44: 100.0}),
            _case("big", "neutral", {42: 120.0, 43: 121.0, 44: 119.0}, param="a"),
            _case("small", "neutral", {42: 101.0, 43: 99.0, 44: 100.5}, param="b"),
        ]

    def test_중립은_결과에_없다(self):
        self.assertNotIn("neutral", [v["case"] for v in verdicts(self.rows)])

    def test_영향_큰_순으로_정렬된다(self):
        self.assertEqual([v["case"] for v in verdicts(self.rows)], ["big", "small"])

    def test_실효만_signal_이_참(self):
        got = {v["case"]: v["signal"] for v in verdicts(self.rows)}
        self.assertEqual(got, {"big": True, "small": False})

    def test_범주형은_자기_베이스와_비교한다(self):
        # loop_dir 은 중립이 아니라 loop_gain=3 을 깐 베이스와 비교해야 한다.
        # 중립과 비교하면 +50 이지만 자기 베이스와는 -10 이다.
        rows = self.rows + [
            _case("loop_gain=3", "neutral", {42: 160.0, 43: 160.0, 44: 160.0}),
            _case("loop_dir=1", "loop_gain=3", {42: 150.0, 43: 150.0, 44: 150.0}),
        ]
        got = {v["case"]: v["mean_d"] for v in verdicts(rows)}
        self.assertAlmostEqual(got["loop_dir=1"], -10.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
