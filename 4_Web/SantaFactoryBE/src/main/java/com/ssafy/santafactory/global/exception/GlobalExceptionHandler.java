package com.ssafy.santafactory.global.exception;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.ssafy.santafactory.global.common.ApiResponse;
import jakarta.servlet.http.HttpServletResponse;
import jakarta.validation.ConstraintViolationException;
import java.io.IOException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.NoHandlerFoundException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 전역 예외 처리기.
 *
 * <p>응답을 {@code HttpServletResponse}에 직접 써서 Spring 의 컨텐트 협상을 건너뛴다 — SSE 라우트
 * ({@code produces = TEXT_EVENT_STREAM_VALUE})에서 예외가 나면, {@code ResponseEntity} 로 JSON 을
 * 돌려주려 해도 요청의 {@code Accept: text/event-stream} 과 안 맞아 협상 자체가 실패하며
 * {@code HttpMediaTypeNotAcceptableException} 이 한 번 더 터진다(500 + 깨진 응답). 직접 쓰면 이 문제가
 * 없다 — SSE 클라이언트는 에러 상황에서 이벤트 스트림 형식을 기대하지 않고 상태 코드만 보면 된다.
 */
@Slf4j
@RestControllerAdvice
@RequiredArgsConstructor
public class GlobalExceptionHandler {

    private final ObjectMapper objectMapper;

    /** 직접 던진 비즈니스 예외 */
    @ExceptionHandler(GlobalException.class)
    public void handleGlobalException(GlobalException e, HttpServletResponse response) throws IOException {
        ErrorCode ec = e.getErrorCode();
        log.warn("GlobalException: {} - {}", ec.getCode(), ec.getMessage());
        writeError(response, ec.getHttpStatus(), ApiResponse.onFailure(ec, null));
    }

    /** @RequestBody @Valid 검증 실패 (필드별 메시지 정리) */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public void handleValidation(MethodArgumentNotValidException e, HttpServletResponse response) throws IOException {
        Map<String, String> errors = new LinkedHashMap<>();
        e.getBindingResult().getFieldErrors().forEach(fe ->
                errors.merge(
                        fe.getField(),
                        fe.getDefaultMessage() == null ? "" : fe.getDefaultMessage(),
                        (a, b) -> a + ", " + b
                ));
        ErrorCode ec = ErrorCode.VALIDATION_ERROR;
        writeError(response, ec.getHttpStatus(), ApiResponse.onFailure(ec.getCode(), ec.getMessage(), errors));
    }

    /** @Validated 파라미터/경로변수 검증 실패 */
    @ExceptionHandler(ConstraintViolationException.class)
    public void handleConstraintViolation(ConstraintViolationException e, HttpServletResponse response) throws IOException {
        ErrorCode ec = ErrorCode.VALIDATION_ERROR;
        writeError(response, ec.getHttpStatus(), ApiResponse.onFailure(ec.getCode(), e.getMessage(), null));
    }

    /** 매핑되지 않은 경로 → 404 */
    @ExceptionHandler({NoResourceFoundException.class, NoHandlerFoundException.class})
    public void handleNotFound(Exception e, HttpServletResponse response) throws IOException {
        ErrorCode ec = ErrorCode.ENTITY_NOT_FOUND;
        writeError(response, ec.getHttpStatus(), ApiResponse.onFailure(ec, null));
    }

    /** 지원하지 않는 HTTP 메서드 → 405 */
    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public void handleMethodNotSupported(HttpRequestMethodNotSupportedException e, HttpServletResponse response) throws IOException {
        ErrorCode ec = ErrorCode.METHOD_NOT_ALLOWED;
        writeError(response, ec.getHttpStatus(), ApiResponse.onFailure(ec, null));
    }

    /** 그 외 처리되지 않은 모든 예외 → 500 */
    @ExceptionHandler(Exception.class)
    public void handleException(Exception e, HttpServletResponse response) throws IOException {
        log.error("Unhandled exception", e);
        ErrorCode ec = ErrorCode.INTERNAL_SERVER_ERROR;
        writeError(response, ec.getHttpStatus(), ApiResponse.onFailure(ec, null));
    }

    private void writeError(HttpServletResponse response, HttpStatus status, Object body) throws IOException {
        response.setStatus(status.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        objectMapper.writeValue(response.getWriter(), body);
    }
}
