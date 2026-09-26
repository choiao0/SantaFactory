# -*- coding: utf-8 -*-
"""검증 영상 위의 표시 — 「이 AMR 이 지금 무슨 주문을 어디서 어디로 나르나」 (S15P21A106-244 · 279).

영상만 봐서는 AMR 이 **주문을 처리하는 중**인지 그냥 돌아다니는지 알 수 없다. DES 피크 구간(slice format 1)에는
태스크마다 출발지·목적지·배정·완료 틱이 있고 로봇마다 매 틱 자리가 있으니, 로봇별 **운행**(픽업 → 적재 → 운반 → 하역)을
짤 수 있다. 태스크에는 로봇 번호가 없어 **완료 틱에 목적지 옆에 선 로봇**으로 짝짓는다(여럿이면 그 사이 출발지에 들렀던 로봇).

★ 글씨의 단계는 **DES 시각이 아니라 그 로봇이 Isaac 에서 실제로 어느 동작까지 왔나**로 정한다. 물리는 DES 보다 늦으므로
  시각으로 고르면 화면과 글씨가 어긋난다. 실행기의 동작마다 DES 계획 틱(`Action.tick`, 구간 시작 = 0)이 붙어 있어,
  「지금 수행 중인 동작의 계획 틱」을 넘기면 그 순간 DES 계획상의 단계가 나온다.

화면 디자인(v2, -279): 반투명 검정 **각진** 카드에 왼쪽 색 띠(제목 = 빨강, 로봇 카드 = 지금 단계 색), 위쪽 밝은 1 px 선.
Noto Sans CJK KR 세 굵기, 2배로 그려 줄여 가장자리를 매끈하게. 천장 영상은 로봇을 **고리로 비워 두고** 가는 선으로
상태 말풍선을 잇는다(겹치지 않는 자리를 찾아 둔다). 고객에게 보이는 말은 확정 용어만 쓴다 —
3D 주행 검증 · 주문 집중 10분 · 피킹 지점 · 포장대 · 상자 · 배송.

Isaac 이 없어도 도는 순수 함수다(`path/test_demo_overlay.py`). 그리기(`draw` · `draw_top`)만 PIL 을 쓴다.
"""
import json
import re
from dataclasses import dataclass

_NAME_RE = re.compile(r"^([a-z_]+)\[(\d+)\]$")
_NAMES = {   # 지점 이름 → (한국어, 영어). 번호는 1부터
    "aisle_buf": ("피킹 지점", "Picking point"),
    "packing": ("포장대", "Packing"),
    "charger": ("충전소", "Charger"),
    "handoff": ("인계 지점", "Handoff"),
    "inbound": ("입고장", "Inbound"),
    "receiving": ("입고장", "Receiving"),
    "dock": ("도크", "Dock"),
}
_PHASES = {  # 단계 → (한국어, 영어) — 추종 영상의 상태 칩
    "to_pick": ("피킹 지점으로 이동", "To picking point"),
    "loading": ("상자 싣는 중", "Loading"),
    "carrying": ("포장대로 운반 중", "To packing"),
    "unloading": ("상자 내리는 중", "Unloading"),
    "idle": ("대기 중", "Idle"),
}
_PHASE_SHORT = {  # 천장 영상 말풍선 · 범례
    "to_pick": ("이동", "Move"),
    "loading": ("싣기", "Load"),
    "carrying": ("운반", "Carry"),
    "unloading": ("내리기", "Unload"),
    "idle": ("대기", "Idle"),
}
STEPS = ("to_pick", "loading", "carrying", "unloading")
PHASE_RGB = {"to_pick": (59, 130, 246), "loading": (245, 158, 11), "carrying": (16, 185, 129),
             "unloading": (139, 92, 246), "idle": (148, 163, 184)}


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

    def lines(self, rid, des_k, window_clock_s, waiting=False):
        """추종 영상에 얹을 값. window_clock_s 가 None 이면 시작 준비 중.
        waiting — 이동해야 할 단계인데 서 있다(앞 로봇이 지나가길 기다린다). 화면에 「통행 대기」로 붙인다."""
        ko = self.lang == "ko"
        ph = self.phase(rid, des_k)
        t = ph.trip
        trips, totes = self.done(rid, des_k)
        step = STEPS.index(ph.key) if ph.key in STEPS else -1
        if t is not None and t.pick_arrive_k is None and step < 2:
            step = 2                                        # 구간 전에 이미 실었다
        return dict(robot=int(rid) + 1 if str(rid).isdigit() else rid, lang=self.lang,
                    title="3D 주행 검증 · 주문 집중 10분" if ko else "3D drive check · busiest 10 min",
                    clock=window_clock_s, window=self.window_s, phase=ph.key,
                    waiting=bool(waiting) and ph.key in ("to_pick", "carrying"),
                    phase_label=_PHASES[ph.key][0 if ko else 1], step=step,
                    frm=t.frm_label if t else None, to=t.to_label if t else None,
                    orders=t.orders if t else 0, totes=t.totes if t else 0,
                    done_trips=trips, done_totes=totes)

    def top_lines(self, ks, window_clock_s, n_robots):
        """천장 영상에 얹을 값. ks = {로봇: 그 로봇의 계획 틱} — 실적은 로봇마다 제 틱까지 합한다."""
        ko = self.lang == "ko"
        done = [self.done(rid, k) for rid, k in ks.items()]
        return dict(lang=self.lang, title="3D 주행 검증" if ko else "3D drive check",
                    sub=(f"AMR {n_robots}대 · 주문 집중 10분" if ko else f"{n_robots} AMRs · busiest 10 min"),
                    clock=window_clock_s, window=self.window_s,
                    trips=sum(d[0] for d in done), totes=sum(d[1] for d in done))

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
# ── 그리기 (v2, -279) — 상업용 오버레이 ─────────────────────────────────
#   어두운 유리 카드 · Noto Sans CJK KR 세 굵기 · 2배 슈퍼샘플링. 상태색은 색상(hue)으로만 가른다.
import os
import threading

SS = 2                                   # 슈퍼샘플링 배율 — 도형 가장자리를 매끈하게
GLASS = (12, 14, 18, 204)
GLASS2 = (12, 14, 18, 150)
EDGE = (255, 255, 255, 22)
TOPLINE = (255, 255, 255, 34)            # 카드 위쪽 가장자리 — 유리판 모서리처럼 또렷하게
NEUTRAL = (255, 255, 255, 110)
TXT = (245, 247, 250, 255)
TXT2 = (170, 178, 190, 255)
ACCENT = (231, 45, 45, 255)
_tls = threading.local()                 # 글꼴은 쓰기 스레드마다 따로 연다(FreeType 면은 스레드 공유 불가)


def _face(font_path, weight):
    """굵기별 글꼴 파일. 'NotoSansCJK-Bold.ttc' 를 주면 같은 폴더의 Regular·Medium 을 찾는다."""
    if font_path and "Bold" in os.path.basename(font_path):
        cand = font_path.replace("Bold", weight)
        if os.path.isfile(cand):
            return cand
    return font_path


def _font(font_path, px, weight="Bold"):
    from PIL import ImageFont
    cache = getattr(_tls, "fonts", None)
    if cache is None:
        cache = _tls.fonts = {}
    key = (font_path, weight, px)
    if key in cache:
        return cache[key]
    path = _face(font_path, weight)
    f = None
    if path:
        try:
            f = ImageFont.truetype(path, px, index=1 if path.lower().endswith(".ttc") else 0)
        except OSError:
            f = None
    if f is None:
        try:
            f = ImageFont.load_default(size=px)          # Pillow ≥ 10.1
        except TypeError:
            f = ImageFont.load_default()
    cache[key] = f
    return f


class _Canvas:
    """기준 해상도 좌표로 그리고, 2배로 그려 줄여서 얹는다."""

    def __init__(self, img, base_h, font_path):
        from PIL import Image, ImageDraw
        self.img = img
        self.W, self.H = img.size
        self.s = self.H / base_h                    # 기준 → 실제
        self.k = self.s * SS                        # 기준 → 그림판
        self.bw, self.bh = self.W / self.s, self.H / self.s     # 기준 좌표계의 폭·높이
        self.fp = font_path
        self.layer = Image.new("RGBA", (self.W * SS, self.H * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.layer)

    def f(self, weight, px):
        return _font(self.fp, max(8, round(px * self.k)), weight)

    def tw(self, text, weight, px):
        return self.d.textlength(text, font=self.f(weight, px)) / self.k

    def text(self, x, y, text, weight, px, fill, anchor="ls"):
        self.d.text((x * self.k, y * self.k), text, font=self.f(weight, px), fill=fill, anchor=anchor)

    def card(self, x0, y0, x1, y1, r=2, fill=GLASS, outline=EDGE, width=1.0, accent=None, bar=3):
        """각진 카드. accent 가 있으면 왼쪽 가장자리에 색 띠(bar px), 위쪽에는 밝은 1 px 선."""
        k = self.k
        self.d.rounded_rectangle([x0 * k, y0 * k, x1 * k, y1 * k], radius=r * k, fill=fill,
                                 outline=outline, width=max(1, round(width * k)))
        self.d.line([(x0 + r) * k, y0 * k + k * .5, (x1 - r) * k, y0 * k + k * .5], fill=TOPLINE,
                    width=max(1, round(k)))
        if accent is not None:
            self.d.rectangle([x0 * k, y0 * k, (x0 + bar) * k, y1 * k], fill=accent)

    def bar(self, x0, y0, x1, y1, fill):
        k = self.k
        self.d.rectangle([x0 * k, y0 * k, x1 * k, y1 * k], fill=fill)

    def dot(self, x, y, r, fill):
        k = self.k
        self.d.ellipse([(x - r) * k, (y - r) * k, (x + r) * k, (y + r) * k], fill=fill)

    def finish(self):
        from PIL import Image
        small = self.layer.resize((self.W, self.H), Image.LANCZOS)
        return Image.alpha_composite(self.img.convert("RGBA"), small).convert("RGB")


def _tint(rgb, t=0.55):
    """상태색을 흰색 쪽으로 — 어두운 카드 위 글자색."""
    return tuple(round(c + (255 - c) * t) for c in rgb) + (255,)


def _clock_block(c, x, y, info, big=15):
    """「04:50 / 10:00」 — 준비 중이면 그 말."""
    ko = info.get("lang", "ko") == "ko"
    if info["clock"] is None:
        c.text(x, y, "시작 준비" if ko else "Starting", "Medium", big - 2, TXT2)
        return c.tw("시작 준비" if ko else "Starting", "Medium", big - 2)
    now, total = _mmss(info["clock"]), _mmss(info["window"])
    c.text(x, y, now, "Bold", big, TXT)
    w = c.tw(now, "Bold", big)
    c.text(x + w + 4, y, f"/ {total}", "Regular", big - 3, TXT2)
    return w + 4 + c.tw(f"/ {total}", "Regular", big - 3)


def _progress(c, x0, x1, y, info):
    c.bar(x0, y, x1, y + 3, (255, 255, 255, 40))
    if info["clock"] is not None and info["window"]:
        frac = max(0.0, min(1.0, info["clock"] / info["window"]))
        if frac > 0:
            c.bar(x0, y, x0 + (x1 - x0) * frac, y + 3, ACCENT)


def _chip(c, x, cy, label, key=None, px=12.5, rgb=None):
    """상태 태그 — 각진 바탕에 왼쪽 색 띠, 흰 글자. 너비를 돌려준다."""
    rgb = rgb or PHASE_RGB.get(key, (148, 163, 184))
    w = c.tw(label, "Medium", px) + 22
    c.card(x, cy - 12, x + w, cy + 12, r=1.5, fill=rgb + (52,), outline=rgb + (120,), width=1,
           accent=rgb + (255,), bar=3)
    c.text(x + 12, cy, label, "Medium", px, TXT, anchor="lm")
    return w


def draw(img, info, font_path, phase_key="idle"):
    """추종 영상(960×540 기준) — 왼쪽 위 진행 캡슐 · 왼쪽 아래 정보 카드 · 오른쪽 아래 실적."""
    c = _Canvas(img, 540, font_path)
    ko = info.get("lang", "ko") == "ko"
    # 진행 캡슐
    x, y = 20, 18
    wt = c.tw(info["title"], "Medium", 13)
    w = max(wt, 150) + 30
    c.card(x, y, x + w, y + 60, accent=ACCENT)
    c.text(x + 16, y + 23, info["title"], "Medium", 13, TXT)
    _clock_block(c, x + 16, y + 44, info, big=15)
    _progress(c, x + 16, x + w - 14, y + 50, info)
    # 정보 카드
    W0, H0 = 344, 124
    x0, y1 = 20, c.bh - 20
    y0 = y1 - H0
    rgb = PHASE_RGB.get(info["phase"], (148, 163, 184))
    c.card(x0, y0, x0 + W0, y1, accent=rgb + (255,), bar=4)
    robot = f"AMR {info['robot']:02d}" if isinstance(info["robot"], int) else f"AMR {info['robot']}"
    c.text(x0 + 18, y0 + 33, robot, "Bold", 20, TXT)
    cx = x0 + 18 + c.tw(robot, "Bold", 20) + 12
    cx += _chip(c, cx, y0 + 26, info["phase_label"], info["phase"]) + 6
    if info.get("waiting"):
        _chip(c, cx, y0 + 26, "통행 대기" if ko else "Waiting to pass", rgb=(226, 232, 240), px=12)
    if info["frm"]:
        xx = x0 + 18
        c.text(xx, y0 + 60, info["frm"], "Regular", 14, TXT)
        xx += c.tw(info["frm"], "Regular", 14) + 8
        arrow = "→" if ko else "->"
        c.text(xx, y0 + 60, arrow, "Regular", 14, TXT2)
        xx += c.tw(arrow, "Regular", 14) + 8
        c.text(xx, y0 + 60, info["to"], "Medium", 14, TXT)
        c.text(x0 + 18, y0 + 80, (f"주문 {info['orders']}건 · 상자 {info['totes']}개" if ko
                                  else f"{info['orders']} orders · {info['totes']} totes"), "Regular", 12, TXT2)
    else:
        c.text(x0 + 18, y0 + 60, "다음 주문을 기다리고 있습니다" if ko else "Waiting for the next order", "Regular", 14, TXT2)
    # 단계 막대 — 이동 · 싣기 · 운반 · 내리기
    sx0, sx1, gap = x0 + 18, x0 + W0 - 16, 4
    seg = (sx1 - sx0 - gap * 3) / 4
    for i, key in enumerate(STEPS):
        a = sx0 + i * (seg + gap)
        cur, done = i == info["step"], 0 <= i < info["step"]
        col = rgb + (255,) if cur else ((255, 255, 255, 150) if done else (255, 255, 255, 38))
        c.bar(a, y0 + 94, a + seg, y0 + 97, col)
        c.text(a, y0 + 112, _PHASE_SHORT[key][0 if ko else 1], "Medium" if cur else "Regular", 10.5,
               TXT if cur else TXT2)
    # 실적
    lab1, lab2 = ("배송 완료", "옮긴 상자") if ko else ("Deliveries", "Totes")
    v1, v2 = (f"{info['done_trips']}건", f"{info['done_totes']}개") if ko else (str(info["done_trips"]), str(info["done_totes"]))
    cw = 96
    x1 = c.bw - 20
    c.card(x1 - cw * 2, y1 - 64, x1, y1, accent=NEUTRAL)
    for i, (lab, val) in enumerate(((lab1, v1), (lab2, v2))):
        cx = x1 - cw * 2 + i * cw + 18
        c.text(cx, y1 - 40, lab, "Regular", 11, TXT2)
        c.text(cx, y1 - 16, val, "Bold", 20, TXT)
    return c.finish()


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


def _rect_hits(r, rects, pad=3):
    return any(r[0] < b[2] + pad and r[2] + pad > b[0] and r[1] < b[3] + pad and r[3] + pad > b[1] for b in rects)


def _circle_hits(r, circles):
    for cx, cy, rad in circles:
        nx, ny = min(max(cx, r[0]), r[2]), min(max(cy, r[1]), r[3])
        if (nx - cx) ** 2 + (ny - cy) ** 2 < rad * rad:
            return True
    return False


def draw_top(img, marks, info, font_path, stations=(), lang="ko"):
    """천장 영상(1280×720 기준) — 로봇은 고리로 비워 두고, 선으로 상태 말풍선을 잇는다."""
    import math
    c = _Canvas(img, 720, font_path)
    ko = lang == "ko"
    s = c.s
    R = 14                                          # 고리 반지름(기준 px) — 차체(≈20 px)를 가리지 않게
    # 머리 카드 · 실적 카드 · 범례 — 말풍선이 피할 자리
    tw_ = max(c.tw(info["title"], "Medium", 15), c.tw(info["sub"], "Regular", 12))
    hw = tw_ + 150
    head = (20, 18, 20 + hw, 18 + 66)
    c.card(*head, accent=ACCENT, bar=4)
    c.text(38, 44, info["title"], "Medium", 15, TXT)
    c.text(38, 64, info["sub"], "Regular", 12, TXT2)
    # 시계는 머리 카드 오른쪽 안
    now = "시작 준비" if info["clock"] is None else _mmss(info["clock"])
    if info["clock"] is None:
        c.text(head[2] - 16, 50, now, "Medium", 13, TXT2, anchor="rs")
    else:
        tot = f"/ {_mmss(info['window'])}"
        c.text(head[2] - 16, 50, tot, "Regular", 12, TXT2, anchor="rs")
        c.text(head[2] - 16 - c.tw(tot, "Regular", 12) - 4, 50, now, "Bold", 20, TXT, anchor="rs")
    _progress(c, head[0] + 18, head[2] - 16, head[3] - 11, info)
    lab1, lab2 = ("배송 완료", "옮긴 상자") if ko else ("Deliveries", "Totes")
    v1, v2 = (f"{info['trips']}건", f"{info['totes']}개") if ko else (str(info["trips"]), str(info["totes"]))
    stat = (c.bw - 20 - 220, 18, c.bw - 20, 18 + 66)
    c.card(*stat, accent=NEUTRAL)
    for i, (lab, val) in enumerate(((lab1, v1), (lab2, v2))):
        x = stat[0] + 18 + i * 110
        c.text(x, 42, lab, "Regular", 12, TXT2)
        c.text(x, 70, val, "Bold", 22, TXT)
    items = [(k, _PHASE_SHORT[k][0 if ko else 1]) for k in ("to_pick", "loading", "carrying", "unloading", "idle")]
    lw = sum(c.tw(t, "Regular", 12) + 30 for _, t in items) + 14
    legend = (20, c.bh - 20 - 32, 20 + lw, c.bh - 20)
    c.card(*legend, fill=GLASS2)
    x = legend[0] + 14
    for k, t in items:
        c.bar(x, legend[1] + 11, x + 10, legend[1] + 21, PHASE_RGB[k] + (255,))
        c.text(x + 15, legend[1] + 16, t, "Regular", 12, TXT, anchor="lm")
        x += c.tw(t, "Regular", 12) + 30
    rects = [head, stat, legend]
    for name, u, v in stations:                      # 포장대 이름 — 작고 조용하게
        bu, bv = u / s, v / s
        w = c.tw(name, "Medium", 11) + 12
        r = (bu - w / 2, bv - 9, bu + w / 2, bv + 9)
        c.card(*r, r=1.5, fill=GLASS2, outline=(0, 0, 0, 0))
        c.text(bu, bv, name, "Medium", 11, TXT, anchor="mm")
        rects.append(r)
    circles = [(m.u / s, m.v / s, R + 4) for m in marks]
    placed = []
    order = sorted(marks, key=lambda m: (not m.follow, m.v))
    angles = [-45, -135, 45, 135, -90, 90, 0, 180]
    for m in order:
        bu, bv = m.u / s, m.v / s
        key = m.key
        rgb = PHASE_RGB.get(key, (148, 163, 184))
        num = f"{m.num:02d}"
        lab = _PHASE_SHORT.get(key, ("", ""))[0 if ko else 1]
        w = 3 + 9 + c.tw(num, "Bold", 12) + 5 + c.tw(lab, "Regular", 12) + 10
        h = 22
        best = None
        near = [(o.u / s, o.v / s) for o in marks if o is not m and math.hypot(o.u / s - bu, o.v / s - bv) < 90]
        if near:
            ox = sum(p[0] for p in near) / len(near) - bu
            oy = sum(p[1] for p in near) / len(near) - bv
            away = math.degrees(math.atan2(-oy, -ox))
            cand = sorted(angles, key=lambda a: abs((a - away + 180) % 360 - 180))
        else:
            cand = angles
        for dist in (30, 46, 64):
            for a in cand:
                ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))
                ax, ay = bu + ca * dist, bv + sa * dist
                x0 = ax if ca > 0.3 else (ax - w if ca < -0.3 else ax - w / 2)
                y0 = ay - h if sa < -0.3 else (ay if sa > 0.3 else ay - h / 2)
                r = (x0, y0, x0 + w, y0 + h)
                if r[0] < 4 or r[1] < 4 or r[2] > c.bw - 4 or r[3] > c.bh - 4:
                    continue
                if _rect_hits(r, rects + placed) or _circle_hits(r, circles):
                    continue
                best = (r, ca, sa)
                break
            if best:
                break
        if best is None:                             # 자리가 없으면 오른쪽 위에 그냥 둔다
            r = (bu + 22, bv - 22 - h, bu + 22 + w, bv - 22)
            best = (r, 0.7, -0.7)
        r, ca, sa = best
        placed.append(r)
        m.callout = (r, rgb, num, lab)
    # 선 → 고리 → 말풍선 순서로 그린다
    for m in marks:
        r, rgb, _, _ = m.callout
        bu, bv = m.u / s, m.v / s
        nx, ny = min(max(bu, r[0]), r[2]), min(max(bv, r[1]), r[3])
        dx, dy = nx - bu, ny - bv
        dd = math.hypot(dx, dy) or 1.0
        sx, sy = bu + dx / dd * (R + 1), bv + dy / dd * (R + 1)
        k = c.k
        c.d.line([sx * k, sy * k, nx * k, ny * k], fill=(15, 17, 21, 170), width=max(1, round(3.2 * k)))
        c.d.line([sx * k, sy * k, nx * k, ny * k], fill=rgb + (255,), width=max(1, round(1.6 * k)))
    for m in marks:
        _, rgb, _, _ = m.callout
        bu, bv = m.u / s, m.v / s
        k = c.k
        if m.follow:
            c.d.ellipse([(bu - R - 5) * k, (bv - R - 5) * k, (bu + R + 5) * k, (bv + R + 5) * k],
                        outline=ACCENT, width=max(1, round(2.2 * k)))
        c.d.ellipse([(bu - R - 1) * k, (bv - R - 1) * k, (bu + R + 1) * k, (bv + R + 1) * k],
                    outline=(15, 17, 21, 170), width=max(1, round(4.6 * k)))
        c.d.ellipse([(bu - R) * k, (bv - R) * k, (bu + R) * k, (bv + R) * k],
                    outline=rgb + (255,), width=max(1, round(2.6 * k)))
        hl = math.hypot(m.hu, m.hv) or 1.0
        hx, hy = m.hu / hl, m.hv / hl
        tip = (bu + hx * (R + 7), bv + hy * (R + 7))
        b1 = (bu + hx * (R + 1) - hy * 4.5, bv + hy * (R + 1) + hx * 4.5)
        b2 = (bu + hx * (R + 1) + hy * 4.5, bv + hy * (R + 1) - hx * 4.5)
        c.d.polygon([(tip[0] * k, tip[1] * k), (b1[0] * k, b1[1] * k), (b2[0] * k, b2[1] * k)], fill=rgb + (255,))
    for m in marks:
        r, rgb, num, lab = m.callout
        c.card(*r, r=1.5, fill=GLASS, outline=(ACCENT if m.follow else EDGE), width=1.4 if m.follow else 1,
               accent=rgb + (255,), bar=3)
        cy = (r[1] + r[3]) / 2
        c.text(r[0] + 12, cy, num, "Bold", 12, TXT, anchor="lm")
        c.text(r[0] + 12 + c.tw(num, "Bold", 12) + 5, cy, lab, "Regular", 12, _tint(rgb, .45), anchor="lm")
    return c.finish()
