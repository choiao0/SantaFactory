# -*- coding: utf-8 -*-
"""커널 토트 동승·서비스·완료 계약."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from kernel.core import FmsKernel, KernelConfig  # noqa: E402


def task(i, frm=(2, 2), to=(4, 4), order=None):
    return dict(id=i, order=i if order is None else order, kind="out",
                frm_name="aisle_buf[0]", to_name=f"packing[{i}]", frm=frm, to=to,
                created=0, assigned=None, completed=None)


def kernel(capacity=1, svc_per_tote=0, completed=None):
    free = np.ones((7, 7), dtype=bool)
    cfg = KernelConfig(heading=False, zone=False, capacity=capacity,
                       service_steps=4, svc_per_tote=svc_per_tote)
    callback = (lambda tk, t: completed.append((tk["id"], t)) or []) if completed is not None else None
    return FmsKernel(free, {"home": (2, 2)}, np.ones((7, 7, 4)), np.ones((7, 7)),
                     [(2, 2)], 1, cfg, on_task_completed=callback)


def test_same_buffer_totes_ride_and_complete_together():
    done = []
    k = kernel(capacity=3, svc_per_tote=5, completed=done)
    for tk in (task(1), task(2), task(3, frm=(3, 3))):
        k.submit_task(tk)
    k.dispatch(0)
    lead = k.robots[0]["task"]
    assert [x["id"] for x in lead["riders"]] == [2]
    assert lead["to"] == lead["riders"][0]["to"]
    assert k.robots[0]["svc_end"] == 14                       # 기본 4 + 2토트×5
    k._complete_drop(k.robots[0], 20)
    assert [x["id"] for x in k.tasks_done] == [1, 2]
    assert done == [(1, 20), (2, 20)] and k.trips == 1


def test_capacity_one_does_not_touch_waiting_task():
    k = kernel(capacity=1)
    a, b = task(1), task(2)
    k.submit_task(a)
    k.submit_task(b)
    k.dispatch(0)
    assert "riders" not in a and k.waiting == [b] and b["assigned"] is None
