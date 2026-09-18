package com.ssafy.santafactory.global.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

import java.time.Duration;

/**
 * 검증 영상 저장소(MinIO) 접속·서명 설정.
 *
 * <p>버킷은 비공개다. 영상은 백엔드가 소유권을 확인한 뒤 발급하는 짧은 만료의 presigned GET URL 로만
 * 본다 — {@code <video src>} 는 JWT 를 실을 수 없어 API 처럼 토큰으로 막을 수 없기 때문이다 (결정 2026-09-15).
 *
 * @param publicUrl  브라우저가 영상을 받는 기준 주소(nginx {@code /media/} → MinIO). 서명은 이 호스트로 한다 —
 *                   백엔드가 MinIO 를 부르는 내부 주소({@code minio:9000})로 서명하면 브라우저 요청의 Host 와
 *                   어긋나 거절된다. 비면 서명하지 않고 저장된 값을 그대로 내보낸다 (로컬·테스트)
 * @param accessKey  읽기 전용 계정. 관리자 계정이 아니라 GET 만 되는 계정이어야 유출 시 피해가 읽기에 그친다
 * @param bucket     엣지가 mp4 를 올리는 버킷 (2_Simulation/t3_amr/deploy/compose.yml MINIO_BUCKET 과 같은 값)
 * @param region     MinIO 기본 us-east-1. 비워 두면 SDK 가 서명 전에 GetBucketLocation 요청을 보낸다
 * @param presignTtl URL 유효 시간. 영상을 보는 동안 구간 이동(Range 재요청)이 되려면 시청 시간을 덮어야 한다
 */
@ConfigurationProperties(prefix = "minio")
public record MinioProperties(
        String publicUrl,
        String accessKey,
        String secretKey,
        @DefaultValue("verify-videos") String bucket,
        @DefaultValue("us-east-1") String region,
        @DefaultValue("30m") Duration presignTtl
) {

    public boolean configured() {
        return notBlank(publicUrl) && notBlank(accessKey) && notBlank(secretKey);
    }

    private static boolean notBlank(String value) {
        return value != null && !value.isBlank();
    }
}
