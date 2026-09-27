-- 물리 검증 중복 요청 가드 (S15P21A106-265). 결과가 오기 전에는 "요청했다" 를 알 방법이 없어
-- 새로고침 뒤 다시 누르면 10분짜리 Isaac 작업이 한 번 더 큐에 쌓였다. 발행 시각을 남겨 막는다.
ALTER TABLE estimates
    ADD COLUMN verify_requested_at TIMESTAMP;
