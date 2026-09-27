package com.ssafy.santafactory.repository;

import com.ssafy.santafactory.entity.warehouse.Warehouse;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface WarehouseRepository extends JpaRepository<Warehouse, Long> {

    /** 내 창고 목록. */
    List<Warehouse> findByMemberIdOrderByIdAsc(Long memberId);

    /** 주인 없는 창고 — 시드에서 온 것뿐이다. 계정 초기화가 데모 회원에게 귀속시킨다. */
    List<Warehouse> findByMemberIsNull();

    /** 관리자 목록용 집계. 회원마다 count 쿼리를 날리지 않게 한 번에 묶는다(N+1 방지). */
    @Query("select new com.ssafy.santafactory.repository.MemberCount(w.member.id, count(w)) "
            + "from Warehouse w where w.member is not null group by w.member.id")
    List<MemberCount> countGroupedByMember();
}
