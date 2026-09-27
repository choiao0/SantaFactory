package com.ssafy.santafactory.global.common;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.fasterxml.jackson.annotation.JsonPropertyOrder;
import com.ssafy.santafactory.global.exception.ErrorCode;
import lombok.AllArgsConstructor;
import lombok.Getter;

/**
 * 모든 API 응답을 감싸는 공통 포맷.
 * 성공/실패와 무관하게 { isSuccess, code, message, result } 형태로 내려간다.
 */
@Getter
@AllArgsConstructor
@JsonPropertyOrder({"isSuccess", "code", "message", "result"})
public class ApiResponse<T> {

    @JsonProperty("isSuccess")
    private final Boolean isSuccess;

    private final String code;
    private final String message;

    // result가 null이면 응답 JSON에서 아예 제외
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private final T result;

    /** 성공 - 기본 코드(COMMON200) */
    public static <T> ApiResponse<T> onSuccess(T result) {
        return new ApiResponse<>(true, "COMMON200", "성공입니다.", result);
    }

    /** 성공 - 바디 없이(생성/삭제 등) */
    public static ApiResponse<Void> onSuccess() {
        return new ApiResponse<>(true, "COMMON200", "성공입니다.", null);
    }

    /** 실패 - GlobalExceptionHandler가 사용 */
    public static <T> ApiResponse<T> onFailure(String code, String message, T result) {
        return new ApiResponse<>(false, code, message, result);
    }

    public static <T> ApiResponse<T> onFailure(ErrorCode errorCode, T result) {
        return new ApiResponse<>(false, errorCode.getCode(), errorCode.getMessage(), result);
    }
}
