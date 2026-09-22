package com.ssafy.santafactory.service.estimate;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.ssafy.santafactory.global.config.MinioProperties;
import io.minio.MinioClient;
import io.minio.StatObjectArgs;
import io.minio.StatObjectResponse;
import java.time.Duration;
import org.junit.jupiter.api.Test;

/** 서명은 네트워크 없이 로컬에서 끝난다(region 고정) — MinIO 없이 URL 모양을 그대로 검증한다. */
class VerifyVideoPresignerTest {

    private static final MinioProperties PROPS = new MinioProperties(
            "https://j15a106.p.ssafy.io/media", "reader", "reader-secret-key", "verify-videos", "us-east-1",
            Duration.ofMinutes(30));

    private final VerifyVideoPresigner presigner = new VerifyVideoPresigner(PROPS);

    @Test
    void an_object_key_becomes_a_presigned_url_under_the_public_media_prefix() {
        String url = presigner.sign("verify_77_n3/demo_verify_77_n3.mp4");

        assertThat(url).startsWith("https://j15a106.p.ssafy.io/media/verify-videos/verify_77_n3/demo_verify_77_n3.mp4?");
        assertThat(url).contains("X-Amz-Signature=").contains("X-Amz-Expires=1800").contains("X-Amz-Credential=reader%2F");
    }

    @Test
    void the_transitional_public_url_from_the_edge_is_resigned_from_its_object_key() {
        String url = presigner.sign("https://j15a106.p.ssafy.io/media/verify-videos/verify_77_n3/demo.mp4");

        assertThat(url).startsWith("https://j15a106.p.ssafy.io/media/verify-videos/verify_77_n3/demo.mp4?X-Amz-");
    }

    @Test
    void the_same_key_signs_the_same_regardless_of_the_stored_form() {
        assertThat(presigner.objectKey("https://x/media/verify-videos/verify_1/a.mp4"))
                .isEqualTo(presigner.objectKey("verify_1/a.mp4"))
                .isEqualTo(presigner.objectKey("/verify_1/a.mp4"))
                .isEqualTo("verify_1/a.mp4");
    }

    @Test
    void a_url_outside_the_bucket_is_passed_through_untouched() {
        assertThat(presigner.sign("file:///tmp/demo.mp4")).isEqualTo("file:///tmp/demo.mp4");
        assertThat(presigner.sign(null)).isNull();
    }

    @Test
    void without_minio_configured_the_stored_value_is_returned_as_is() {
        VerifyVideoPresigner unconfigured = new VerifyVideoPresigner(
                new MinioProperties("", "", "", "verify-videos", "us-east-1", Duration.ofMinutes(30)));

        assertThat(unconfigured.sign("verify_77/demo.mp4")).isEqualTo("verify_77/demo.mp4");
    }

    @Test
    void a_public_url_without_a_path_prefix_needs_no_rewrite() {
        VerifyVideoPresigner direct = new VerifyVideoPresigner(
                new MinioProperties("http://localhost:9002", "a", "b", "verify-videos", "us-east-1", Duration.ofMinutes(5)));

        assertThat(direct.sign("verify_1/a.mp4"))
                .startsWith("http://localhost:9002/verify-videos/verify_1/a.mp4?")
                .contains("X-Amz-Expires=300");
    }

    /**
     * 러너는 상단 키 하나만 싣는다 — 측면은 이름 규칙으로 찾는다 (S15P21A106-265).
     * 버킷에 없으면 null 이라 화면에 시점 버튼이 생기지 않는다.
     */
    @Test
    void the_side_key_is_derived_from_the_top_key_when_the_object_exists() throws Exception {
        MinioClient client = mock(MinioClient.class);
        when(client.statObject(any(StatObjectArgs.class))).thenReturn(mock(StatObjectResponse.class));
        VerifyVideoPresigner withSide = new VerifyVideoPresigner(PROPS, client);

        assertThat(withSide.deriveSideKey("verify_77_n3/demo_verify_77_n3.mp4"))
                .isEqualTo("verify_77_n3/demo_verify_77_n3_side.mp4");
    }

    @Test
    void a_missing_side_object_gives_no_key() throws Exception {
        MinioClient client = mock(MinioClient.class);
        when(client.statObject(any(StatObjectArgs.class))).thenThrow(new RuntimeException("no such key"));
        VerifyVideoPresigner withoutSide = new VerifyVideoPresigner(PROPS, client);

        assertThat(withoutSide.deriveSideKey("verify_77_n3/demo_verify_77_n3.mp4")).isNull();
    }

    @Test
    void deriving_needs_a_configured_client_and_an_mp4_key() throws Exception {
        MinioClient client = mock(MinioClient.class);
        when(client.statObject(any(StatObjectArgs.class))).thenReturn(mock(StatObjectResponse.class));

        assertThat(presigner.deriveSideKey(null)).isNull();                          // 상단이 없으면 측면도 없다
        assertThat(new VerifyVideoPresigner(PROPS, null).deriveSideKey("a/b.mp4")).isNull();
        assertThat(new VerifyVideoPresigner(PROPS, client).deriveSideKey("verify_1/demo")).isNull();
    }
}
