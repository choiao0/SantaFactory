package com.ssafy.santafactory.controller;

import com.ssafy.santafactory.dto.warehouse.WarehouseCreateRequest;
import com.ssafy.santafactory.dto.warehouse.WarehouseResponse;
import com.ssafy.santafactory.global.auth.AuthenticatedMember;
import com.ssafy.santafactory.global.common.ApiResponse;
import com.ssafy.santafactory.service.WarehouseService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "창고", description = "견적의 입력이 되는 창고 운영 조건")
@RestController
@RequestMapping("/api/warehouses")
@RequiredArgsConstructor
public class WarehouseController {

    private final WarehouseService warehouseService;

    @Operation(summary = "창고 운영 조건 생성",
            description = "작업자 수·입출고 시간대·물량·목표·예산을 저장한다. 응답의 warehouse_id 를 견적 요청에 넣는다.")
    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public ApiResponse<WarehouseResponse> create(@Valid @RequestBody WarehouseCreateRequest request,
                                                 @AuthenticationPrincipal AuthenticatedMember me) {
        return ApiResponse.onSuccess(warehouseService.create(request, me));
    }

    @Operation(summary = "내 창고 목록", description = "관리자는 전체를 본다")
    @GetMapping
    public ApiResponse<List<WarehouseResponse>> list(@AuthenticationPrincipal AuthenticatedMember me) {
        return ApiResponse.onSuccess(warehouseService.list(me));
    }

    @Operation(summary = "창고 운영 조건 조회",
            description = "01 화면 폼 초기값. 남의 창고는 없는 것처럼 404 를 준다.")
    @GetMapping("/{warehouseId}")
    public ApiResponse<WarehouseResponse> get(@PathVariable Long warehouseId,
                                              @AuthenticationPrincipal AuthenticatedMember me) {
        return ApiResponse.onSuccess(warehouseService.get(warehouseId, me));
    }
}
