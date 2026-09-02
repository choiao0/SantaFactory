package com.ssafy.santafactory.global.exception;

import lombok.Getter;

/**
 * 서비스/컨트롤러에서 직접 던지는 비즈니스 예외.
 */
@Getter
public class GlobalException extends RuntimeException {

    private final ErrorCode errorCode;

    public GlobalException(ErrorCode errorCode) {
        super(errorCode.getMessage());
        this.errorCode = errorCode;
    }
}
