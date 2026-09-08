package com.ssafy.santafactory.global.exception;

import com.ssafy.santafactory.global.common.ApiResponse;
import jakarta.validation.ConstraintViolationException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
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
 * 모든 컨트롤러에서 발생한 예외를 잡아 ApiResponse 실패 포맷으로 변환한다.
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    /** 직접 던진 비즈니스 예외 */
    @ExceptionHandler(GlobalException.class)
    public ResponseEntity<ApiResponse<Void>> handleGlobalException(GlobalException e) {
        ErrorCode ec = e.getErrorCode();
        log.warn("GlobalException: {} - {}", ec.getCode(), ec.getMessage());
        return ResponseEntity
                .status(ec.getHttpStatus())
                .body(ApiResponse.onFailure(ec, null));
    }

    /** @RequestBody @Valid 검증 실패 (필드별 메시지 정리) */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ApiResponse<Map<String, String>>> handleValidation(MethodArgumentNotValidException e) {
        Map<String, String> errors = new LinkedHashMap<>();
        e.getBindingResult().getFieldErrors().forEach(fe ->
                errors.merge(
                        fe.getField(),
                        fe.getDefaultMessage() == null ? "" : fe.getDefaultMessage(),
                        (a, b) -> a + ", " + b
                ));
        ErrorCode ec = ErrorCode.VALIDATION_ERROR;
        return ResponseEntity
                .status(ec.getHttpStatus())
                .body(ApiResponse.onFailure(ec.getCode(), ec.getMessage(), errors));
    }

    /** @Validated 파라미터/경로변수 검증 실패 */
    @ExceptionHandler(ConstraintViolationException.class)
    public ResponseEntity<ApiResponse<Void>> handleConstraintViolation(ConstraintViolationException e) {
        ErrorCode ec = ErrorCode.VALIDATION_ERROR;
        return ResponseEntity
                .status(ec.getHttpStatus())
                .body(ApiResponse.onFailure(ec.getCode(), e.getMessage(), null));
    }

    /** 매핑되지 않은 경로 → 404 */
    @ExceptionHandler({NoResourceFoundException.class, NoHandlerFoundException.class})
    public ResponseEntity<ApiResponse<Void>> handleNotFound(Exception e) {
        ErrorCode ec = ErrorCode.ENTITY_NOT_FOUND;
        return ResponseEntity
                .status(ec.getHttpStatus())
                .body(ApiResponse.onFailure(ec, null));
    }

    /** 지원하지 않는 HTTP 메서드 → 405 */
    @ExceptionHandler(HttpRequestMethodNotSupportedException.class)
    public ResponseEntity<ApiResponse<Void>> handleMethodNotSupported(HttpRequestMethodNotSupportedException e) {
        ErrorCode ec = ErrorCode.METHOD_NOT_ALLOWED;
        return ResponseEntity
                .status(ec.getHttpStatus())
                .body(ApiResponse.onFailure(ec, null));
    }

    /** 그 외 처리되지 않은 모든 예외 → 500 */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleException(Exception e) {
        log.error("Unhandled exception", e);
        ErrorCode ec = ErrorCode.INTERNAL_SERVER_ERROR;
        return ResponseEntity
                .status(ec.getHttpStatus())
                .body(ApiResponse.onFailure(ec, null));
    }
}
