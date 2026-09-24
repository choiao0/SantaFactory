package com.ssafy.santafactory.repository;

import com.ssafy.santafactory.entity.estimate.Estimate;
import java.util.List;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface EstimateRepository extends JpaRepository<Estimate, Long> {

    /** 견적 목록 — 최근순 (명세 §3-1 GET /estimates). 관리자만 쓴다. */
    Page<Estimate> findAllByOrderByCreatedAtDesc(Pageable pageable);

    /**
     * 내 견적 — 최근순.
     *
     * <p>견적에 소유자 컬럼을 두지 않고 창고를 거쳐 찾는다. 컬럼을 중복으로 두면 두 곳이 어긋날
     * 여지가 생기고, 견적은 자기 창고에만 만들 수 있으므로 창고의 주인이 곧 견적의 주인이다.
     */
    Page<Estimate> findByWarehouseMemberIdOrderByCreatedAtDesc(Long memberId, Pageable pageable);

    /** 관리자 목록용 집계. 회원마다 count 쿼리를 날리지 않게 한 번에 묶는다(N+1 방지). */
    @Query("select new com.ssafy.santafactory.repository.MemberCount(e.warehouse.member.id, count(e)) "
            + "from Estimate e where e.warehouse.member is not null group by e.warehouse.member.id")
    List<MemberCount> countGroupedByMember();

    /**
     * 관리자 전체 목록 — 행마다 회사·담당자를 보여줘야 해서 창고와 회원을 함께 가져온다.
     * 지연 로딩에 맡기면 행마다 두 번씩 더 조회한다(N+1).
     */
    @Query(value = "select e from Estimate e left join fetch e.warehouse w left join fetch w.member",
            countQuery = "select count(e) from Estimate e")
    Page<Estimate> findAllWithOwner(Pageable pageable);

    /** 한 회원의 견적만 — 관리자 화면에서 회원 카드를 눌렀을 때 (S15P21A106-271). */
    @Query(value = "select e from Estimate e left join fetch e.warehouse w left join fetch w.member m"
            + " where m.id = :memberId",
            countQuery = "select count(e) from Estimate e where e.warehouse.member.id = :memberId")
    Page<Estimate> findAllWithOwnerByMember(@Param("memberId") Long memberId, Pageable pageable);
}
