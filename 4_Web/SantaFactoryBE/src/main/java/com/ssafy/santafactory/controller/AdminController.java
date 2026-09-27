package com.ssafy.santafactory.controller;

import com.ssafy.santafactory.dto.admin.AdminEstimateResponse;
import com.ssafy.santafactory.dto.admin.AdminMemberResponse;
import com.ssafy.santafactory.global.common.ApiResponse;
import com.ssafy.santafactory.service.admin.AdminService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.web.PageableDefault;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 관리자 조회 (S15P21A106-186).
 *
 * <p>접근 제어는 {@code SecurityConfig} 가 경로 단위로 한다 —
 * {@code /api/admin/**} → {@code hasRole("ADMIN")}. 그래서 메서드마다 검사를 걸지 않는다.
 */
@Tag(name = "관리자", description = "고객사별 회원·견적 현황 (ADMIN 전용)")
@RestController
@RequestMapping("/api/admin")
@RequiredArgsConstructor
public class AdminController {

    private final AdminService adminService;

    @Operation(summary = "회원 목록",
            description = "회사·이름순. 행마다 등록한 창고 수와 요청한 견적 수가 붙는다.")
    @GetMapping("/members")
    public ApiResponse<List<AdminMemberResponse>> members() {
        return ApiResponse.onSuccess(adminService.members());
    }

    @Operation(summary = "전체 견적 목록",
            description = "기본 최근순(sort=createdAt,asc 로 오래된순). 고객 목록과 달리 회사·담당자·연락처를 "
                    + "함께 담는다 — \"오늘 어떤 회사가 뭘 신청했나\"를 보는 화면이다. "
                    + "memberId 를 주면 그 회원의 견적만 준다.")
    @GetMapping("/estimates")
    public ApiResponse<Page<AdminEstimateResponse>> estimates(
            @RequestParam(required = false) Long memberId,
            @PageableDefault(size = 20, sort = "createdAt", direction = Sort.Direction.DESC) Pageable pageable) {
        return ApiResponse.onSuccess(adminService.estimates(memberId, pageable));
    }
}
