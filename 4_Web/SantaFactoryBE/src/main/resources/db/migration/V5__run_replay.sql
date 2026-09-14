-- 견적 run 의 앞 구간 리플레이 (S15P21A106-205).
-- 궤적은 run 마다 다르므로 simscenarios 에, 맵(scene)은 대수와 무관하게 같으므로 estimates 에 한 벌만 둔다.
-- 나누지 않으면 143 KB 짜리 scene 이 run 수만큼(최대 28번) 중복 저장된다.
ALTER TABLE simscenarios
    ADD COLUMN replay_json TEXT;

ALTER TABLE estimates
    ADD COLUMN replay_scene_json TEXT;
