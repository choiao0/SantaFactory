package com.ssafy.santafactory.global.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
@EnableConfigurationProperties(SimProperties.class)
public class RabbitConfig {

    @Bean
    public Queue simRequestQueue(SimProperties props) {
        return new Queue(props.requestQueue(), true);
    }

    @Bean
    public Queue simResultQueue(SimProperties props) {
        return new Queue(props.resultQueue(), true);
    }

    @Bean
    public Queue simVerifyResultQueue(SimProperties props) {
        return new Queue(props.verifyResultQueue(), true);
    }

    @Bean
    public MessageConverter jsonMessageConverter(ObjectMapper objectMapper) {
        return new Jackson2JsonMessageConverter(objectMapper);
    }
}
