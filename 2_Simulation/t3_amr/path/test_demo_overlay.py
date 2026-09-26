# -*- coding: utf-8 -*-
"""`demo_overlay` — 1인칭 영상 위에 「이 AMR 이 지금 무슨 주문을 어디서 어디로」를 적는다 (S15P21A106-244).

Isaac 없이 본다: 합성 구간(로봇 두 대 · 운행 하나)으로 운행 짜기 · 단계 · 실적 · 로봇 고르기 · 글씨 줄을 확인한다.

    python3 -m pytest path/test_demo_overlay.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import demo_overlay as DO                                     # noqa: E402

DT = 1.0


def xy(r, c):
    """export_isaac._xy 규약: x = (c+0.5) − 0.4, y = r + 0.5."""
    return round(c + 0.1, 2), round(r + 0.5, 2)


def slice_doc():
    """로봇 0: 틱 0~3 (5,0)에서 대기 → 4~5 (5,1)·(5,2) 이동 → 6~8 픽업 칸 (5,3) 정차 → 9~11 이동 → 12~14 포장대 (5,6) 정차 → 이후 (5,6).
    로봇 1: 내내 (9,9) 에 서 있다. 태스크 두 건(같은 운행, 토트 2 + 동승 1)이 틱 14 에 끝난다. 구간 시작 = 절대 틱 100."""
    path0 = [(5, 0)] * 4 + [(5, 1), (5, 2)] + [(5, 3)] * 3 + [(5, 4), (5, 5), (5, 5)] + [(5, 6)] * 9
    rows0 = [[100 + k, *xy(r, c)] for k, (r, c) in enumerate(path0)]
    rows1 = [[100 + k, *xy(9, 9)] for k in range(len(path0))]
    tasks = [
        {"id": 1, "order": 11, "frm": [5, 3], "to": [5, 6], "frm_name": "aisle_buf[4]", "to_name": "packing[0]",
         "assigned": 102, "completed": 114, "riders": [{"id": 3, "order": 13}]},
        {"id": 2, "order": 12, "frm": [5, 3], "to": [5, 6], "frm_name": "aisle_buf[4]", "to_name": "packing[0]",
         "assigned": 102, "completed": 114, "riders": []},
    ]
    return {"dt_s": DT, "robots": {"0": rows0, "1": rows1}, "headings": {}, "tasks": tasks,
            "slice": {"t_start_s": 100.0, "t0_s": 102.0, "warmup_s": 2.0, "window_s": 15.0}}


class TestTrips:
    def test_two_tasks_that_finish_together_are_one_trip_with_all_totes(self):
        tl = DO.Timeline.from_slice(slice_doc())
        trips = tl.trips["0"]
        assert len(trips) == 1 and tl.trips.get("1", []) == []
        t = trips[0]
        assert (t.pick_arrive_k, t.pick_leave_k, t.drop_arrive_k, t.done_k) == (6, 9, 12, 14)
        assert t.totes == 3 and t.orders == 3                  # 두 태스크 + 동승 하나
        assert t.frm_label == "통로 버퍼 5" and t.to_label == "포장대 1"


    def test_a_rider_listed_twice_is_one_tote(self):
        """동승 태스크는 주 태스크의 riders 와 태스크 목록 양쪽에 나온다 — 두 번 세면 6토트 운행이 11이 된다."""
        doc = slice_doc()
        doc["tasks"].append({"id": 3, "order": 13, "frm": [5, 3], "to": [5, 6], "frm_name": "aisle_buf[4]",
                             "to_name": "packing[0]", "assigned": 102, "completed": 114, "riders": []})
        t = DO.Timeline.from_slice(doc).trips["0"][0]
        assert t.totes == 3 and t.orders == 3


class TestPhase:
    def test_phases_follow_the_des_plan_tick(self):
        tl = DO.Timeline.from_slice(slice_doc())
        assert tl.phase("0", 3).key == "to_pick"                # 배정(틱 2) 뒤, 픽업 칸 도착 전
        assert tl.phase("0", 7).key == "loading"
        assert tl.phase("0", 10).key == "carrying"
        assert tl.phase("0", 13).key == "unloading"
        assert tl.phase("0", 16).key == "idle"                  # 운행이 끝났다
        assert tl.phase("1", 5).key == "idle"

    def test_done_counts_only_trips_finished_by_that_tick(self):
        tl = DO.Timeline.from_slice(slice_doc())
        assert tl.done("0", 13) == (0, 0)
        assert tl.done("0", 14) == (1, 3)


class TestPlanTick:
    """글씨의 단계를 정하는 틱 — 실행기는 동작마다 계획 틱을 릴리스 바닥으로 박아 **DES 보다 앞서지 못한다**."""

    def test_on_schedule_the_clock_decides(self):
        """다음 동작이 아직 풀리지 않았다(시계 < 계획) = 계획대로 서 있는 중(적재·대기) → 시계 틱."""
        assert DO.plan_tick(pending_tick=80, clock_s=30.4, tick_s=0.5) == 60

    def test_lagging_robot_shows_what_it_is_actually_doing(self):
        """시계는 넘었는데 동작이 아직 = 밀린 로봇 → 지금 붙잡고 있는 동작의 계획 틱."""
        assert DO.plan_tick(pending_tick=40, clock_s=30.4, tick_s=0.5) == 40

    def test_chain_finished_follows_the_clock(self):
        assert DO.plan_tick(pending_tick=None, clock_s=12.0, tick_s=0.5) == 24


class TestPick:
    def test_the_busiest_robot_is_followed(self):
        assert DO.Timeline.from_slice(slice_doc()).busiest() == "0"


class TestLines:
    def test_the_hud_reads_like_order_work(self):
        tl = DO.Timeline.from_slice(slice_doc())
        top, sub, big, right = tl.lines("0", des_k=10, window_clock_s=8.0)
        assert "AMR 1" in top and "00:08 / 00:15" in top
        assert "주문 3건" in sub and "토트 3개" in sub and "통로 버퍼 5 → 포장대 1" in sub
        assert "운반 중" in big and "포장대 1" in big
        assert "완료 운행 0회" in right

    def test_before_the_window_it_says_warming_up(self):
        top, *_ = DO.Timeline.from_slice(slice_doc()).lines("0", des_k=0, window_clock_s=None)
        assert "준비 중" in top

    def test_english_labels_when_no_korean_font(self):
        tl = DO.Timeline.from_slice(slice_doc(), lang="en")
        _, sub, big, _ = tl.lines("0", des_k=10, window_clock_s=8.0)
        assert "Aisle buffer 5 -> Packing 1" in sub and "Carrying" in big


class TestDraw:
    def test_draws_on_a_frame_of_the_same_size(self):
        from PIL import Image
        img = Image.new("RGB", (960, 540), (40, 40, 40))
        lines = DO.Timeline.from_slice(slice_doc(), lang="en").lines("0", des_k=10, window_clock_s=8.0)
        out = DO.draw(img, lines, None, "carrying")
        assert out.size == img.size and out.mode == "RGB"
        assert out.getpixel((20, 540 - 20)) != (40, 40, 40)      # 단계 알약이 칠해졌다

    def test_a_missing_font_file_falls_back_instead_of_losing_the_frame(self):
        from PIL import Image
        img = Image.new("RGB", (480, 270))
        out = DO.draw(img, ("a", "b", "c", "d"), "/no/such/font.ttf", "idle")
        assert out.size == (480, 270)


SIZE = (1280, 720)
FOCAL, HAP = 24.0, 20.955
FX = FOCAL / HAP * SIZE[0]


class TestProject:
    """천장 영상의 로봇 표시 — 월드 점을 카메라 화면으로. USD 행벡터 규약 · 카메라는 로컬 −Z 를 본다."""

    def test_straight_down_camera_maps_world_axes_to_screen_axes(self):
        cam = DO.top_down(50.0, 40.0, 100.0)
        (c, right, up, behind) = DO.project([(50, 40, 0), (60, 40, 0), (50, 50, 0), (50, 40, 150)],
                                            cam, FOCAL, HAP, SIZE)
        assert c == (640.0, 360.0)
        assert abs(right[0] - (640 + FX * 0.1)) < 1e-6 and right[1] == 360.0      # +x → 오른쪽
        assert abs(up[1] - (360 - FX * 0.1)) < 1e-6                               # +y → 위
        assert behind is None                                                      # 카메라 뒤

    def test_fit_keeps_every_robot_position_on_screen(self):
        doc = slice_doc()
        doc["robots"]["1"] = [[100 + k, 60.0, 30.0] for k in range(21)]            # 멀리 떨어진 로봇
        tl = DO.Timeline.from_slice(doc)
        cam = DO.top_down(*DO.fit_top(tl.extent, SIZE, FOCAL, HAP))
        pts = [(x, y, 0.0) for rows in doc["robots"].values() for _, x, y in rows]
        for u, v in DO.project(pts, cam, FOCAL, HAP, SIZE):
            assert 0 <= u <= SIZE[0] and 0 <= v <= SIZE[1]


class TestTopView:
    def test_fleet_totals_sum_every_robot(self):
        tl = DO.Timeline.from_slice(slice_doc())
        head, right = tl.top_lines({"0": 14, "1": 14}, window_clock_s=12.0, n_robots=2)
        assert "AMR 2대" in head and "00:12 / 00:15" in head
        assert "완료 운행 1회" in right and "토트 3개" in right

    def test_packing_stations_are_labelled_where_the_totes_go(self):
        tl = DO.Timeline.from_slice(slice_doc())
        assert tl.stations == {"포장대 1": (6.1, 5.5)}

    def test_robots_are_painted_in_their_phase_colour(self):
        from PIL import Image
        img = Image.new("RGB", SIZE, (40, 40, 40))
        marks = [DO.Mark(num=1, u=300.0, v=300.0, hu=12.0, hv=0.0, key="carrying", follow=True),
                 DO.Mark(num=2, u=900.0, v=400.0, hu=0.0, hv=-12.0, key="idle", follow=False)]
        out = DO.draw_top(img, marks, ("head", "right"), None, stations=[("Packing 1", 640.0, 100.0)], lang="en")
        assert out.size == SIZE
        assert out.getpixel((300 - 5, 300 + 5)) == DO.PHASE_RGB["carrying"]


class TestNames:
    def test_known_station_names_become_readable(self):
        assert DO.label("aisle_buf[0]") == "통로 버퍼 1"
        assert DO.label("packing[2]") == "포장대 3"
        assert DO.label("mystery") == "mystery"
