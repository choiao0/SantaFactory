package com.ssafy.santafactory.global.auth;

import com.ssafy.santafactory.entity.estimate.Estimate;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

/**
 * 소유권 검사 (S15P21A106-186).
 *
 * <p><b>없는 것처럼 404 를 준다</b> — 403 을 주면 "그 id 의 리소스가 존재한다"는 사실이 새어
 * 나간다. 견적 id 를 훑으며 남의 견적이 몇 개인지 세는 것을 막으려면 있는 것과 없는 것의 응답이
 * 같아야 한다.
 *
 * <p>ADMIN 은 전체를 본다 — Santa Factory 영업이 고객사 견적 현황을 봐야 하기 때문이다.
 *
 * <p>견적은 읽기와 쓰기를 가른다 (S15P21A106-283). 체험 모드에서는 데모 회원의 견적을 누구나
 * 읽지만({@link #checkEstimateReadable}), 삭제·취소·검증은 여전히 주인만 한다({@link #checkEstimate}).
 */
@Component
@RequiredArgsConstructor
public class OwnershipGuard {

    private final TrialMode trialMode;

    public void checkWarehouse(Warehouse warehouse, AuthenticatedMember member) {
        if (!member.isAdmin() && !warehouse.ownedBy(member.id())) {
            throw new GlobalException(ErrorCode.WAREHOUSE_NOT_FOUND);
        }
    }

    /** 바꾸는 쪽(삭제·취소·검증) — 주인과 관리자만. */
    public void checkEstimate(Estimate estimate, AuthenticatedMember member) {
        if (!member.isAdmin() && !estimate.getWarehouse().ownedBy(member.id())) {
            throw new GlobalException(ErrorCode.ESTIMATE_NOT_FOUND);
        }
    }

    /** 읽는 쪽(상세·리플레이·스트림·견적서) — 주인과 관리자, 그리고 체험 모드면 데모 회원의 견적. */
    public void checkEstimateReadable(Estimate estimate, AuthenticatedMember member) {
        if (trialMode.isShowcase(estimate.getWarehouse())) {
            return;
        }
        checkEstimate(estimate, member);
    }
}
