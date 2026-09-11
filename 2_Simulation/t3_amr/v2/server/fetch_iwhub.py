"""Isaac 공식 에셋에서 idealworks iw.hub 로봇을 받는다 (공개 S3, 인증 불필요)."""
import urllib.request, urllib.parse, xml.etree.ElementTree as ET, os, concurrent.futures
B = "https://omniverse-content-production.s3-us-west-2.amazonaws.com"
PREFIX = "Assets/Isaac/6.0/Isaac/Robots/Idealworks/iwhub/"
# [patch_fetch_dest] 받는 자리는 $ROBOT 에서 끌어온다 — 경로를 두 번 정의하지 않는다.
#   예전에는 "~/khs/wh/warehouse/robots/iwhub/" 가 박혀 있었다. 팀 저장소로
#   옮기면서 $W 가 바뀌자 옛 자리에 받고 새 자리는 계속 비어 있었다
#   (2026-09-11). main.py 가 검사하는 경로와 같은 곳에 받아야 한다.
def _dest():
    import sys as _s
    if os.environ.get("IWHUB_DEST"):
        return os.path.expanduser(os.environ["IWHUB_DEST"]), "$IWHUB_DEST"
    if os.environ.get("ROBOT"):                 # paths.sh 가 정한 자리 (정답)
        return os.path.dirname(os.path.expanduser(os.environ["ROBOT"])), "$ROBOT"
    if os.environ.get("WAREHOUSE"):
        return os.path.join(os.path.expanduser(os.environ["WAREHOUSE"]),
                            "robots", "iwhub"), "$WAREHOUSE"
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))            # v2/server/ -> 저장소 루트
    return os.path.join(root, "robots", "iwhub"), "저장소 루트 역산"


DEST, _WHY = _dest()
DEST = DEST.rstrip("/") + "/"
print(f"[iwhub] 받을 자리: {DEST}   (출처: {_WHY})", flush=True)
if not os.environ.get("ROBOT") and not os.environ.get("IWHUB_DEST"):
    print("[iwhub] ★ $ROBOT 가 없습니다 — `source paths.sh` 를 먼저 하거나\n"
          "        IWHUB_DEST=<경로> 로 직접 주세요. 지금 자리가 맞는지 확인하세요.",
          flush=True)
if os.path.isfile(os.path.join(DEST, "iw_hub.usd")):
    print("[iwhub] 이미 있습니다 — 없는 파일만 채웁니다.", flush=True)
NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"

def keys():
    out, tok = [], None
    while True:
        u = f"{B}/?list-type=2&prefix={urllib.parse.quote(PREFIX)}&max-keys=1000"
        if tok: u += "&continuation-token=" + urllib.parse.quote(tok)
        with urllib.request.urlopen(u, timeout=60) as r: root = ET.fromstring(r.read())
        for c in root.findall(NS + "Contents"):
            k = c.find(NS + "Key").text
            if not k.endswith("/") and "/.thumbs/" not in k: out.append(k)
        if root.findtext(NS + "IsTruncated") == "true": tok = root.findtext(NS + "NextContinuationToken")
        else: break
    return out

def dl(k):
    p = os.path.join(DEST, k[len(PREFIX):])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    if os.path.exists(p) and os.path.getsize(p) > 0: return "skip"
    try:
        urllib.request.urlretrieve(f"{B}/{urllib.parse.quote(k)}", p); return "ok"
    except Exception as e: return f"ERR {k}: {e}"

ks = keys()
print(f"[iwhub] {len(ks)}개 -> {DEST}", flush=True)
ok = skip = err = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=24) as ex:
    for r in ex.map(dl, ks):
        if r == "ok": ok += 1
        elif r == "skip": skip += 1
        else:
            err += 1
            if err <= 5: print(r, flush=True)
print(f"[iwhub] ok={ok} skip={skip} err={err}", flush=True)
