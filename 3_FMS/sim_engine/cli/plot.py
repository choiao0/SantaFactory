# -*- coding: utf-8 -*-
import os

import numpy as np

from .common import OUT

def plot_heat(a, kernel, ctx, tag, tasks_per_h):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9.5, 8.5))
    vc = kernel.visit_count
    hm = np.where(vc > 0, vc, np.nan)
    ax.imshow(np.where(ctx.free, 1.0, 0.25), cmap="gray", vmin=0, vmax=1, origin="lower")
    im = ax.imshow(hm, cmap="inferno", origin="lower", alpha=0.9)
    plt.colorbar(im, ax=ax, shrink=0.75, label="cell visits")
    st_r = [rc[0] for rc in ctx.st_cell.values()]
    st_c = [rc[1] for rc in ctx.st_cell.values()]
    ax.scatter(st_c, st_r, s=8, c="#27ae60", marker="s", alpha=0.6)
    ax.set_title(f"sim_v2 traffic — {a.variant} ({a.flow}), {a.n_robots} robots, "
                 f"{a.n_orders} orders ({tasks_per_h:.0f} tasks/h)")
    plt.tight_layout()
    png = os.path.join(OUT, "results", tag + "_heat.png")
    plt.savefig(png, dpi=110)
    print(f"[4] 저장: {os.path.basename(png)}")
