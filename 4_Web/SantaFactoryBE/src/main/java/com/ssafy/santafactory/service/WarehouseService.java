package com.ssafy.santafactory.service;

import com.ssafy.santafactory.dto.warehouse.WarehouseCreateRequest;
import com.ssafy.santafactory.dto.warehouse.WarehouseResponse;
import com.ssafy.santafactory.entity.member.Member;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.global.auth.AuthenticatedMember;
import com.ssafy.santafactory.global.auth.OwnershipGuard;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.repository.MemberRepository;
import com.ssafy.santafactory.repository.WarehouseRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@Service
@RequiredArgsConstructor
public class WarehouseService {

    private final WarehouseRepository warehouseRepository;
    private final MemberRepository memberRepository;
    private final OwnershipGuard ownershipGuard;

    /**
     * 운영 조건을 새 창고 행으로 저장한다. 견적 요청은 이 id 를 들고 온다.
     *
     * <p>소유자를 세션 회원으로 붙인다 — 요청에서 받지 않는다. 받으면 남의 소유로 만들 수 있다.
     */
    @Transactional
    public WarehouseResponse create(WarehouseCreateRequest request, AuthenticatedMember me) {
        Member owner = memberRepository.findById(me.id())
                .orElseThrow(() -> new GlobalException(ErrorCode.UNAUTHORIZED));
        Warehouse saved = warehouseRepository.save(Warehouse.create(
                request.nameOrDefault(),
                request.widthOrDefault(),
                request.lengthOrDefault(),
                request.workerCount(),
                request.inboundStart(),
                request.inboundEnd(),
                request.outboundStart(),
                request.outboundEnd(),
                request.inboundAvg(),
                request.outboundAvg(),
                request.outboundRateOrDefault(),
                request.targetThroughputOrDefault(),
                request.targetUtilizationOrDefault(),
                request.budgetLimit()));
        saved.assignTo(owner);
        log.info("창고 생성: warehouseId={}, memberId={}, 작업자 {}명, 출고 {}건/일, 목표 처리율 {}%, 예산 {}원",
                saved.getId(), owner.getId(), saved.getWorkerCount(), saved.getOutboundAvg(),
                saved.getTargetThroughput(), saved.getBudgetLimit());
        return WarehouseResponse.from(saved);
    }

    /** 남의 창고는 없는 것처럼 404 를 준다 — 이유는 OwnershipGuard 참고. */
    @Transactional(readOnly = true)
    public WarehouseResponse get(Long warehouseId, AuthenticatedMember me) {
        Warehouse warehouse = warehouseRepository.findById(warehouseId)
                .orElseThrow(() -> new GlobalException(ErrorCode.WAREHOUSE_NOT_FOUND));
        ownershipGuard.checkWarehouse(warehouse, me);
        return WarehouseResponse.from(warehouse);
    }

    /** 내 창고 목록. 관리자는 전체를 본다. */
    @Transactional(readOnly = true)
    public List<WarehouseResponse> list(AuthenticatedMember me) {
        List<Warehouse> warehouses = me.isAdmin()
                ? warehouseRepository.findAll()
                : warehouseRepository.findByMemberIdOrderByIdAsc(me.id());
        return warehouses.stream().map(WarehouseResponse::from).toList();
    }
}
