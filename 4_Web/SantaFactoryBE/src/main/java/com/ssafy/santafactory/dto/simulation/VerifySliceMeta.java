package com.ssafy.santafactory.dto.simulation;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;

/**
 * {@link SimulationResponse.VerifySlice} 에서 {@code gz_b64} 를 뺀 나머지 (S15P21A106-244).
 * DB 의 {@code meta_json} 컬럼과 검증 회차의 {@code slice_meta_json} 컬럼에 이 모양 그대로 저장한다 —
 * 큰 궤적 문자열 없이도 구간이 언제·몇 초 창인지 화면에 보여줄 수 있어야 해서다.
 */
@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
@JsonIgnoreProperties(ignoreUnknown = true)
public record VerifySliceMeta(
        Integer format,
        String source,
        Double t0S,
        Double tStartS,
        Double tEndS,
        Double warmupS,
        Double windowS,
        Integer nRobots,
        Integer tasksDone,
        Integer moves,
        Integer turns,
        Integer reverses,
        Long b64Bytes,
        String error
) {
}
