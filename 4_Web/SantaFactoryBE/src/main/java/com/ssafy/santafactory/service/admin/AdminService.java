package com.ssafy.santafactory.service.admin;

import com.ssafy.santafactory.dto.admin.AdminEstimateResponse;
import com.ssafy.santafactory.dto.admin.AdminMemberResponse;
import com.ssafy.santafactory.repository.EstimateRepository;
import com.ssafy.santafactory.repository.MemberCount;
import com.ssafy.santafactory.repository.MemberRepository;
import com.ssafy.santafactory.repository.WarehouseRepository;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import lombok.RequiredArgsConstructor;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 관리자 조회 (S15P21A106-186). 영업이 고객사별 신청 현황을 보는 화면의 뒷단이다.
 *
 * <p>권한 검사는 하지 않는다 — {@code SecurityConfig} 가 {@code /api/admin/**} 를
 * {@code hasRole("ADMIN")} 으로 이미 막는다. 여기서 또 검사하면 두 곳이 어긋날 여지만 생긴다.
 */
@Service
@RequiredArgsConstructor
public class AdminService {

    private final MemberRepository memberRepository;
    private final WarehouseRepository warehouseRepository;
    private final EstimateRepository estimateRepository;

    /**
     * 회원 목록 — 회사·이름순. 각 행에 창고 수와 견적 수를 붙여 "활성 고객"이 한눈에 보이게 한다.
     *
     * <p>개수는 집계 쿼리 두 번으로 한꺼번에 받아 맵으로 붙인다. 회원마다 세면 N+1 이 된다.
     */
    @Transactional(readOnly = true)
    public List<AdminMemberResponse> members() {
        Map<Long, Long> warehouseCounts = toMap(warehouseRepository.countGroupedByMember());
        Map<Long, Long> estimateCounts = toMap(estimateRepository.countGroupedByMember());

        return memberRepository.findAllByOrderByCompanyAscNameAsc().stream()
                .map(member -> AdminMemberResponse.of(
                        member,
                        warehouseCounts.getOrDefault(member.getId(), 0L),
                        estimateCounts.getOrDefault(member.getId(), 0L)))
                .toList();
    }

    /** 전체 견적 — 최근순. 행마다 회사·담당자·연락처가 붙는다. */
    @Transactional(readOnly = true)
    /** 회원을 지정하면 그 회원의 견적만. 정렬·페이지는 호출 쪽 Pageable 을 그대로 따른다. */
    public Page<AdminEstimateResponse> estimates(Long memberId, Pageable pageable) {
        Page<com.ssafy.santafactory.entity.estimate.Estimate> page = memberId == null
                ? estimateRepository.findAllWithOwner(pageable)
                : estimateRepository.findAllWithOwnerByMember(memberId, pageable);
        return page.map(AdminEstimateResponse::from);
    }

    private Map<Long, Long> toMap(List<MemberCount> counts) {
        return counts.stream().collect(java.util.stream.Collectors.toMap(
                MemberCount::memberId, MemberCount::count, Long::sum));
    }
}
