package com.ssafy.santafactory.global.exception;

import lombok.Getter;
import org.springframework.http.HttpStatus;

@Getter
public enum ErrorCode {

    // Common
    VALIDATION_ERROR(HttpStatus.BAD_REQUEST, "COMMON400", "입력한 내용을 확인해 주세요."),
    METHOD_NOT_ALLOWED(HttpStatus.METHOD_NOT_ALLOWED, "COMMON405", "잘못된 요청입니다."),
    ACCESS_DENIED(HttpStatus.FORBIDDEN, "COMMON403", "접근 권한이 없습니다."),
    ENTITY_NOT_FOUND(HttpStatus.NOT_FOUND, "COMMON404", "요청하신 정보를 찾을 수 없습니다."),
    INTERNAL_SERVER_ERROR(HttpStatus.INTERNAL_SERVER_ERROR, "COMMON500", "일시적인 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."),

    // Sim
    SIM_QUEUE_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "SIM503", "지금은 요청을 처리할 수 없습니다. 잠시 후 다시 시도해 주세요."),

    // Estimate
    WAREHOUSE_NOT_FOUND(HttpStatus.NOT_FOUND, "EST404_1", "창고 정보를 찾을 수 없습니다."),
    ESTIMATE_NOT_FOUND(HttpStatus.NOT_FOUND, "EST404_2", "견적을 찾을 수 없습니다."),
    ESTIMATE_NOT_VERIFIABLE(HttpStatus.CONFLICT, "EST409_1", "권장 대수가 없어 3D 주행 검증을 시작할 수 없습니다."),
    ESTIMATE_NOT_FINISHED(HttpStatus.CONFLICT, "EST409_2", "대수별 시뮬레이션이 끝난 뒤에 견적서를 만들 수 있습니다."),
    VERIFY_IN_PROGRESS(HttpStatus.CONFLICT, "EST409_3", "3D 주행 검증이 이미 진행 중입니다. 완료될 때까지 기다려 주세요."),
    VERIFY_ALREADY_DONE(HttpStatus.CONFLICT, "EST409_4", "이미 3D 주행 검증을 마친 견적입니다."),
    QUOTE_PDF_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE, "PDF503", "견적서를 만들지 못했습니다. 잠시 후 다시 시도해 주세요."),

    // Auth
    UNAUTHORIZED(HttpStatus.UNAUTHORIZED, "AUTH401_1", "로그인이 필요합니다."),
    INVALID_CREDENTIALS(HttpStatus.UNAUTHORIZED, "AUTH401_2", "이메일 또는 비밀번호가 올바르지 않습니다."),
    REFRESH_TOKEN_INVALID(HttpStatus.UNAUTHORIZED, "AUTH401_3", "다시 로그인해 주세요."),
    EMAIL_ALREADY_USED(HttpStatus.CONFLICT, "AUTH409_1", "이미 사용 중인 이메일입니다."),
    EMAIL_CODE_INVALID(HttpStatus.BAD_REQUEST, "AUTH400_1", "인증 코드가 올바르지 않습니다."),
    EMAIL_NOT_VERIFIED(HttpStatus.FORBIDDEN, "AUTH403_1", "이메일 인증을 먼저 완료해 주세요."),
    EMAIL_CODE_EXPIRED(HttpStatus.GONE, "AUTH410_1", "인증 코드가 만료되었습니다. 다시 요청해 주세요."),
    EMAIL_SEND_TOO_OFTEN(HttpStatus.TOO_MANY_REQUESTS, "AUTH429_1", "잠시 후 다시 요청해 주세요."),
    ;

    private final HttpStatus httpStatus;
    private final String code;
    private final String message;

    ErrorCode(HttpStatus httpStatus, String code, String message) {
        this.httpStatus = httpStatus;
        this.code = code;
        this.message = message;
    }
}
