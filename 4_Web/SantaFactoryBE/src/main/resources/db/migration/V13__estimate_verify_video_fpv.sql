-- 두 번째 시점을 측면에서 1인칭으로 바꾼다 — 이름이 뜻과 어긋나면 나중에 읽는 사람이 헷갈린다
-- (S15P21A106-266). V10 은 이미 적용돼 있어 손대지 않고 여기서 이름만 바꾼다.
ALTER TABLE estimates RENAME COLUMN verify_video_side_url TO verify_video_fpv_url;
