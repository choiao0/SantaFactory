package com.ssafy.santafactory.repository;

/**
 * 회원별 개수 집계 결과. 관리자 목록이 회원마다 쿼리를 날리지 않게(N+1 방지) 한 번에 묶어 받는다.
 *
 * @param memberId 회원 id
 * @param count    그 회원의 창고 수 또는 견적 수
 */
public record MemberCount(Long memberId, long count) {
}
