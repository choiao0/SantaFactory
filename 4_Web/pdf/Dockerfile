# 견적서 HTML → PDF 변환기 (S15P21A106-236). Gotenberg(크로미움 내장)에 한글 폰트만 얹는다.
# 백엔드가 내부 네트워크로 POST /forms/chromium/convert/html 을 호출한다. 외부 포트는 열지 않는다.
FROM gotenberg/gotenberg:8

USER root
# Pretendard 1.3.9 가변 폰트(SIL OFL 1.1). 웹 화면과 같은 글꼴이라 견적서 모양이 화면과 일치한다.
COPY fonts/PretendardVariable.ttf /usr/local/share/fonts/PretendardVariable.ttf
RUN chmod 644 /usr/local/share/fonts/PretendardVariable.ttf && fc-cache -f
USER gotenberg
