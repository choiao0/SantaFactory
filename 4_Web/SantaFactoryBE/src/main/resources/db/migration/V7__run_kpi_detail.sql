-- run 별 시뮬 지표 7개 (S15P21A106-236). 시뮬은 14개 지표를 보내는데 지금까지는 4개만 남기고 버렸다.
-- 견적서의 "권장 구성 운영 예상"과 물리 검증 결과 비교의 "계산 예상" 값이 여기서 나오므로 run 마다 남아야 한다.
-- 명세 §1-2 kpi 의 키 이름을 그대로 컬럼명으로 쓴다. 시뮬이 값을 안 주면 NULL.
ALTER TABLE simscenarios
    ADD COLUMN orders_total INTEGER,
    ADD COLUMN orders_completed INTEGER,
    ADD COLUMN lead_time_mean_s DOUBLE PRECISION,
    ADD COLUMN queue_time_mean_s DOUBLE PRECISION,
    ADD COLUMN throughput_orders_per_h DOUBLE PRECISION,
    ADD COLUMN conflict_wait_ratio DOUBLE PRECISION,
    ADD COLUMN distance_total_m BIGINT;
