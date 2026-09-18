# A 복구 기동이 **평형에서 실제로 빠져나오나** — Isaac 없이 제어기만 돌린다.
# a6 실측 자세를 그대로 넣는다: along 37 mm · cross 211 mm · head -10.0도
import math, os, sys
sys.path.insert(0, os.path.join(os.environ["W"], "path"))
import pibt_core_v2                                    # noqa: F401
import isaac_drive as D                                # noqa: E402

geom = D.RobotGeom(pitch=1.0, rear_len=1.11, front_len=0.39, width=0.80,
                   heading_offset=2)
DT = 1.0 / 60.0

def run(recover, T=30.0):
    os.environ["PIBT_RECOVER"] = "1" if recover else "0"
    import importlib; importlib.reload(D)
    s0, s1 = (46, 50, 0), (45, 50, 0)
    act = D.Action(agent=6, idx=0, kind=D.REVERSE, tick=651,
                   frm=s0, to=s1, cells=geom.swept_cells(s0, s1))
    c = D.MotionController(geom, D.Tolerance())
    c.begin(act)
    # a6 최종 자세를 재구성: 목표에서 along +37mm · cross +211mm · head -10도
    fx, fy = math.cos(c.tyaw) * c.sign, math.sin(c.tyaw) * c.sign
    px = c.tx - 0.037 * fx + 0.211 * fy
    py = c.ty - 0.037 * fy - 0.211 * fx
    pose = [px, py, c.tyaw + math.radians(10.0)]
    t = 0.0; best = 1e9
    while t < T:
        v, w = c.update(tuple(pose), DT)
        # 단순 적분 (물리 없이 명령이 무엇을 만드는지만 본다)
        pose[2] += w * DT
        pose[0] += v * math.cos(pose[2]) * DT
        pose[1] += v * math.sin(pose[2]) * DT
        t += DT
        e = math.hypot(c.tx - pose[0], c.ty - pose[1])
        best = min(best, e)
        if c.at_target(tuple(pose)):
            return ("★ 빠져나왔다", t, e * 1000, c.recovered, best * 1000)
    e = math.hypot(c.tx - pose[0], c.ty - pose[1])
    return ("☹ 갇혔다", t, e * 1000, c.recovered, best * 1000)

print(f"  {'판':<8} {'결과':<12} {'시간':>7} {'최종오차':>10} {'복구':>5} {'최소오차':>10}")
for lab, rec in (("끔 (전)", False), ("켬 (후)", True)):
    r, t, e, n, b = run(rec)
    print(f"  {lab:<8} {r:<12} {t:6.1f}s {e:9.1f}mm {n:5d} {b:9.1f}mm")
