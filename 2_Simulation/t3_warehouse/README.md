# T3 — 창고 씬 빌더 (그리드 → Isaac USD)

"그리드가 곧 씬"이 원칙: 맵(`../t3_warehouse_map/map/`)의 occupancy grid와 랙 좌표를
그대로 Isaac USD 씬으로 세운다. DES와 SIL이 단일 소스를 공유하는 구조의 물리 실체.
콜라이더는 전부 그리드 rect에서 나오고, 에셋은 시각 전용이다.

## 파일

| 파일 | 역할 |
|---|---|
| `build_scene.py` | 씬 빌더 — 그리드→벽·작업대, 랙 조립, 화물 드레싱, omap V&V, 스크린샷 |
| `roof_structure.py` | 박공지붕·상부 철골·H형강 기둥 모듈 (DXF 치수선 실측 기하) |
| `warehouse_scene.usd` | 산출 씬 — 커밋본 그대로 열림 (에셋은 NVIDIA S3 원격 참조, 383KB) |
| `view_scene.py` | WebRTC 스트리밍 뷰어 (헤드리스 서버 관전용) |
| `http_stream.py` | TCP 전용 HTTP MJPEG 관전 경로 — UDP 차단망(교육장 내부망) 대응 |
| `export_replay.py` | 맵 → `../isaac_export_t3/` 재생 데이터 생성 (isaac_replay 포맷) |
| `out/scene_*.png` | 검수 스크린샷 (외관·트러스·통로·스테이션·사무실 등) |

## 실행

```bash
# 씬 열람만 (빌드 불필요 — 커밋된 usd 사용)
cd <isaacsim> && ./python.sh <repo>/2_Simulation/t3_warehouse/view_scene.py
# 접속: Isaac Sim WebRTC Streaming Client → 서버 IP (동시 1인스턴스 주의)
# UDP 차단망(교육장 내부망 — tailscale이 DERP/TCP 릴레이로 떨어지는 환경)에서는
# WebRTC 대신 브라우저로 http://<서버IP>:8211/  (TCP MJPEG ~6fps, 관전 전용)

# 씬 재생성 (맵 산출물 갱신 시)
cd <repo>/2_Simulation/t3_warehouse_map/map && python warehouse_layout_v5_5_final.py
cd <isaacsim> && ./python.sh <repo>/2_Simulation/t3_warehouse/build_scene.py
```

## 구성 요소

- **건물** (설계도 DXF 치수선 실측): 처마 +9.0m, 박공지붕 i=15%(릿지면 ~+14.5m),
  K1 트러스 15프레임(6m 간격) + 퍼린 + 단부 X-브레이싱, 릿지 환기 모니터 4.5m,
  릿지 지지 H형강 기둥 12개(+11.0m, columns.npy 실기둥 중심). 외벽 샌드위치 패널
- **랙** (rack_units, 세로형 더블로우): NVIDIA 랙 부품 z 90° 회전 조립, 빔 2단
  (1.35/2.7 — 층간 여유 0.97m로 화물 관통 원천 차단)
- **화물** (운영 모델): 바닥 파렛트 밴드(셀값 6)는 랩핑 재고 더미 최대 4단,
  랙은 피킹 낱박스 1,923점(슬롯별 채움 45~90% 편차) — 결정적 의사난수 배치
- **스테이션**: 작업대 16개소 = 투명 그리드 콜라이더 + `packing_table` 에셋
  (내장 콜라이더 비활성 — 콜라이더 단일 소스 유지), 지게차 1대(인바운드 밴드)
- **사무실 2개소**: 파티션·모니터·철제 책상·강관 의자·캐비닛·마커보드 등 가구
  186점 (시각 전용, V&V에서 사무실 마스크 제외)
- **충전 스테이션 6기** (stations.json charger): 동벽 벽걸이 캐비닛·LED·베이 도장 —
  도킹 셀은 자유 공간이라 실물은 벽 팽창역 안 시각 전용(collide=False)
- **도어 4개소** (서·동 박공벽): 롤업 셔터 **폐쇄 상태** + 하우징·잼 포스트·상부 메꿈.
  그리드의 문 구간이 벽 라미나로 봉인돼 있어(실측) 셔터 폐쇄가 콜라이더와 정확히
  일치 — 라이다에 문이 벽으로 잡히는 게 폐쇄 셔터의 실제 물리
- **스테이션 앵커 46개**: stations.json 전 지점 = `/World/anchors/<type>_<i>` Xform.
  재생기·warehouse_sim·FMS가 좌표를 씬에서 직접 질의하는 표준 통로
- 설계도의 메자닌(+4.5m)은 **범위 외 확정** — 지지 기둥이 그리드(2D 단일 소스)를
  바꾸므로 미구현. AMR은 지면 주행·라이다 밴드 z 0.2~1.2라 운영상 무관
- **V&V**: `isaacsim.asset.gen.omap`으로 씬→점유맵 역생성 후 원 그리드와 diff —
  현행: 벽·컨베이어·작업대·파렛트 재현율 100.0% · 랙 풋프린트 점유 93.3% ·
  풋프린트 밖 오검출 0셀. 빌드 시 자동 실행

## 재생 (그리드 시뮬 검증 재생기 연동)

`../isaac_replay.py`(재생기)의 홈서버 확장 — 실물 씬 안에서 궤적 재생 + WebRTC:

```bash
./python.sh 2_Simulation/isaac_replay.py --export-dir 2_Simulation/isaac_export_t3 \
    --stage 2_Simulation/t3_warehouse/warehouse_scene.usd --livestream --loop
```

- `../isaac_export_t3/`는 `export_replay.py` 산출(스테이션 미션 6건, A* 침범 0 자가검증)
- sim_v1 익스포트를 쓰려면 `--export-dir`만 바꾸면 됨 (포맷 동일)

## 남은 것 (T3 본편)

iw.hub + 라이다 투입(warehouse_sim.py), 스테이션 왕복 order 연쇄, 리프트 도킹 1장면,
사이클 타임 분해 + 도킹 시간 분포 실측(DES 환류).
