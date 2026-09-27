-- 주문 리드타임 p90(초) — 판정 조건으로 쓰려면 run 마다 남아 있어야 한다 (S15P21A106-97).
-- 판정은 마지막 run 이 끝난 뒤 전 대수를 DB 에서 다시 읽어 한 번에 하므로(finalizeIfComplete),
-- 결과 수신 시점에만 들고 있다가 버리면 판정할 수 없다.
--
-- 명세 §1-2 의 kpi.lead_time_p90_s 를 그대로 담는다. 시뮬이 값을 안 주면 NULL 이고,
-- 그 run 은 리드타임 조건을 건너뛴다 — 없는 값으로 떨어뜨리지 않는다.
ALTER TABLE simscenarios
    ADD COLUMN lead_time_p90 DOUBLE PRECISION;
