package com.ssafy.santafactory.global.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class SwaggerConfig {

    @Bean
    public OpenAPI openAPI() {
        return new OpenAPI().info(new Info()
                .title("SantaFactory API")
                .description("AMR 창고 시뮬레이션 백엔드 API")
                .version("v0.1"));
    }
}
