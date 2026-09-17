-- 물리 검증(Isaac) 결과 (S15P21A106-236). 결과 메시지(SIM_VERIFY_CONTRACT.md §3)에는 가동 로봇 수·종료 사유·
-- 경고·시뮬과 같은 14개 지표가 실려 오는데 지금까지는 영상 키(verify_video_url)만 남기고 버렸다.
-- 견적서 "권장 구성 물리 검증" 블록이 정상 종료 여부와 계산 예상 대비 차이를 보여 주므로 견적에 남긴다.
-- 비교에 쓰는 지표 3개만 담고(피크 10분 창이라 처리율 % 는 비교하지 않음), 재검증하면 덮어쓴다.
-- verify_warnings_json 이 NULL 이면 계산과 같은 조건에서 돈 것이다(계약 §3 fms.warnings).
ALTER TABLE estimates
    ADD COLUMN verify_run_id VARCHAR(64),
    ADD COLUMN verify_status VARCHAR(20),
    ADD COLUMN verify_reason VARCHAR(100),
    ADD COLUMN verify_error VARCHAR(500),
    ADD COLUMN verify_n_robots INTEGER,
    ADD COLUMN verify_robots_online INTEGER,
    ADD COLUMN verify_window_s INTEGER,
    ADD COLUMN verify_warnings_json TEXT,
    ADD COLUMN verify_throughput_orders_per_h DOUBLE PRECISION,
    ADD COLUMN verify_lead_time_p90_s DOUBLE PRECISION,
    ADD COLUMN verify_conflict_wait_ratio DOUBLE PRECISION,
    ADD COLUMN verified_at TIMESTAMP;
