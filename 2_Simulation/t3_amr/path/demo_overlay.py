# -*- coding: utf-8 -*-
"""1인칭 영상 위의 글씨 — 「이 AMR 이 지금 무슨 주문을 어디서 어디로 나르나」 (S15P21A106-244).

영상만 봐서는 AMR 이 **주문을 처리하는 중**인지 그냥 돌아다니는지 알 수 없다. DES 피크 구간(slice format 1)에는
태스크마다 출발지·목적지·배정·완료 틱이 있고 로봇마다 매 틱 자리가 있으니, 로봇별 **운행**(픽업 → 적재 → 운반 → 하역)을
짤 수 있다. 태스크에는 로봇 번호가 없어 **완료 틱에 목적지 옆에 선 로봇**으로 짝짓는다(여럿이면 그 사이 출발지에 들렀던 로봇).

★ 글씨의 단계는 **DES 시각이 아니라 그 로봇이 Isaac 에서 실제로 어느 동작까지 왔나**로 정한다. 물리는 DES 보다 늦으므로
  시각으로 고르면 화면과 글씨가 어긋난다. 실행기의 동작마다 DES 계획 틱(`Action.tick`, 구간 시작 = 0)이 붙어 있어,
  「지금 수행 중인 동작의 계획 틱」을 넘기면 그 순간 DES 계획상의 단계가 나온다.

Isaac 이 없어도 도는 순수 함수다(`path/test_demo_overlay.py`). 그리기(`draw`)만 PIL 을 쓴다.
"""
import json
import re
from dataclasses import dataclass

_NAME_RE = re.compile(r"^([a-z_]+)\[(\d+)\]$")
_NAMES = {   # 스테이션 이름 → (한국어, 영어). 번호는 사람이 읽게 1부터
    "aisle_buf": ("통로 버퍼", "Aisle buffer"),
    "packing": ("포장대", "Packing"),
    "charger": ("충전소", "Charger"),
    "handoff": ("인계 지점", "Handoff"),
    "inbound": ("입고장", "Inbound"),
    "receiving": ("입고장", "Receiving"),
    "dock": ("도크", "Dock"),
}
_PHASES = {  # 단계 → (한국어, 영어). {frm}·{to} 는 운행의 출발지·목적지
    "to_pick": ("픽업하러 이동 · {frm}", "Heading to pick-up · {frm}"),
    "loading": ("토트 적재 중 · {frm}", "Loading totes · {frm}"),
    "carrying": ("운반 중 → {to}", "Carrying -> {to}"),
    "unloading": ("하역 중 · {to}", "Unloading · {to}"),
    "idle": ("다음 주문 대기", "Waiting for next order"),
}
_PHASE_SHORT = {  # 천장 영상 범례
    "to_pick": ("픽업 이동", "To pick-up"),
    "loading": ("적재", "Loading"),
    "carrying": ("운반", "Carrying"),
    "unloading": ("하역", "Unloading"),
    "idle": ("대기", "Idle"),
}
PHASE_RGB = {"to_pick": (80, 170, 255), "loading": (255, 170, 60), "carrying": (90, 220, 120),
             "unloading": (255, 120, 90), "idle": (170, 170, 170)}


def label(name, lang="ko"):
    """`aisle_buf[4]` → `통로 버퍼 5`. 모르는 이름은 그대로."""
    m = _NAME_RE.match(str(name or ""))
    if not m or m.group(1) not in _NAMES:
        return str(name)
    ko, en = _NAMES[m.group(1)]
    return f"{ko if lang == 'ko' else en} {int(m.group(2)) + 1}"


def _cell(x, y):
    """export_isaac._xy 의 역: x = (c+0.5)·1.0 − 0.4, y = (r+0.5)·1.0."""
    return int(round(y - 0.5)), int(round(x + 0.4 - 0.5))


def _xy(cell):
    """export_isaac._xy — 칸 (r, c) → 월드 (x, y)."""
    r, c = cell
    return round(c + 0.1, 2), round(r + 0.5, 2)


def _cheb(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


@dataclass
class Trip:
    robot: str
    frm: tuple
    to: tuple
    frm_label: str
    to_label: str
    assigned_k: int
    pick_arrive_k: int | None       # None = 구간 전에 이미 실었다
    pick_leave_k: int | None
    drop_arrive_k: int
    done_k: int
    totes: int
    orders: int


@dataclass
class Phase:
    key: str
    text: str
    trip: Trip | None


@dataclass
class Mark:
    """천장 영상의 로봇 하나 — 화면 좌표 (u, v), 차 앞 방향 (hu, hv) [px], 단계, 1인칭 대상 여부."""
    num: int
    u: float
    v: float
    hu: float
    hv: float
    key: str
    follow: bool


class Timeline:
    """로봇별 운행 목록. 틱은 모두 **구간 시작 = 0** 기준(실행기 `Action.tick` 과 같다)."""

    def __init__(self, trips, window, lang="ko", extent=None, stations=None):
        self.trips = trips                  # {로봇: [Trip, ...]} 배정 순
        self.warmup_k, self.window_k, self.window_s, self.dt = window
        self.lang = lang
        self.extent = extent                # 로봇이 다닌 범위 (x0, x1, y0, y1) [m] — 천장 카메라 맞춤
        self.stations = stations or {}      # {포장대 이름: (x, y)} — 천장 영상에 적는다

    @classmethod
    def from_file(cls, path, lang="ko"):
        with open(path, encoding="utf-8") as f:
            return cls.from_slice(json.load(f), lang)

    @classmethod
    def from_slice(cls, doc, lang="ko"):
        dt = float(doc["dt_s"])
        sl = doc.get("slice") or {}
        k_start = int(round(float(sl.get("t_start_s", 0.0)) / dt))
        pos = {rid: {int(round(float(t) / dt)) - k_start: _cell(x, y) for t, x, y in rows}
               for rid, rows in doc["robots"].items()}
        groups = {}
        for task in doc.get("tasks") or []:
            if task.get("completed") is None or task.get("assigned") is None:
                continue
            a_k, d_k = int(task["assigned"]) - k_start, int(task["completed"]) - k_start
            frm, to = tuple(task["frm"]), tuple(task["to"])
            rid = _who(pos, frm, to, a_k, d_k)
            if rid is None:
                continue
            g = groups.setdefault((rid, d_k, to), {"tasks": [], "frm": frm, "assigned": a_k,
                                                   "frm_name": task.get("frm_name"), "to_name": task.get("to_name")})
            g["tasks"].append(task)
            g["assigned"] = min(g["assigned"], a_k)
        trips = {}
        for (rid, d_k, to), g in groups.items():
            trips.setdefault(rid, []).append(_trip(rid, pos[rid], g, to, d_k, lang))
        for v in trips.values():
            v.sort(key=lambda t: (t.assigned_k, t.done_k))
        warmup_s, window_s = float(sl.get("warmup_s", 0.0)), float(sl.get("window_s", 0.0))
        window = (int(round(warmup_s / dt)), int(round(window_s / dt)), window_s, dt)
        xs = [float(x) for rows in doc["robots"].values() for _, x, _ in rows]
        ys = [float(y) for rows in doc["robots"].values() for _, _, y in rows]
        extent = (min(xs), max(xs), min(ys), max(ys)) if xs else None
        stations = {label(t["to_name"], lang): _xy(t["to"]) for t in doc.get("tasks") or []
                    if str(t.get("to_name", "")).startswith("packing[")}
        return cls(trips, window, lang, extent, stations)

    # ── 조회 ──────────────────────────────────────────────────────────────
    def phase(self, rid, k):
        """계획 틱 k 에서 그 로봇의 단계."""
        cur = None
        for t in self.trips.get(str(rid), []):
            if t.assigned_k <= k <= t.done_k:
                cur = t
        if cur is None:
            return Phase("idle", self._phase_text("idle", None), None)
        if cur.pick_arrive_k is None:
            key = "carrying" if k < cur.drop_arrive_k else "unloading"
        elif k < cur.pick_arrive_k:
            key = "to_pick"
        elif k < cur.pick_leave_k:
            key = "loading"
        elif k < cur.drop_arrive_k:
            key = "carrying"
        else:
            key = "unloading"
        return Phase(key, self._phase_text(key, cur), cur)

    def done(self, rid, k):
        """창 안에서 틱 k 까지 끝낸 (운행 수, 토트 수)."""
        fin = [t for t in self.trips.get(str(rid), []) if self.warmup_k <= t.done_k <= k]
        return len(fin), sum(t.totes for t in fin)

    def busiest(self):
        """창 안에서 운행을 가장 많이 끝내는 로봇(같으면 토트가 많은 쪽, 그다음 번호가 작은 쪽). 없으면 None."""
        end = self.warmup_k + self.window_k
        score = {rid: (sum(1 for t in v if self.warmup_k <= t.done_k <= end),
                       sum(t.totes for t in v if self.warmup_k <= t.done_k <= end))
                 for rid, v in self.trips.items()}
        if not score:
            return None
        return min(score, key=lambda r: (-score[r][0], -score[r][1], int(r) if str(r).isdigit() else 0))

    def lines(self, rid, des_k, window_clock_s):
        """(윗줄, 운행 줄, 큰 단계 글씨, 실적) — 영상에 그대로 쓴다. window_clock_s 가 None 이면 워밍업."""
        ko = self.lang == "ko"
        n = int(rid) + 1 if str(rid).isdigit() else rid
        head = f"AMR {n} · " + ("DES 피크 구간 물리 재현" if ko else "DES peak replay (physics)")
        if window_clock_s is None:
            head += "   " + ("준비 중" if ko else "warming up")
        else:
            clock = f"{_mmss(window_clock_s)} / {_mmss(self.window_s)}"
            head += "   " + (f"창 {clock}" if ko else f"window {clock}")
        ph = self.phase(rid, des_k)
        t = ph.trip
        if t is None:
            sub = ""
        elif ko:
            sub = f"주문 {t.orders}건 · 토트 {t.totes}개   {t.frm_label} → {t.to_label}"
        else:
            sub = f"Orders {t.orders} · Totes {t.totes}   {t.frm_label} -> {t.to_label}"
        trips, totes = self.done(rid, des_k)
        right = (f"완료 운행 {trips}회 · 토트 {totes}개" if ko else f"Trips done {trips} · Totes {totes}")
        return head, sub, ph.text, right

    def top_lines(self, ks, window_clock_s, n_robots):
        """천장 영상의 (윗줄, 오른쪽 아래 실적). ks = {로봇: 그 로봇의 계획 틱} — 실적은 로봇마다 제 틱까지 합한다."""
        ko = self.lang == "ko"
        head = (f"DES 피크 구간 물리 재현 · AMR {n_robots}대" if ko
                else f"DES peak replay (physics) · {n_robots} AMRs")
        if window_clock_s is None:
            head += "   " + ("준비 중" if ko else "warming up")
        else:
            clock = f"{_mmss(window_clock_s)} / {_mmss(self.window_s)}"
            head += "   " + (f"창 {clock}" if ko else f"window {clock}")
        done = [self.done(rid, k) for rid, k in ks.items()]
        trips, totes = sum(d[0] for d in done), sum(d[1] for d in done)
        right = (f"완료 운행 {trips}회 · 토트 {totes}개" if ko else f"Trips done {trips} · Totes {totes}")
        return head, right

    def _phase_text(self, key, trip):
        ko, en = _PHASES[key]
        tpl = ko if self.lang == "ko" else en
        return tpl.format(frm=trip.frm_label if trip else "", to=trip.to_label if trip else "")


def plan_tick(pending_tick, clock_s, tick_s):
    """글씨의 단계를 정할 계획 틱.

    궤적 재생은 동작마다 제 계획 틱을 릴리스 바닥으로 박는다(`fms_traj._stamp_schedule`) — 로봇은 DES 보다
    **앞서지 못하고 늦을 수만** 있다. 그래서
      · 다음 동작이 아직 안 풀렸다(시계 < 계획) = 계획대로 서 있다(적재·하역·대기) → 시계 틱
      · 시계는 넘었는데 그 동작을 아직 붙잡고 있다 = 밀렸다 → 그 동작의 계획 틱
    둘 다 `min` 하나로 나온다. 동작이 다 끝났으면 시계 틱.
    """
    clock_k = int(float(clock_s) / float(tick_s))
    return clock_k if pending_tick is None else min(int(pending_tick), clock_k)


def _mmss(s):
    s = max(0, int(s))
    return f"{s // 60:02d}:{s % 60:02d}"


def _who(pos, frm, to, a_k, d_k):
    """완료 틱에 목적지 옆(체비쇼프 1칸)에 선 로봇. 여럿이면 배정~완료 사이 출발지에 들른 로봇, 그다음 목적지에 정확히 선 로봇."""
    near = [rid for rid, p in pos.items() if d_k in p and _cheb(p[d_k], to) <= 1]
    if len(near) <= 1:
        return near[0] if near else None
    visited = [rid for rid in near if any(pos[rid].get(k) == frm for k in range(a_k, d_k + 1))]
    if len(visited) == 1:
        return visited[0]
    pool = visited or near
    exact = [rid for rid in pool if pos[rid][d_k] == to]
    return (exact or pool)[0]


def _trip(rid, p, g, to, d_k, lang):
    frm, a_k = g["frm"], g["assigned"]
    ks = [k for k in sorted(p) if a_k <= k <= d_k]
    pick_arrive = next((k for k in ks if p[k] == frm), None)
    pick_leave = None
    if pick_arrive is not None:
        pick_leave = next((k for k in ks if k > pick_arrive and p[k] != frm), d_k)
    after = pick_leave if pick_leave is not None else a_k
    drop_arrive = next((k for k in ks if k >= after and p[k] == to), None)
    if drop_arrive is None:
        drop_arrive = next((k for k in ks if k >= after and _cheb(p[k], to) <= 1), d_k)
    # 토트 = 서로 다른 태스크 id. 동승 태스크는 주 태스크의 riders 와 목록 자체에 **두 번** 나온다(실측: 6토트 운행이 11로 셌다)
    ids, orders = set(), set()
    for t in g["tasks"]:
        for x in [t, *(t.get("riders") or [])]:
            ids.add(x.get("id", id(x)))
            orders.add(x.get("order", x.get("id")))
    totes = len(ids)
    return Trip(rid, frm, to, label(g["frm_name"], lang), label(g["to_name"], lang), a_k,
                pick_arrive, pick_leave, drop_arrive, d_k, totes, len(orders))


# ── 그리기 (PIL) ─────────────────────────────────────────────────────────
def _font(font_path, px):
    """글꼴 파일이 없거나 못 읽으면 PIL 기본 글꼴 — 글씨가 작아질 뿐 프레임은 잃지 않는다.
    기본 글꼴에는 한글이 없으니 한글 글꼴이 없을 때는 `Timeline(lang="en")` 과 짝지어 쓴다."""
    from PIL import ImageFont
    if font_path:
        try:
            return ImageFont.truetype(font_path, px)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=px)          # Pillow ≥ 10.1
    except TypeError:
        return ImageFont.load_default()


def draw(img, lines, font_path, phase_key="idle"):
    """PIL Image 위에 글씨를 얹어 돌려준다. 위: 반투명 띠 두 줄 · 아래 왼쪽: 단계(크게) · 아래 오른쪽: 실적."""
    from PIL import Image, ImageDraw
    head, sub, big, right = lines
    w, h = img.size
    s = h / 540.0                                       # 960x540 기준 크기를 해상도에 맞춘다
    f_head, f_sub, f_big, f_right = (_font(font_path, max(10, int(px * s))) for px in (22, 20, 30, 20))
    base = img.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.rectangle([0, 0, w, int(76 * s)], fill=(10, 20, 35, 170))
    d.text((int(16 * s), int(10 * s)), head, font=f_head, fill=(255, 255, 255, 255))
    if sub:
        d.text((int(16 * s), int(42 * s)), sub, font=f_sub, fill=(255, 214, 102, 255))
    color = PHASE_RGB.get(phase_key, (200, 200, 200))
    bx, by = int(16 * s), h - int(64 * s)
    tw = d.textlength(big, font=f_big)
    d.rounded_rectangle([bx - int(8 * s), by - int(6 * s), bx + tw + int(12 * s), by + int(44 * s)],
                        radius=int(10 * s), fill=(*color, 215))
    d.text((bx + int(2 * s), by), big, font=f_big, fill=(15, 15, 15, 255))
    rw = d.textlength(right, font=f_right)
    d.rectangle([w - rw - int(28 * s), h - int(44 * s), w, h], fill=(10, 20, 35, 170))
    d.text((w - rw - int(14 * s), h - int(36 * s)), right, font=f_right, fill=(255, 255, 255, 255))
    return Image.alpha_composite(base, layer).convert("RGB")


# ── 천장 영상 (-244) ──────────────────────────────────────────────────────
#   120 m 상공 광각에서 1.5 m AMR 은 흰 점 18 px 이라 바닥과 구분이 안 된다. USD 에 표시 prim 을 달면
#   물리 링크 밑이라 판이 달라질 위험이 있어, **프레임 위에 그린다** — 로봇 자세를 카메라로 투영해
#   단계 색 원 · 진행 방향 · 번호를 얹는다. 물리와 무관하다.
def top_down(cx, cy, height):
    """(cx, cy) 를 바로 위 height m 에서 내려다보는 카메라의 카메라→월드 변환 (USD 행벡터 4x4).
    화면 오른쪽 = +x, 위 = +y — `build_amr_scene_v2.look_at` 이 Cam_Top 에 만드는 것과 같은 축."""
    return [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0],
            [float(cx), float(cy), float(height), 1.0]]


def fit_top(extent, size, focal_mm, h_aperture_mm, margin_m=4.0):
    """로봇이 다닌 범위 + 여유를 화면에 꽉 차게 — top_down 의 (cx, cy, height).
    바닥에서 보이는 너비 = 높이 × 수평 조리개 ÷ 초점거리."""
    x0, x1, y0, y1 = extent
    x0, x1, y0, y1 = x0 - margin_m, x1 + margin_m, y0 - margin_m, y1 + margin_m
    w, h = size
    width_m = max(x1 - x0, (y1 - y0) * w / h)
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0, width_m * focal_mm / h_aperture_mm


def project(pts, cam_to_world, focal_mm, h_aperture_mm, size):
    """월드 점들 → 화면 픽셀 (u, v). 카메라는 로컬 −Z 를 보고, 수평 조리개가 화면 너비에 맞는다(정사각 픽셀).
    카메라 뒤의 점은 None."""
    import numpy as np
    w, h = size
    inv = np.linalg.inv(np.asarray(cam_to_world, dtype=float))
    fx = float(focal_mm) / float(h_aperture_mm) * w
    out = []
    for x, y, z in pts:
        xc, yc, zc, _ = np.array([x, y, z, 1.0]) @ inv
        if zc >= -1e-6:
            out.append(None)
            continue
        out.append((w / 2.0 + fx * xc / -zc, h / 2.0 - fx * yc / -zc))
    return out


def draw_top(img, marks, lines, font_path, stations=(), lang="ko"):
    """천장 프레임 위에 로봇(단계 색 원 · 진행 방향 · 번호) · 포장대 이름 · 윗줄 · 범례 · 실적을 얹는다."""
    import math
    from PIL import Image, ImageDraw
    head, right = lines
    w, h = img.size
    s = h / 720.0                                       # 1280x720 기준
    f_head, f_small, f_num = (_font(font_path, max(10, int(px * s))) for px in (24, 18, 15))
    base = img.convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for name, u, v in stations:                         # 포장대 — 토트가 가는 곳
        tw = d.textlength(name, font=f_small)
        d.rectangle([u - tw / 2 - 4 * s, v - 12 * s, u + tw / 2 + 4 * s, v + 12 * s], fill=(10, 20, 35, 150))
        d.text((u - tw / 2, v - 10 * s), name, font=f_small, fill=(255, 214, 102, 255))
    for m in marks:
        hl = math.hypot(m.hu, m.hv) or 1.0
        r = max(10.0 * s, 1.2 * hl)
        if m.follow:                                    # 1인칭 영상의 그 로봇
            d.ellipse([m.u - r - 6 * s, m.v - r - 6 * s, m.u + r + 6 * s, m.v + r + 6 * s],
                      outline=(255, 60, 200, 255), width=max(2, int(4 * s)))
        d.ellipse([m.u - r, m.v - r, m.u + r, m.v + r], fill=(*PHASE_RGB.get(m.key, (200, 200, 200)), 255),
                  outline=(15, 15, 15, 255), width=max(1, int(2 * s)))
        d.line([m.u, m.v, m.u + m.hu / hl * r * 1.4, m.v + m.hv / hl * r * 1.4],
               fill=(15, 15, 15, 255), width=max(2, int(3 * s)))
        tag = str(m.num)
        tx, ty = m.u + r * 0.8, m.v - r * 0.8 - 16 * s
        tw = d.textlength(tag, font=f_num)
        d.rectangle([tx - 3 * s, ty, tx + tw + 3 * s, ty + 17 * s], fill=(10, 20, 35, 200))
        d.text((tx, ty), tag, font=f_num, fill=(255, 255, 255, 255))
    d.rectangle([0, 0, w, int(44 * s)], fill=(10, 20, 35, 170))
    d.text((int(16 * s), int(9 * s)), head, font=f_head, fill=(255, 255, 255, 255))
    x = int(16 * s)                                     # 범례 — 아래 왼쪽
    y = h - int(36 * s)
    items = [(k, _PHASE_SHORT[k][0 if lang == "ko" else 1]) for k in _PHASE_SHORT]
    tot = sum(d.textlength(t, font=f_small) + 40 * s for _, t in items)
    d.rectangle([0, y - 8 * s, x + tot + 8 * s, h], fill=(10, 20, 35, 170))
    for k, t in items:
        d.ellipse([x, y + 2 * s, x + 16 * s, y + 18 * s], fill=(*PHASE_RGB[k], 255))
        d.text((x + 22 * s, y), t, font=f_small, fill=(255, 255, 255, 255))
        x += int(d.textlength(t, font=f_small) + 40 * s)
    rw = d.textlength(right, font=f_small)
    d.rectangle([w - rw - int(28 * s), y - 8 * s, w, h], fill=(10, 20, 35, 170))
    d.text((w - rw - int(14 * s), y), right, font=f_small, fill=(255, 255, 255, 255))
    return Image.alpha_composite(base, layer).convert("RGB")
