import math, os, sys
sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                                    # noqa: F401
import isaac_drive as D                                # noqa: E402
geom = D.RobotGeom(pitch=1.0, rear_len=1.11, front_len=0.39, width=0.80, heading_offset=2)
DT = 1.0 / 60.0
os.environ["PIBT_RECOVER"] = "1"
s0, s1 = (46, 50, 0), (45, 50, 0)
act = D.Action(agent=6, idx=0, kind=D.REVERSE, tick=651, frm=s0, to=s1,
               cells=geom.swept_cells(s0, s1))
c = D.MotionController(geom, D.Tolerance()); c.begin(act)
fx0, fy0 = math.cos(c.tyaw) * c.sign, math.sin(c.tyaw) * c.sign
pose = [c.tx - 0.037 * fx0 + 0.211 * fy0, c.ty - 0.037 * fy0 - 0.211 * fx0,
        c.tyaw + math.radians(10.0)]
print(f"  {'t':>5} {'along':>8} {'cross':>9} {'head':>7} {'v':>7} {'w':>8} {'복구':>5}")
t = 0.0
for i in range(int(12.0 / DT)):
    v, w = c.update(tuple(pose), DT)
    if i % 45 == 0:
        x, y, yaw = pose
        fx, fy = math.cos(yaw) * c.sign, math.sin(yaw) * c.sign
        dx, dy = c.tx - x, c.ty - y
        al, cr = dx * fx + dy * fy, fx * dy - fy * dx
        hd = math.degrees(D.wrap(c.tyaw - yaw))
        print(f"  {t:5.2f} {al*1000:7.1f}m {cr*1000:8.1f}m {hd:6.2f}° "
              f"{v:6.3f} {w:7.4f} {c._recov_n:5d}")
    pose[2] += w * DT
    pose[0] += v * math.cos(pose[2]) * DT
    pose[1] += v * math.sin(pose[2]) * DT
    t += DT
