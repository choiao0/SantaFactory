package com.ssafy.santafactory.global.auth;

import com.ssafy.santafactory.entity.member.Member;
import com.ssafy.santafactory.entity.member.Role;
import com.ssafy.santafactory.entity.warehouse.Warehouse;
import com.ssafy.santafactory.repository.MemberRepository;
import com.ssafy.santafactory.repository.WarehouseRepository;
import java.util.List;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * 관리자·데모 계정 주입 (S15P21A106-186).
 *
 * <p><b>왜 시드 SQL 이 아니라 코드인가</b> — 시드에 넣으면 BCrypt 해시가 저장소에 커밋되고,
 * 바꾸려면 매번 커밋해야 하며 운영에서 지울 수도 없다. 여기서 만들면 비밀번호가 {@code .env}
 * 에만 있고 값을 비우면 계정이 생기지 않는다.
 *
 * <p><b>관리자가 필요한 이유</b> — 가입 API 는 항상 USER 로 만든다. 관리자는 밖에서 주입할
 * 수밖에 없다. 반면 데모 USER 는 가입으로도 만들 수 있는데, <b>창고 등록 화면이 없는 동안</b>
 * 시드 창고의 주인이 필요해서 같이 만든다. 화면이 생기면 {@code DEMO_PASSWORD} 를 비워 끈다.
 *
 * <p>두 동작을 나눠 둔 게 중요하다. 계정 생성은 "없을 때만"이지만 <b>창고 귀속은 매 기동마다</b>
 * 확인한다. 시드({@code R__seed_demo.sql})가 재실행되면 창고가 주인 없이 다시 만들어지는데,
 * 계정 생성 쪽만 보고 건너뛰면 주인이 영구히 비게 된다.
 */
@Slf4j
@Component
@EnableConfigurationProperties(AccountProperties.class)
@RequiredArgsConstructor
public class AccountInitializer implements ApplicationRunner {

    private final MemberRepository memberRepository;
    private final WarehouseRepository warehouseRepository;
    private final PasswordEncoder passwordEncoder;
    private final AccountProperties props;

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        createAdmin();
        Member demo = createDemoUser();
        claimOrphanWarehouses(demo);
    }

    private void createAdmin() {
        AccountProperties.Account admin = props.admin();
        // 설정 블록이 아예 없을 수 있다 (테스트 yml 이 main 을 가린다)
        if (admin == null || isBlank(admin.password())) {
            log.info("ADMIN_PASSWORD 가 없어 관리자 계정을 만들지 않습니다");
            return;
        }
        if (memberRepository.existsByRole(Role.ADMIN)) {
            return;   // 이미 있으면 건너뛴다 — .env 를 바꿔도 기존 비밀번호는 그대로다
        }
        Member saved = memberRepository.save(Member.admin(
                admin.email(), passwordEncoder.encode(admin.password()),
                admin.name(), admin.company(), admin.phone()));
        log.info("관리자 계정 생성: {}", saved.getEmail());
    }

    private Member createDemoUser() {
        AccountProperties.Account demo = props.user();
        if (demo == null || isBlank(demo.password())) {
            return null;
        }
        return memberRepository.findByEmail(demo.email())
                .orElseGet(() -> {
                    Member saved = memberRepository.save(Member.signUp(
                            demo.email(), passwordEncoder.encode(demo.password()),
                            demo.name(), demo.company(), demo.phone()));
                    log.info("데모 회원 생성: {}", saved.getEmail());
                    return saved;
                });
    }

    /**
     * 주인 없는 창고를 데모 회원에게 귀속시킨다. 그런 창고는 시드에서 온 것뿐이다 —
     * 생성 API 는 항상 세션 회원을 붙인다.
     */
    private void claimOrphanWarehouses(Member demo) {
        if (demo == null) {
            return;
        }
        List<Warehouse> orphans = warehouseRepository.findByMemberIsNull();
        if (orphans.isEmpty()) {
            return;
        }
        orphans.forEach(warehouse -> warehouse.assignTo(demo));
        log.info("주인 없는 창고 {}개를 {} 에게 귀속시켰습니다", orphans.size(), demo.getEmail());
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
