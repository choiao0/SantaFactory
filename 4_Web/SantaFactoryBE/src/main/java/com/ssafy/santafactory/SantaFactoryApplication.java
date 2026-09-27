package com.ssafy.santafactory;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 스케줄링은 견적의 TIMEOUT 스윕(결과가 오지 않은 run 회수)에, 비동기는 메일 발송(SMTP 왕복을 요청 스레드에서
 * 떼기)에 쓴다.
 */
@EnableAsync
@EnableScheduling
@SpringBootApplication
public class SantaFactoryApplication {

    public static void main(String[] args) {
        SpringApplication.run(SantaFactoryApplication.class, args);
    }
}
