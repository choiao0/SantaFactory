package com.ssafy.santafactory.service.estimate.quote;

import com.ssafy.santafactory.dto.estimate.EstimateDetailResponse;
import com.ssafy.santafactory.dto.warehouse.WarehouseResponse;

/** 견적서를 만들 재료 — 상세 응답과 그 견적의 창고. 한 트랜잭션에서 같이 읽는다 (S15P21A106-236). */
public record QuoteSource(EstimateDetailResponse detail, WarehouseResponse warehouse) {
}
