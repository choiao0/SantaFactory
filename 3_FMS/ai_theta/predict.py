# -*- coding: utf-8 -*-
"""맵 특징으로 θ 를 예측한다 — 설정 하나로 켜고 끈다 (S15P21A106-206).

## 기본은 꺼져 있다

환경변수 `THETA_MODEL` 이 비어 있으면 이 모듈은 **한 번도 호출되지 않는다.** 견적·검증 런은
지금까지와 **비트 단위로 같은** 고정 θ(`theta_wallA_r20_c6_v36.json`)로 돈다. 켤 때만
모델이 끼어든다 (`section_limit`(-193) 과 같은 방식).

예측이 실패하면 — 모델 파일이 없거나, 맵 특징을 못 뽑거나, sklearn 이 없거나 — **조용히
고정 θ 로 떨어진다.** 견적이 모델 때문에 멈추면 안 된다.

## 무엇을 예측하나

    입력   맵 특징 6개 (통로수 · 중심간격 · 통로길이 · 통행칸 · 대수 · 상대부하)
    출력   θ 11축

모델 둘을 곱해 **기대 처리량**을 최대화하는 θ 를 고른다:

    기대 처리량 = P(완주 | 맵, θ) x 처리량비(맵, θ)

처리량만 최대화하면 교착 벼랑으로 간다 — 홀드아웃 실측에서 완주율 18 %, 20창고 중 9곳이
0 % 였고 공통 θ 보다 **−61.7 %**(p=0.004) 였다. 곱으로 바꾸면 완주율 72 %, 공통 θ 대비
**+40.9 %**(15/20, p=0.041).

## 최적화는 경사상승이 아니라 샘플링이다

같은 MLP 로 둘을 비교했더니 무작위 10만 개 샘플링이 시작점 40개 경사상승보다 나았다
(기대 처리량 417.3 → 425.2). 경사상승이 국소 봉우리에 걸린다. 샘플링은 구현도 단순하고
모델 종류를 안 가린다(XGBoost 처럼 미분 안 되는 것도 그대로 쓴다).

## 한계 — 합성 창고 전용

`aisles` · `pitch` · `length` 는 합성 창고의 **생성 파라미터**라 맵 이름(`r11p5l17`)에서
읽는다. 실제 고객 도면에는 그런 이름이 없고, 랙 배치가 불규칙하면 값 자체가 정의되지 않는다.
특징을 도면에서 재는 것으로 갈아끼우는 것이 다음 과제다.

조건도 **개방(`aisle_block=0`)** 에서 학습했다. 운영(차단)에는 완주 데이터가 아직 없다.
"""
import json
import os
import re
import tempfile

MODEL_ENV = "THETA_MODEL"
NAME_RE = re.compile(r"r(\d+)p(\d+)l(\d+)")
FEATS = ["aisles", "pitch", "length", "free", "fleet", "load_frac"]
_CACHE = {}


def features_from_name(name, free=None, fleet=None, load_frac=1.0):
    """합성 창고 이름에서 기하 특징을 읽는다 — `r11p5l17` = 통로 11 · 간격 5 · 길이 17."""
    m = NAME_RE.search(str(name))
    if not m:
        return None
    f = {"aisles": float(m.group(1)), "pitch": float(m.group(2)),
         "length": float(m.group(3)), "load_frac": float(load_frac)}
    if free is None or fleet is None:
        d = _design().get(os.path.basename(str(name)))
        if d is None:
            return None
        f["free"] = float(d["free"]) if free is None else float(free)
        f["fleet"] = float(d["fleet"]) if fleet is None else float(fleet)
    else:
        f["free"], f["fleet"] = float(free), float(fleet)
    return f


def features_from_map(map_dir=None, fleet=None, load_frac=1.0):
    """도면 격자에서 직접 잰다 — 이름이 없어도 된다 (공식 맵·실제 도면용).

    `map_features.extract` 가 차단/개방 차이로 랙 사이 통로를 찾아 통로 수·간격·길이를 센다.
    합성 창고 112개에서 이름의 정답과 112/112 일치했다. `map_dir=None` 이면 공식 맵이다.

    **주의** — 공식 맵은 통행 칸이 9,333 으로 학습 범위(1,050~2,217) 밖이다. θ 는 나오지만
    그 값이 좋다는 보장은 없다 (차단 조건 1런 실측에서 고정 θ 대비 -7.9 %).
    """
    import map_features
    f = map_features.extract(map_dir)
    if f is None or fleet is None:
        return None
    return {"aisles": f["aisles"], "pitch": f["pitch"], "length": f["length"],
            "free": f["free"], "fleet": float(fleet), "load_frac": float(load_frac)}


def _design():
    """합성 창고 설계표 — free·fleet 을 이름만으로 채울 때 쓴다."""
    if "design" in _CACHE:
        return _CACHE["design"]
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "infra", "out", "theta_open", "design.json")
    try:
        _CACHE["design"] = {d["name"]: d for d in json.load(open(path, encoding="utf-8"))}
    except Exception:
        _CACHE["design"] = {}
    return _CACHE["design"]


def _load(model_path):
    if model_path in _CACHE:
        return _CACHE[model_path]
    from joblib import load                      # 늦게 부른다 — 꺼져 있으면 의존성도 없다
    _CACHE[model_path] = load(model_path)
    return _CACHE[model_path]


def predict(features, model_path=None, samples=100000, seed=0):
    """맵 특징 → θ 11축. 실패하면 None 을 돌려준다 (호출부가 고정 θ 로 떨어진다)."""
    model_path = model_path or os.environ.get(MODEL_ENV, "")
    if not model_path or not os.path.exists(model_path):
        return None
    if not all(k in features for k in FEATS):
        return None
    try:
        import numpy as np
        M = _load(model_path)
    except Exception:
        return None

    cols, cont, cats = M["cols"], M["cont"], M["cats"]
    ranges, cat_values = M["ranges"], M["cat_values"]
    rng = np.random.default_rng(seed)
    lo = np.array([ranges[c][0] for c in cont])
    hi = np.array([ranges[c][1] for c in cont])

    base = np.zeros(len(cols))
    for k, c in enumerate(cols):
        base[k] = float(features.get(c, 0.0))
    X = np.tile(base, (samples, 1))
    idx = [cols.index(c) for c in cont]
    cat_i = [cols.index(c) for c in cats]
    X[:, idx] = rng.uniform(lo, hi, size=(samples, len(cont)))
    cand_cat = np.column_stack([rng.choice(cat_values[c], samples) for c in cats])
    X[:, cat_i] = cand_cat

    try:
        p = M["clf"].predict_proba(X)[:, 1]      # 완주 확률
        r = M["reg"].predict(X)                  # 처리량비
    except Exception:
        return None
    j = int((p * r).argmax())                    # 기대 처리량이 최대인 후보

    theta = {c: float(X[j, cols.index(c)]) for c in cont}
    theta.update({c: int(cand_cat[j, k]) for k, c in enumerate(cats)})
    theta["_pred_complete"] = round(float(p[j]), 4)   # 진단용 — 시뮬은 무시한다
    theta["_pred_ratio"] = round(float(r[j]), 4)
    return theta


def write_theta(theta, out_dir=None):
    """θ 를 임시 JSON 으로 쓰고 **절대경로**를 돌려준다.

    상대경로를 돌려주면 시뮬이 `sim_engine/` 에서 돌아 파일을 못 찾고, 그 런이 조용히
    교착으로 집계된다 (실제로 600런을 그렇게 날린 적이 있다).
    """
    d = out_dir or tempfile.mkdtemp(prefix="theta_pred_")
    os.makedirs(d, exist_ok=True)
    path = os.path.abspath(os.path.join(d, "theta_pred.json"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump({k: v for k, v in theta.items() if not k.startswith("_")},
                  f, ensure_ascii=False, indent=1)
    return path


def theta_file_for(map_name=None, fleet=None, load_frac=1.0, model_path=None,
                   out_dir=None, map_dir=None):
    """맵 → θ 파일 경로. 실패하면 None.

    `map_dir` 를 주면(또는 `map_name` 이 없으면) **도면 격자에서 직접 재고**, 합성 창고
    이름을 주면 이름에서 읽는다. 둘 다 없으면 공식 맵을 잰다.
    """
    if map_dir is not None or map_name is None:
        f = features_from_map(map_dir, fleet=fleet, load_frac=load_frac)
    else:
        f = features_from_name(map_name, fleet=fleet, load_frac=load_frac)
    if f is None:
        return None
    th = predict(f, model_path=model_path)
    return write_theta(th, out_dir) if th else None


if __name__ == "__main__":
    import argparse
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    p = argparse.ArgumentParser(
        description="맵으로 θ 예측 — 인자 없으면 공식 맵을 격자에서 잰다")
    p.add_argument("map", nargs="?", default=None,
                   help="합성 창고 이름(r11p5l17) 또는 맵 폴더 경로. 생략하면 공식 맵")
    p.add_argument("--fleet", type=float, default=None,
                   help="대수. 공식 맵·폴더 지정 시에는 필수 (합성 이름이면 설계표에서 읽는다)")
    p.add_argument("--load-frac", type=float, default=1.0, dest="load_frac")
    p.add_argument("--model", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "model", "theta_model.joblib"))
    p.add_argument("--out", default=None, help="θ 를 쓸 폴더 (없으면 출력만)")
    a = p.parse_args()

    # 이름이면 이름에서, 폴더이거나 생략이면 격자에서 잰다
    if a.map and not os.path.isdir(a.map) and NAME_RE.search(a.map):
        label = a.map
        feat = features_from_name(a.map, fleet=a.fleet, load_frac=a.load_frac)
    else:
        label = a.map or "공식 맵 (3_FMS/map)"
        if a.fleet is None:
            raise SystemExit("대수를 지정할 것 — 도면에서는 대수를 잴 수 없다 (--fleet 20)")
        feat = features_from_map(a.map, fleet=a.fleet, load_frac=a.load_frac)
    if feat is None:
        raise SystemExit("맵 특징을 못 뽑았다 — 경로나 이름을 확인할 것")

    print("%s" % label)
    print("  " + " · ".join("%s %g" % (k, feat[k]) for k in FEATS))
    th = predict(feat, model_path=a.model)
    if th is None:
        raise SystemExit("예측 실패 — 모델 파일(%s)을 확인할 것" % a.model)
    print()
    print("예측 θ")
    for k, v in th.items():
        if not k.startswith("_"):
            print("  %-20s %s" % (k, ("%.4f" % v) if isinstance(v, float) else v))
    print()
    print("모델 예측 완주확률 %.0f%% · 처리량비 %.3f"
          % (100 * th["_pred_complete"], th["_pred_ratio"]))
    if a.out:
        print("  %s" % write_theta(th, a.out))
