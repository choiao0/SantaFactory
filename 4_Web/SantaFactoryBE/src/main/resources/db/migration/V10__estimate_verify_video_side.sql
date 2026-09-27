-- 물리 검증 영상을 시점별로 받는다 (S15P21A106-265). 기존 verify_video_url 은 상단 시점으로 남고,
-- 측면 시점이 새 열에 들어간다. 측면을 찍지 않은 회차는 NULL 이라 화면이 상단만 보여준다.
ALTER TABLE estimates
    ADD COLUMN verify_video_side_url VARCHAR(500);
