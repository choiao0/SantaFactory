package com.ssafy.santafactory.support;

import com.ssafy.santafactory.global.auth.AuthenticatedMember;
import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;
import java.util.List;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContext;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.test.context.support.WithSecurityContext;
import org.springframework.security.test.context.support.WithSecurityContextFactory;

/**
 * 컨트롤러 테스트용 인증 주체.
 *
 * <p>{@code @WithMockUser} 를 쓰면 안 된다 — 그건 Spring 의 {@code User} 를 주체로 넣으므로
 * {@code @AuthenticationPrincipal AuthenticatedMember me} 가 <b>null 로 바인딩된다.</b> 그러면
 * 서비스 호출 인자가 null 이 되어, 소유권을 넘기는지 검증할 수 없다.
 */
@Target({ElementType.TYPE, ElementType.METHOD})
@Retention(RetentionPolicy.RUNTIME)
@WithSecurityContext(factory = WithMockMember.Factory.class)
public @interface WithMockMember {

    long id() default 1L;

    String role() default "USER";

    class Factory implements WithSecurityContextFactory<WithMockMember> {

        @Override
        public SecurityContext createSecurityContext(WithMockMember annotation) {
            var principal = new AuthenticatedMember(annotation.id(), annotation.role());
            var authentication = new UsernamePasswordAuthenticationToken(
                    principal, null, List.of(new SimpleGrantedAuthority("ROLE_" + annotation.role())));
            SecurityContext context = SecurityContextHolder.createEmptyContext();
            context.setAuthentication(authentication);
            return context;
        }
    }
}
