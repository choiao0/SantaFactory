# -*- coding: utf-8 -*-
import math
import numpy as np

DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1)]  # 0=N 1=E 2=S 3=W

# ============================================================
# 헤딩 모델 — 상태 (r, c, h), 2칸 점유, 제자리 회전 액션, 스윙 칸 예약
# (설계: docs/이동계층_PIBT.md#상태와-2칸-점유)
#
#   pos(s)  = (r, c)              앞축(구동축)이 있는 칸 — 칸 중심에 정렬
#   rear(s) = (r, c) - DIRS[h]    뒤 차체(≈1.24m)가 있는 칸
#   occupied(s) = {pos, rear}     로봇 1대 = 2칸
#   valid(s)  ⇔ pos, rear 모두 free (벽에 등을 대고 설 수 없다)
#   액션: 전진(edge_cost) / 좌·우 90° 회전(turn_cost, 스윙 칸 필요) / 대기
#         / 후진 1칸 (edge_cost[pos, 반대방향] × REVERSE_FACTOR)
#   swing(h→h') = {rear(h), rear(h'), 그 사이 대각 칸}          — 몸처럼 예약(hard)
#   front(h→h') = {front(h), front(h')}  (configure(front_swing=True), -203) — soft 칸: 다른 로봇의
#                 구동축(pos)이 거기 있거나 이번 틱에 들어오면 회전 금지. 뒤 칸만 걸쳐 있으면 허용.
#
#   회전 발자국 (S15P21A106-203, docs/2026-09-13_S15P21A106-203_회전발자국마스크_설계.md, 앞스윙_교착_검토.md):
#   앞 모서리 반경 hypot(앞, 반폭) = hypot(0.39, 0.40) = 0.56 > 0.5 라 회전 중 코가 앞 2칸에
#   0.06 m(여유 포함 0.13 m) 들어간다. 랙·벽은 0.1 m 지도로 만든 정적 마스크(map_loader.turn_mask)로,
#   로봇끼리는 앞 칸의 **축** 유무로 판정한다 — 축이 앞 칸에 있으면 상대 코(0.61)·옆면(0.60)이 스윕(0.63) 안,
#   뒤 칸만 걸치면 상대 뒤끝은 스윕에서 0.26 m 밖. 칸 단위로 몸 전체를 막으면(5칸 예약) 폭 1 통로·
#   열 대기 줄에서 아무도 회전을 못 해 교착한다(2026-09-13 실측).
#   configure() 를 안 부르면 예전 그대로(legacy: 마스크 없음·front 없음, 계약 v3.3 비트 동일).
#
#   후진이 필요한 이유 (2026-09-02 실측): 벽에 붙은 레인(예: 충전기 열 c=108,
#   동쪽 c=109 벽)에서는 벽 쪽으로 뒤 칸이 필요한 방향으로 회전할 수 없어
#   로봇이 레인에 갇힌다. 실제 로봇은 후진 후 회전(3점 회전)으로 빠져나온다.
#
# 위의 칸 모델(dist_map/step/run)은 그대로 두고(v1compat·B-1e 보존), 헤딩
# 모델은 *_h 함수로 병행 제공한다. sim_v2는 --heading 플래그로 선택.
# ============================================================
REAR_CELLS = 1      # 기종 카드(물리 팀 2026-09-13): 구동축 뒤 차체 1.11 m → 뒤 칸 1개

# ------------------------------------------------------------
# 전진·회전 틱 (S15P21A106-194, 계약 v3.6)
#
# 물리 팀 실측(2026-09-13): 90° 회전 1.511 s, 전진 1.2 m 2.367 s.
# v_max 0.90 m/s · ω_max 1.80 rad/s 로 역산하면 a = 0.871 m/s² · α = 2.820 rad/s².
# 각가속은 이미 장비 최대라 **회전 1.511 s 가 하한**이다 — 선가속을 올려도 안 줄어든다.
#
# 전진 1칸에 걸리는 시간은 **직진 런 안에서 서느냐**에 달렸다.
#
#   매 칸 정지     칸마다 가속·감속   →  2.145 s/칸  →  비율 0.705
#   연속 주행      런당 가속·감속 1번 →  1.195 s/칸  →  비율 1.264  →  4 : 5   ← 채택
#
# 물리 실행기가 연속 주행(ADG 블렌딩)으로 가므로 아래쪽을 쓴다. 그게 선가속을 올리는 것보다
# 크다 — a 를 몇 배로 올려도 매 칸 정지면 회전 하한에 막히는데, 연속 주행은 a 를 그대로 두고도
# 칸당 2.145 → 1.195 s 가 된다.
#
# 1.195 s/칸 은 가정이 아니라 **우리 조건에서 잰 값**이다 (20·24대 · 250건 · 900건/h ·
# 탐색 시드 3개 = 직진 런 27,925개 · 277,647칸). 런마다 ramp 시간을 구해 전부 더한 뒤
# 칸 수로 나눴다 — 평균 런 길이를 먼저 내고 ramp 를 적용하면 안 된다. 1칸 런이 개수의
# 28 % 라 그 비싼 칸값이 평균에 묻히기 때문이다.
#
# -203 이 같은 실측에서 TURN_TICKS=1 을 유지한 것은 **전진이 1틱일 때** 0.64 를 정수로
# 표현할 방법이 없어서다. 전진을 4틱으로 쪼개면 그 제약이 없어진다 — 층이 다른 판단이고
# 모순이 아니다.
#
# 4 : 5 = 1.250 은 오차 −1.1 % 다. 런 길이가 6~20칸으로 흔들리면 목표 비율 자체가 8 %
# 움직이므로 그보다 정밀할 이유가 없고, 4 는 6 h 가 72 k 틱이라 계약 상한 20만에 여유가 크다.
# 실측: 비율 1.25 / 1.20 / 1.167 에서 최적 θ 1위가 안 바뀐다. 0.75↔1.00↔1.14 에서는 바뀐다.
# ------------------------------------------------------------
MOVE_TICKS = 4      # 전진·후진 1칸에 걸리는 틱 (실행)
TURN_TICKS = 5      # 90° 제자리 회전에 걸리는 틱 (실행)

# 거리장 가중은 **틱 수가 아니라 전진 1칸 대비 배율**이다. edge_cost 기준이 1.0 이고
# clamp 가 [COST_MIN, COST_MAX] = [0.5, 5.0] 이라, 회전에 틱 수를 그대로 넣으면 회전이
# 전진의 TURN_TICKS 배가 된다. MOVE_TICKS 로 나눠 환율을 맞춘다.
TURN_COST = TURN_TICKS / MOVE_TICKS     # 1.25 — 회전이 전진보다 비싸다

FOOTPRINT_MARGIN_M = 0.05  # 회전 마스크 여유 = Isaac 정지 허용 오차 5 cm (-203)

# 회전 발자국 설정 (-203). 기본 = legacy.
# ponytail: 모듈 전역 설정 — 프로세스당 커널 1개 전제(워커·A트랙은 서브프로세스). 한 프로세스에
# 치수가 다른 커널 2개가 필요해지면 turn_ok/swing_cells 인자로 승격.
_TURN_MASK = None     # bool[H, W, 4, 4] — [r, c, h, h2] = 회전 스윕이 장애물과 안 겹침. None = 마스크 없음
_FRONT_SWING = False  # 회전 시 앞 칸(front(h), front(h2))을 soft 칸으로 검사
_FRONT_DIAG = False   # soft 에 섞임 대각 2칸(mA, mB)도 포함 = 4칸 (-79, 물리 팀 2026-09-14 답신: 뒤 대각은 몸 칸(hard), 코 대각은 여유 무관)


def configure(turn_mask=None, front_swing=False, front_diag=False, robot_dims=None, pitch=1.0):
    """회전 발자국 설정. FmsKernel.__init__ 가 Replanner/HGraph 를 만들기 **전에** 부른다.
    front_swing: 앞 2칸(f0, f1) soft. front_diag: 섞임 대각 2칸(mA, mB)도 soft = 4칸(`--footprint=exact,front`; 2칸은 `exact,front_2cell`).
    robot_dims=(앞, 뒤, 폭) 를 주면 pitch 게이팅을 여기서 한다: 코 반경 hypot(앞, 폭/2) × 2 ≤ pitch 면 코가 칸을 안 벗어나
    규칙이 필요 없다(∅) — 계획기와 실행층(ADG)이 같은 판정을 보게 규칙 함수 쪽에 둔다(물리 팀 2026-09-14 §1)."""
    global _TURN_MASK, _FRONT_SWING, _FRONT_DIAG
    _TURN_MASK = None if turn_mask is None else np.asarray(turn_mask, dtype=bool)
    if front_swing and robot_dims is not None:
        front_swing = front_needed(robot_dims, pitch)
    _FRONT_SWING = bool(front_swing)
    _FRONT_DIAG = bool(front_swing and front_diag)


def front_needed(robot_dims, pitch=1.0):
    """코 모서리 반경 hypot(앞, 폭/2) 가 반 칸(pitch/2) 을 넘으면 회전 중 코가 앞 칸에 들어간다 → soft 규칙 필요.
    (0.39, 1.11, 0.80): 0.559 > 0.5 → True. pitch 1.2 면 0.559 < 0.6 → False (규칙 불필요)."""
    front, _, width = robot_dims
    return math.hypot(front, width / 2) > pitch / 2


def reset():
    """legacy 로 되돌림 (테스트용)."""
    configure()


def turn_mask():
    return _TURN_MASK


def front_swing_on():
    return _FRONT_SWING


def front_diag_on():
    return _FRONT_DIAG
REVERSE_FACTOR = 3.0  # 후진 1칸 비용 배율 — 느리고 시야 없는 동작이라 마지막 수단 (3점 회전용)
REV_TICKS = round(MOVE_TICKS * REVERSE_FACTOR)   # 후진 1칸 실행 틱 (계약 v3.15, -250). 12틱.
# v3.14 까지 후진이 전진과 같은 MOVE_TICKS 였다 — REVERSE_FACTOR 가 **계획 비용에만** 걸려 있었다.
# 물리 팀 녹화 실측(t3-31 §2): 전진 0.818 · 후진 0.260 m/s = 3.11~3.14배. speed 0.9 에서
# 12틱 = 3.3333 s/칸 = **0.300 m/s** 로 그쪽 후진 p99 와 같다(후진 상한 0.3 = 전진 0.9 의 1/3).
# 값을 여기 한 곳에만 둔다 — KernelConfig 와 sim_v2_tasks 가 이 이름을 쓴다.

def rear_cell(r, c, h):
    return (r - DIRS[h][0], c - DIRS[h][1])


def occupied(s):
    r, c, h = s
    return ((r, c), rear_cell(r, c, h))


def _inb(free, rc):
    H, W = free.shape
    return 0 <= rc[0] < H and 0 <= rc[1] < W and free[rc]


def valid_state(free, s):
    r, c, h = s
    return _inb(free, (r, c)) and _inb(free, rear_cell(r, c, h))


def swing_cells(r, c, h, h2):
    """h→h2(90°) 회전 중 뒤 차체가 쓸고 가는 칸 3개(옛 뒤·새 뒤·대각) — 몸처럼 예약(hard)."""
    d1, d2 = DIRS[h], DIRS[h2]
    return {rear_cell(r, c, h), rear_cell(r, c, h2),
            (r - d1[0] - d2[0], c - d1[1] - d2[1])}


def front_cells(r, c, h, h2):
    """h→h2 회전 중 코가 스치는 앞 2칸(옛·새 헤딩 앞) — soft 칸(축만 금지). front_swing 설정이 아니면 빈 집합.
    front_diag 면 섞임 대각 2칸 mA=(r+d1−d2), mB=(r−d1+d2) 도 (4칸): 상대 축이 대각(1.414 m)에 있어도 내 코 반경 + 상대 뒤 반경
    (1.739 m) 안이라 닿을 수 있다. 코 대각(r+d1+d2)은 여유를 안 올리고 합법쌍만 줄이며, 뒤 대각(r−d1−d2)은
    몸이 실제로 지나는 hard 칸이라 soft 에 넣지 않는다.
    **정정(물리 팀 답신 11, 2026-09-16):** 09-14 에 받았던 "4칸 = 최소 여유 200 mm·합법쌍 302" 는 soft 를 hard 로 계산한 값이었다. soft(축만 금지)
    로 다시 재면 앞2·4칸 모두 최소 여유 41.4 mm(합법쌍 314·304), 200 mm 는 5칸 hard(286)라야 나온다. 4칸의 근거는 여유가 아니라
    귀측 ADG 순환 방지(규칙 끔 12/12 순환 → 켬 0/12)다. 이 모듈의 soft 4칸 정의는 그대로다.
    의미는 **더하기**: hard(축·뒤·스윙 3칸)는 그대로 두고 soft 는 "축만 금지" 추가 제약. 스윕 밖 soft 칸도 순수 추가 제약."""
    if not _FRONT_SWING:
        return set()
    d1, d2 = DIRS[h], DIRS[h2]
    cells = {(r + d1[0], c + d1[1]), (r + d2[0], c + d2[1])}
    if _FRONT_DIAG:
        cells |= {(r + d1[0] - d2[0], c + d1[1] - d2[1]), (r - d1[0] + d2[0], c - d1[1] + d2[1])}
    return cells


def turn_ok(free, r, c, h, h2):
    """(r,c)에서 h→h2 회전 가능: 양쪽 상태 valid + 스윙 대각 칸 free + (설정 시) 정적 마스크 True."""
    if not (valid_state(free, (r, c, h)) and valid_state(free, (r, c, h2))):
        return False
    d1, d2 = DIRS[h], DIRS[h2]
    if not _inb(free, (r - d1[0] - d2[0], c - d1[1] - d2[1])):
        return False
    return _TURN_MASK is None or bool(_TURN_MASK[r, c, h, h2])


_stay_cache_h = {}


def stay_map_h(free, s):
    """서비스 중·회전 중 고정용: 상태 s만 0, 나머지 -1 → 후보가 대기 하나뿐.
    (읽기 전용 캐시 — 틱마다 (H,W,4) 배열을 새로 만들면 헤딩 모델이 10배 느려진다.)"""
    key = (free.shape, s)
    m = _stay_cache_h.get(key)
    if m is None:
        if len(_stay_cache_h) > 4096:
            _stay_cache_h.clear()
        m = np.full(free.shape + (4,), -1.0, dtype=np.float64)
        m[s] = 0.0
        _stay_cache_h[key] = m
    return m
