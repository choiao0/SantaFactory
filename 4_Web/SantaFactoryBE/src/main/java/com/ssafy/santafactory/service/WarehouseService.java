package com.ssafy.santafactory.service;

import com.ssafy.santafactory.dto.warehouse.WarehouseCreateRequest;
import com.ssafy.santafactory.dto.warehouse.WarehouseResponse;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import com.ssafy.santafactory.repository.WarehouseRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Slf4j
@Service
@RequiredArgsConstructor
public class WarehouseService {

    private final WarehouseRepository warehouseRepository;

    /** 운영 조건을 새 창고 행으로 저장한다. 견적 요청은 이 id 를 들고 온다. */
    @Transactional
    public WarehouseResponse create(WarehouseCreateRequest request) {
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
        log.info("창고 생성: warehouseId={}, 작업자 {}명, 출고 {}건/일, 목표 처리율 {}%, 예산 {}원",
                saved.getId(), saved.getWorkerCount(), saved.getOutboundAvg(),
                saved.getTargetThroughput(), saved.getBudgetLimit());
        return WarehouseResponse.from(saved);
    }

    @Transactional(readOnly = true)
    public WarehouseResponse get(Long warehouseId) {
        return warehouseRepository.findById(warehouseId)
                .map(WarehouseResponse::from)
                .orElseThrow(() -> new GlobalException(ErrorCode.WAREHOUSE_NOT_FOUND));
    }
}
