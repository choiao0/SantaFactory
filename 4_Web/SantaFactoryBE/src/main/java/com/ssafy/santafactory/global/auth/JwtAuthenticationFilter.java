package com.ssafy.santafactory.global.auth;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import lombok.RequiredArgsConstructor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * access 쿠키를 읽어 SecurityContext 를 채운다.
 *
 * <p>토큰이 없거나 유효하지 않으면 <b>아무것도 하지 않고 통과시킨다.</b> 거부는 Security 의
 * 인가 단계가 맡는다 — 이렇게 두면 permitAll 경로(가입·로그인·Swagger)가 토큰 없이도 지나간다.
 */
@Component
@RequiredArgsConstructor
public class JwtAuthenticationFilter extends OncePerRequestFilter {

    private final JwtProvider jwtProvider;

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        AuthCookies.read(request, AuthCookies.ACCESS)
                .flatMap(jwtProvider::parseAccess)
                .ifPresent(this::authenticate);
        chain.doFilter(request, response);
    }

    private void authenticate(AuthenticatedMember member) {
        var authorities = List.of(new SimpleGrantedAuthority("ROLE_" + member.role()));
        var authentication = new UsernamePasswordAuthenticationToken(member, null, authorities);
        SecurityContextHolder.getContext().setAuthentication(authentication);
    }
}
