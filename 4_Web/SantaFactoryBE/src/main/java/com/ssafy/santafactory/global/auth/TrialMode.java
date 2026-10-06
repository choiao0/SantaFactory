package com.ssafy.santafactory.global.auth;

import com.ssafy.santafactory.entity.member.Member;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.global.exception.ErrorCode;
import com.ssafy.santafactory.global.exception.GlobalException;
import java.util.Optional;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 체험 모드 (S15P21A106-283).
 *
 * <p>본선 뒤 공개 체험 링크는 GCP DES 워커와 GPU 서버를 쓰지 않는다. 워커로 가는 요청은 견적 생성
 * ({@code sim.request})과 3D 주행 검증({@code sim.verify.request}) 둘뿐이라 그 입구와 발행 직전을 막는다.
 * 대신 데모 회원({@code account.user})이 미리 돌려 둔 견적을 가입한 누구나 <b>읽기만</b> 하게 연다.
 *
 * <p>데모 회원은 id 가 아니라 이메일로 알아본다 — id 는 DB 마다 다르지만 이메일은 설정에 보이는 값이다.
 */
@Component
@EnableConfigurationProperties(TrialProperties.class)
@RequiredArgsConstructor
public class TrialMode {

    private final TrialProperties trialProperties;
    private final AccountProperties accountProperties;

    public boolean enabled() {
        return trialProperties.enabled();
    }

    /** 새 워커 요청(과 그 앞 단계)을 받는 자리에서 맨 먼저 부른다. 꺼져 있으면 아무 일도 하지 않는다. */
    public void rejectNewRequests() {
        if (enabled()) {
            throw new GlobalException(ErrorCode.TRIAL_READ_ONLY);
        }
    }

    /** 누구나 읽을 수 있는 견적의 주인 이메일. 꺼져 있거나 데모 회원 설정이 없으면 비어 있다. */
    public Optional<String> showcaseOwnerEmail() {
        AccountProperties.Account demo = accountProperties.user();
        if (!enabled() || demo == null || demo.email() == null || demo.email().isBlank()) {
            return Optional.empty();
        }
        return Optional.of(demo.email());
    }

    /** 이 창고의 견적을 가입한 누구나 읽을 수 있는가 — 체험 모드이고 주인이 데모 회원일 때만. */
    public boolean isShowcase(Warehouse warehouse) {
        Member owner = warehouse.getMember();
        return owner != null && showcaseOwnerEmail().map(email -> email.equals(owner.getEmail())).orElse(false);
    }
}
