package com.ssafy.santafactory.service.auth;

import com.ssafy.santafactory.global.config.MailProperties;
import jakarta.mail.MessagingException;
import jakarta.mail.internet.MimeMessage;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.mail.MailException;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;

/**
 * 메일 발송. 요청 스레드에서 떼어 보낸다 — SMTP 왕복(수 초)을 가입 화면이 기다리지 않게.
 * 실패는 로그로만 남긴다. 사용자는 쿨다운이 지나면 다시 요청할 수 있다.
 *
 * <p>{@code mail.enabled=false} 면 내용을 로그에 찍고 끝낸다. {@code JavaMailSender} 는
 * {@code spring.mail.host} 가 있을 때만 만들어지므로 있으면 쓰고 없으면 로그로 대체한다.
 *
 * <p>이름을 {@code MailSender} 로 두면 Spring 이 만드는 {@code JavaMailSender} 빈 이름({@code mailSender})과
 * 충돌해 기동이 실패한다.
 */
@Slf4j
@Component
@EnableConfigurationProperties(MailProperties.class)
public class EmailSender {

    private final MailProperties properties;
    private final ObjectProvider<JavaMailSender> senderProvider;

    public EmailSender(MailProperties properties, ObjectProvider<JavaMailSender> senderProvider) {
        this.properties = properties;
        this.senderProvider = senderProvider;
    }

    @Async
    public void send(String to, String subject, String text) {
        JavaMailSender sender = activeSender();
        if (sender == null) {
            log.info("메일 발송 생략(mail.enabled={}): to={}, subject={}\n{}", properties.enabled(), to, subject, text);
            return;
        }
        SimpleMailMessage message = new SimpleMailMessage();
        message.setFrom(properties.from());
        message.setTo(to);
        message.setSubject(subject);
        message.setText(text);
        try {
            sender.send(message);
            log.info("메일 발송: to={}, subject={}", to, subject);
        } catch (MailException e) {
            log.error("메일 발송 실패: to={}, subject={}", to, subject, e);
        }
    }

    /**
     * 첨부 파일 한 개를 붙여 보낸다 (견적서 PDF, S15P21A106-236). 호출자가 이미 비동기 스레드에서 부르므로
     * 여기서는 동기로 보내고, 성패를 돌려준다.
     */
    public boolean sendWithAttachment(String to, String subject, String text,
                                      String filename, byte[] attachment, String contentType) {
        JavaMailSender sender = activeSender();
        if (sender == null) {
            log.info("첨부 메일 발송 생략(mail.enabled={}): to={}, subject={}, file={} ({} bytes)",
                    properties.enabled(), to, subject, filename, attachment.length);
            return false;
        }
        try {
            MimeMessage message = sender.createMimeMessage();
            MimeMessageHelper helper = new MimeMessageHelper(message, true, StandardCharsets.UTF_8.name());
            helper.setFrom(properties.from());
            helper.setTo(to);
            helper.setSubject(subject);
            helper.setText(text, false);
            helper.addAttachment(filename, new ByteArrayResource(attachment), contentType);
            sender.send(message);
            log.info("첨부 메일 발송: to={}, subject={}, file={}", to, subject, filename);
            return true;
        } catch (MessagingException | MailException e) {
            log.error("첨부 메일 발송 실패: to={}, subject={}, file={}", to, subject, filename, e);
            return false;
        }
    }

    private JavaMailSender activeSender() {
        return properties.enabled() ? senderProvider.getIfAvailable() : null;
    }
}
