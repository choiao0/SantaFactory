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
TURN_TICKS = 1      # 물리 팀 실측(2026-09-13) 90° 회전 1.511 s, 전진 1.2 m 2.367 s → 비 0.64 → 1틱 (2보다 1에 가깝다)
FOOTPRINT_MARGIN_M = 0.05  # 회전 마스크 여유 = Isaac 정지 허용 오차 5 cm

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
    (1.739 m) 안이라 닿을 수 있다 → 여유 41 → 200 mm. 코 대각(r+d1+d2)은 여유를 안 올리고 합법쌍만 줄이며, 뒤 대각(r−d1−d2)은
    몸이 실제로 지나는 hard 칸이라 soft 에 넣지 않는다 (물리 팀 2026-09-14: 4칸 합법쌍 302 / 200 mm, hard ∪ soft = 3×3 중 8칸).
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
