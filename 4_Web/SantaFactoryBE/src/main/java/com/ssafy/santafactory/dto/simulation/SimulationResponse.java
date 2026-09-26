package com.ssafy.santafactory.dto.simulation;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.PropertyNamingStrategies;
import com.fasterxml.jackson.databind.annotation.JsonNaming;
import jakarta.validation.constraints.NotBlank;

@JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
public record SimulationResponse(
        @NotBlank String runId,
        @NotBlank String status,
        String error,
        Kpi kpi,
        /**
         * 앞 구간 재생 데이터 (명세 §1-2 "리플레이", S15P21A106-205). 요청에 {@code export_replay} 를
         * 넣었을 때만 온다. null 일 수 있고 그래도 run 은 정상이다 — 리플레이는 곁다리다.
         *
         * <p>자바 모델로 풀지 않고 {@link JsonNode} 로 받는다. 안쪽이 "로봇 id → 궤적 배열" 이라
         * 타입으로 옮겨봐야 그대로 다시 JSON 으로 나갈 뿐이고, 시뮬 쪽이 키를 늘려도 여기가 안 깨진다.
         */
        JsonNode replay,
        /**
         * DES 피크 구간(물리 검증용) — status "done" 메시지에만, export 가 있을 때 온다 (S15P21A106-244).
         * 구간을 못 만들었으면 {@code gzB64} 없이 {@code error} 만 채워 온다 — 그래도 화면이 사유를
         * 보일 수 있게 이 값 자체는 저장한다.
         */
        VerifySlice verifySlice
) {

    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    public record Kpi(
            Integer ordersTotal,
            Integer ordersCompleted,
            Integer inboundTotal,
            Integer inboundCompleted,

            Long makespanS,
            Double leadTimeMeanS,
            Double leadTimeP90S,
            Double queueTimeMeanS,

            Double throughputOrdersPerH,
            Double throughputTasksPerH,

            Double amrUtilization,
            Double conflictWaitRatio,
            Long distanceTotalM,
            Long chargeDowntimeS
    ) {
    }

    /** 명세 §A {@code verify_slice} 그대로 — {@code meta()} 로 {@code gzB64} 를 뺀 저장용 모양을 얻는다. */
    @JsonNaming(PropertyNamingStrategies.SnakeCaseStrategy.class)
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record VerifySlice(
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
            /** gzip 압축 후 base64 — 없으면(= 상한을 넘겨) {@code error} 만 채워 온다. */
            String gzB64,
            String error
    ) {

        /** 큰 궤적 문자열을 뺀 메타만. DB {@code meta_json} 컬럼에 이 모양 그대로 저장한다. */
        public VerifySliceMeta meta() {
            return new VerifySliceMeta(format, source, t0S, tStartS, tEndS, warmupS, windowS,
                    nRobots, tasksDone, moves, turns, reverses, b64Bytes, error);
        }

        public boolean hasTrajectory() {
            return gzB64 != null;
        }
    }
}
