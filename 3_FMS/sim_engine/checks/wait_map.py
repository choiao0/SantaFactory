# -*- coding: utf-8 -*-
"""명시 주문 실행의 대기 지도와 후진 비율을 재는 회귀 도구.

사용(3_FMS/sim_engine):
  python checks/wait_map.py 12 42 orders.json --horizon=7200
  python checks/wait_map.py 20 101 orders.json --horizon=7200 -- --no-lanes --no-yield
"""
import argparse
import json
import os
import sys

import numpy as np

ENGINE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ENGINE_DIR)

from sim_v2_tasks import build, parse_args, run_ticks  # noqa: E402

CORNER_CELLS = {"south_west": (46, 31), "south_east": (46, 100),
                "north_west": (69, 31), "north_east": (69, 100)}


def corner_waits(wait_count, radius=3):
    """각 모서리 중심의 ±radius 정사각형 안 대기 틱."""
    h, w = wait_count.shape
    return {name: int(wait_count[max(0, r-radius):min(h, r+radius+1),
                                 max(0, c-radius):min(w, c+radius+1)].sum())
            for name, (r, c) in CORNER_CELLS.items()}


def save_png(path, free, wait_count, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9.5, 8.5))
    ax.imshow(np.where(free, 1.0, 0.25), cmap="gray", vmin=0, vmax=1, origin="lower")
    im = ax.imshow(np.where(wait_count > 0, wait_count, np.nan), cmap="magma",
                   origin="lower", alpha=0.9)
    plt.colorbar(im, ax=ax, shrink=0.75, label="navigation wait ticks")
    for name, (r, c) in CORNER_CELLS.items():
        ax.scatter(c, r, s=24, facecolors="none", edgecolors="#2ecc71")
        ax.text(c + 1, r + 1, name.replace("_", " "), fontsize=7, color="#2ecc71")
    ax.set_title(title)
    plt.tight_layout()
    plt.savefig(path, dpi=110)
    plt.close(fig)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("robots", type=int)
    p.add_argument("seed", type=int)
    p.add_argument("orders_file")
    p.add_argument("--horizon", type=int, default=7200)
    p.add_argument("--output", "-o", help="PNG 경로(기본 results/wait_map_*.png)")
    args, flags = p.parse_known_args(argv)
    sim = parse_args(["waitmap", str(args.robots), "0", str(args.seed), "1",
                      f"--orders-file={os.path.abspath(args.orders_file)}",
                      f"--horizon={args.horizon}", *flags])
    kernel, stream, ctx = build(sim)
    run_ticks(kernel, stream, sim.horizon)
    totals = kernel.totals()
    total_wait = int(kernel.wait_count.sum())
    assert total_wait == totals["wait"], (total_wait, totals["wait"])
    moves = totals["drive"]
    result = dict(robots=args.robots, seed=args.seed, orders_file=os.path.basename(args.orders_file),
                  horizon=args.horizon, total_wait_ticks=total_wait,
                  reverse_ratio=round(totals["rev"] / max(moves, 1), 6),
                  reverse_steps=int(totals["rev"]), drive_steps=int(moves),
                  corner_wait_ticks=corner_waits(kernel.wait_count))
    suffix = "_".join(x.lstrip("-").replace("=", "-") for x in flags) or "default"
    path = args.output or os.path.join(ENGINE_DIR, "results",
                                       f"wait_map_r{args.robots}_s{args.seed}_{suffix}.png")
    save_png(path, ctx.free, kernel.wait_count,
             f"wait map — {args.robots} robots, seed {args.seed}, wait {total_wait:,} ticks")
    result["png"] = os.path.relpath(path, ENGINE_DIR).replace("\\", "/")
    print("[WAIT_MAP] " + json.dumps(result, ensure_ascii=False, sort_keys=True))
    return result


if __name__ == "__main__":
    main()
