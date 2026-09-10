package com.ssafy.santafactory.global.config;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

@ConfigurationProperties(prefix = "sim")
public record SimProperties(
        @DefaultValue("sim.request") String requestQueue,
        @DefaultValue("sim.result") String resultQueue,
        @DefaultValue("sim.verify.request") String verifyRequestQueue,
        @DefaultValue("sim.verify.result") String verifyResultQueue
) {
}
