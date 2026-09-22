package com.ssafy.santafactory.service.estimate;

import com.ssafy.santafactory.global.config.MinioProperties;
import io.minio.GetPresignedObjectUrlArgs;
import io.minio.MinioClient;
import io.minio.StatObjectArgs;
import io.minio.errors.ErrorResponseException;
import io.minio.http.Method;
import java.net.URI;
import java.util.concurrent.TimeUnit;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 저장된 검증 영상 위치 → 브라우저가 열 수 있는 presigned GET URL.
 *
 * <p>서명 대상 객체 키는 반드시 소유권 검사를 통과한 견적 행의 값만 쓴다. 요청 파라미터로 키를 받아
 * 서명해 주면 "견적 번호만 바꿔 남의 영상을 보는" 구멍이 되살아난다.
 *
 * <p>저장 값은 두 가지가 올 수 있다 — 엣지가 아직 공개 URL 형식으로 보내는 과도기 값
 * ({@code https://…/media/verify-videos/<key>})과 계약 정정 뒤의 객체 키({@code verify_77_n3/demo.mp4}).
 * 둘 다 키를 뽑아 서명한다. 키를 못 찾는 값({@code file://…})과 MinIO 미설정 환경은 그대로 돌려준다.
 *
 * <p>nginx 가 {@code /media/} 접두사를 떼고 MinIO 에 넘기므로(server-setup/nginx-santafactory.conf)
 * 서명은 접두사 없는 경로로 하고 결과 URL 에만 접두사를 붙인다. MinIO 는 자기가 받은 경로·Host 로
 * 서명을 검증하므로 nginx 는 Host 를 그대로 전달해야 한다.
 */
@Slf4j
@Component
@EnableConfigurationProperties(MinioProperties.class)
public class VerifyVideoPresigner {

    /** 시점별 파일 이름 규칙 — 상단 <code>demo_x.mp4</code>, 측면 <code>demo_x_side.mp4</code>. */
    private static final String SIDE_SUFFIX = "_side";
    private static final String VIDEO_EXT = ".mp4";

    private final MinioProperties properties;
    private final MinioClient client;
    private final String pathPrefix;

    @Autowired
    public VerifyVideoPresigner(MinioProperties properties) {
        this(properties, properties.configured() ? buildClient(properties) : null);
        if (client == null) {
            log.warn("MinIO 미설정 — 검증 영상 URL 을 서명하지 않고 저장된 값을 그대로 내보낸다");
        }
    }

    VerifyVideoPresigner(MinioProperties properties, MinioClient client) {
        this.properties = properties;
        this.client = client;
        this.pathPrefix = client == null ? "" : stripTrailingSlash(URI.create(properties.publicUrl()).getRawPath());
    }

    /**
     * 상단 시점 키에서 측면 시점 키를 만들어, 그 객체가 실제로 버킷에 있으면 돌려준다.
     *
     * <p>러너는 결과에 상단 키 하나만 싣는다. 측면을 받으려면 host-orch 페이로드까지 고쳐야 하는데,
     * 파일 이름 규칙(<code>…_side.mp4</code>)만 지키면 키는 계산으로 얻을 수 있다 (S15P21A106-265).
     *
     * <p><b>있는지는 반드시 확인한다.</b> 이름만 만들어 서명해 내보내면 측면을 안 찍은 회차에도
     * 시점 버튼이 생기고, 누르면 404 로 재생이 깨진다. 확인에 실패하면 없는 것으로 본다 —
     * 버튼이 안 생길 뿐 화면은 지금과 같다.
     */
    public String deriveSideKey(String topStored) {
        if (topStored == null || client == null) {
            return null;
        }
        String topKey = objectKey(topStored);
        if (topKey == null || !topKey.endsWith(VIDEO_EXT)) {
            return null;
        }
        String sideKey = topKey.substring(0, topKey.length() - VIDEO_EXT.length()) + SIDE_SUFFIX + VIDEO_EXT;
        return exists(sideKey) ? sideKey : null;
    }

    private boolean exists(String key) {
        try {
            client.statObject(StatObjectArgs.builder().bucket(properties.bucket()).object(key).build());
            return true;
        } catch (ErrorResponseException e) {
            return false;   // 없는 객체 — 정상적인 경우다
        } catch (Exception e) {
            log.warn("측면 시점 영상 존재 확인 실패 — 없는 것으로 본다: key={}", key, e);
            return false;
        }
    }

    public String sign(String stored) {
        if (stored == null || client == null) {
            return stored;
        }
        String key = objectKey(stored);
        if (key == null) {
            return stored;
        }
        try {
            String signed = client.getPresignedObjectUrl(GetPresignedObjectUrlArgs.builder()
                    .method(Method.GET)
                    .bucket(properties.bucket())
                    .object(key)
                    .expiry((int) properties.presignTtl().toSeconds(), TimeUnit.SECONDS)
                    .build());
            return withPathPrefix(signed);
        } catch (Exception e) {
            log.warn("검증 영상 URL 서명 실패, 저장된 값을 그대로 내보낸다: key={}", key, e);
            return stored;
        }
    }

    /** URL 이면 {@code /<bucket>/} 뒤를, 아니면 값 전체를 객체 키로 본다. URL 인데 버킷이 없으면 null. */
    String objectKey(String stored) {
        if (!stored.contains("://")) {
            return stored.startsWith("/") ? stored.substring(1) : stored;
        }
        String marker = "/" + properties.bucket() + "/";
        int at = stored.indexOf(marker);
        if (at < 0) {
            return null;
        }
        String key = stored.substring(at + marker.length());
        int query = key.indexOf('?');
        return query < 0 ? key : key.substring(0, query);
    }

    private String withPathPrefix(String signed) {
        if (pathPrefix.isEmpty()) {
            return signed;
        }
        URI uri = URI.create(signed);
        String base = uri.getScheme() + "://" + uri.getRawAuthority();
        return base + pathPrefix + signed.substring(base.length());
    }

    private static MinioClient buildClient(MinioProperties properties) {
        URI url = URI.create(properties.publicUrl());
        return MinioClient.builder()
                .endpoint(url.getScheme() + "://" + url.getRawAuthority())
                .credentials(properties.accessKey(), properties.secretKey())
                .region(properties.region())
                .build();
    }

    private static String stripTrailingSlash(String path) {
        if (path == null || path.equals("/")) {
            return "";
        }
        return path.endsWith("/") ? path.substring(0, path.length() - 1) : path;
    }
}
