# 견적서 PDF 개발 기록 (S15P21A106-236)

2026-09-17. 브랜치 `feature/S15P21A106-236-견적서-pdf-산출`. 문서 구성·문구 원칙은 [견적서_구성안.md](견적서_구성안.md), 시안은 같은 폴더의 `견적서_예시_1면.png`·`2면.png`.

## 1. 무엇을 만들었나

견적 결과를 **A4 2장 PDF** 로 만들어 (1) 브라우저에서 내려받고 (2) 로그인 계정 이메일로 첨부 전송하는 기능.
그 전 단계로, 견적서에 필요한데 DB 에 없던 값 두 가지를 먼저 저장하게 했다.

| 단계 | 내용 | 커밋 |
|---|---|---|
| 1차 | run 별 시뮬 지표 7개 저장(`simscenarios`), 물리 검증 결과 저장(`estimates.verify_*`) + 권장 run 대비 비교 판정. 상세 응답에 `runs[].kpi`·`verification` 블록 | `8c5f10f` |
| 2차 | PDF 변환 컨테이너, 문서 모델·템플릿, 다운로드·메일 API, 프런트 버튼 | (미커밋) |

## 2. 방식 결정 — 왜 별도 변환 컨테이너인가

| 후보 | 기각/채택 이유 |
|---|---|
| 브라우저 인쇄(`window.print`) | 메일 첨부 불가. 서버에 파일이 없다 |
| 자바 HTML→PDF 라이브러리(openhtmltopdf) | CSS 2.1 수준이라 시안의 grid·flex 배치를 표로 다시 짜야 하고 SVG 는 플러그인. 모양 편차 |
| 백엔드 JVM 안 헤드리스 크롬(Playwright) | 백엔드 JVM 안에 브라우저 프로세스(건당 300 MB 안팎)를 두면 크롬이 죽을 때 백엔드가 같이 흔들림. 서버(t3.xlarge, 16 GB) 메모리 자체는 문제가 아니라 격리가 이유 |
| **Gotenberg 컨테이너 (채택)** | 크로미움 내장 HTTP 변환기. 시안 HTML 그대로, 백엔드는 HTML 만 만들고 HTTP 한 번. 죽어도 견적서 기능만 멈춤. 검증 영상을 MinIO 로 분리한 것과 같은 결 |

정책 결정(사용자, 2026-09-17): 메일 수신자 = 로그인 계정 이메일 고정 · 권한 = 견적 상세 조회와 동일(`OwnershipGuard.checkEstimate`, 남의 것은 404) · 파일명 `견적서_EST-yyyyMMdd-NNNN.pdf` · 비교 기준값 처리 시간 +10 % / 혼잡 +1 %p(임시).

## 3. 구성 요소

```
브라우저 ─(GET quote.pdf / POST quote/email)─▶ backend(Spring)
                                                  │ ① estimateService.quoteSource()  ── DB (estimates·simscenarios·warehouses)
                                                  │ ② QuoteDocumentFactory.build()    ── 상세 응답+창고 → QuoteDocument
                                                  │ ③ Thymeleaf templates/quote/quote.html → HTML 문자열
                                                  │ ④ GotenbergClient.htmlToPdf()  ─(multipart POST)─▶ pdf 컨테이너(Gotenberg+크로미움+Pretendard)
                                                  │ ⑤ 다운로드: PDF 바이트 응답 / 메일: EmailSender.sendWithAttachment (@Async)
```

| 파일 | 역할 |
|---|---|
| `4_Web/pdf/Dockerfile`, `4_Web/pdf/fonts/PretendardVariable.ttf` | `gotenberg/gotenberg:8` + 한글 폰트(가변 TTF 6.7 MB, SIL OFL). `fc-cache` 로 등록 |
| `4_Web/docker-compose.yml` `pdf` 서비스 | `mem_limit: 512m`, `--api-timeout=60s --chromium-max-queue-size=2 --chromium-disable-javascript=true`, healthcheck. 호스트 바인딩은 `127.0.0.1:3001`(로컬에서 백엔드를 gradle 로 띄울 때용, 3000 은 frontend 컨테이너가 쓴다). backend 가 `depends_on` |
| `Jenkinsfile` | `$COMPOSE build backend pdf`, `4_Web/pdf/` 변경도 BE 빌드 트리거 |
| `service/estimate/quote/QuotePdfProperties` | `pdf.base-url`(비면 503), `pdf.timeout`(30s), `pdf.site-url`(문서 안 링크) |
| `service/estimate/quote/QuoteSource` | 상세 응답 + `WarehouseResponse`. `EstimateService.quoteSource()` 가 한 트랜잭션에서 만든다 |
| `service/estimate/quote/QuoteDocument` | 템플릿 값 레코드. 숫자는 전부 표기용 문자열 |
| `service/estimate/quote/QuoteDocumentFactory` | 상세 응답+창고 → 문서. 12행 선택, 비교표·주의 문장, 곡선 SVG 좌표, 사유 문구 |
| `service/estimate/quote/QuoteFormat` | 원("2억 1,700만 원")·억("2.17")·분·초·%·문서 번호. 웹 `utils/format.js` 와 같은 규칙 |
| `service/estimate/quote/GotenbergClient` | `RestClient` multipart(`files=index.html`, A4 8.27×11.69 in, 여백 0, 배경 인쇄). 동시 1건 세마포어, 실패·타임아웃은 `PDF503` |
| `service/estimate/quote/QuotePdfService` | `checkRenderable`(변환기 유무·소유권·상태) → `render`(문서 → HTML → PDF) |
| `service/estimate/quote/QuoteMailService` | `@Async sendToRequester`: 회원 이메일 조회 → render → 첨부 발송. 예외는 로그 |
| `service/auth/EmailSender.sendWithAttachment` | `MimeMessageHelper` 첨부. `mail.enabled=false` 면 로그만 |
| `resources/templates/quote/quote.html` | Thymeleaf. 스크립트 없음(서버가 전부 채움), 로고는 base64, 폰트는 컨테이너 시스템 폰트 |
| `resources/quote/santafactory-logo.png` | 로고 원본(프런트 `public/` 복사) |
| `controller/EstimateController` | `GET /api/estimates/{id}/quote.pdf`, `POST /api/estimates/{id}/quote/email` |
| `global/exception/ErrorCode` | `ESTIMATE_NOT_FINISHED`(409 `EST409_2`), `QUOTE_PDF_UNAVAILABLE`(503 `PDF503`) |
| FE `api/client.js` `api.download` | fetch → blob → `<a download>`. 401 이면 갱신 1회 뒤 재시도. `Content-Disposition` 의 UTF-8 파일명 해석 |
| FE `api/estimates.js` | `downloadQuotePdf`, `emailQuote` |
| FE `components/QuoteStep.jsx` `QuoteActions` | 버튼 2개. 견적 상태 DONE·PARTIAL 아니면 비활성, 진행 중 문구, 결과 메시지 |

## 4. 동작 흐름

### 다운로드
1. 사용자가 견적 화면 "견적서 PDF 저장" 클릭 → `api.download('/estimates/{id}/quote.pdf')` (HttpOnly 쿠키 동봉).
2. `EstimateController.quotePdf` → `QuotePdfService.render(id, me)`.
3. `checkRenderable`: `pdf.base-url` 비면 503 → `estimateService.quoteSource(id, me)` (`@Transactional(readOnly)`: 견적 조회 → `OwnershipGuard.checkEstimate` → `toDetail`(상세 응답, 검증 비교 포함) + `WarehouseResponse.from(warehouse)`) → 상태가 DONE·PARTIAL 아니면 409.
4. **트랜잭션 밖에서** `QuoteDocumentFactory.build(source)` → `templateEngine.process("quote/quote")` → `GotenbergClient.htmlToPdf(html)`.
5. 응답 `application/pdf`, `Content-Disposition: attachment; filename*=UTF-8''견적서_EST-….pdf`. 브라우저가 저장.

### 메일
1. "메일로 받기" 클릭 → `POST /estimates/{id}/quote/email`.
2. 컨트롤러가 **동기로** `checkRenderable` 만 하고(404/409/503 즉시) `QuoteMailService.sendToRequester(source, me)` 호출 → **202**.
3. `@Async` 스레드: `memberRepository.findById(me.id())` 로 이메일 → `pdfService.render(source)` → `EmailSender.sendWithAttachment(email, 제목, 본문, 파일명, bytes, application/pdf)`.
4. 실패는 로그. 화면은 "가입한 이메일로 견적서를 보냈습니다" 를 표시한다(발송 성패는 알 수 없음 — 한계 참고).

### 문서 값이 나오는 곳
| 블록 | 값의 출처 |
|---|---|
| 01 발행 정보 | `estimates`(생성 시각·상태·소요·모델) + `warehouses`(이름·크기·작업자·주문 시간대·하루 주문) |
| 02 권장 구성 | `estimates.recommended_count`·`knee_count` + 권장 run 의 `throughput`·`utilization`·`total_cost`·`lead_time_p90`·`kpi.lead_time_mean_s` |
| 03 목표 달성 여부 | 견적에 복사된 목표 3개 vs 권장 run. 리드타임 상한은 `estimate.lead-time-p90-limit`(미설정이면 "판정에 미포함") |
| 04 예상 구축 비용 | `EstimateProperties.amrPrice`·`installPerUnit` × 대수, 합계는 run 의 `total_cost`(차이가 있으면 "기타 설비" 행) |
| 05 물리 검증 결과 | 상세 응답 `verification`(`estimates.verify_*` + `VerifyComparator` 판정). 검증 전이면 안내 문장 |
| 06 대수별 비교 | DONE run 전체에서 최대 12행(`pickRows`: 양끝·권장·정체·예산 경계 앞뒤 고정, 나머지 등간격) |
| 07 그래프 | 효율 점수(처리율×가동률/100)·구축비 선, 예산 점선, 권장 표식, 정체 점선. 비용 축은 `niceCostMax` |
| 08 운영 예상 | 권장 run 의 `kpi`(평균 처리 시간·배정 대기·혼잡·이동 거리) |
| 09 유의 사항 | 고정 문구 + `pdf.site-url` |

권장이 없는 견적(사유 코드만)은 02 에 사유 문장을 넣고 03~05·08 을 비운다. 부록 블록 번호는 `base`(권장 있으면 5, 없으면 2)로 계산해 이어진다.

## 5. 설정·환경

| 키 | 기본 | 비고 |
|---|---|---|
| `pdf.base-url` ← `PDF_BASE_URL` | 빈 값 | compose 는 `http://pdf:3000`(컨테이너 간). 로컬 gradle 실행은 `http://localhost:3001`. 비면 견적서 API 가 503 |
| `pdf.timeout` | 30s | 변환기 응답 대기이자 세마포어 대기 상한 |
| `pdf.site-url` ← `APP_PUBLIC_URL` | `http://localhost:5173` | compose 기본 `https://j15a106.p.ssafy.io` |
| `estimate.verify-compare.*` | 0.10 / 0.01 | 05 비교 판정 기준. 조회 시 계산이라 과거 견적에도 즉시 적용 |
| `mail.enabled` 등 | 기존 | 꺼져 있으면 첨부 메일도 로그만 |

로컬에서 보기: `docker compose -f 4_Web/docker-compose.yml up -d pdf` 뒤 백엔드에 `PDF_BASE_URL=http://localhost:3001`. 렌더된 HTML 만 보려면 `./gradlew test --tests '*QuoteTemplateTest'` 가 `build/quote-preview.html` 을 남긴다.

## 6. 검증한 것

- 단위: `QuoteFormatTest`(표기 규칙), `QuoteDocumentFactoryTest`(요약·비교·12행·곡선·사유 없는 경우), `QuoteTemplateTest`(스프링 없이 렌더, 2쪽·블록 전부·번호 재계산), `EstimateControllerTest` 4건(첨부 헤더·409·202·503).
- 실물: 로컬에서 변환 이미지를 빌드해 컨테이너로 샘플 견적 변환 — 2쪽, 620 KB, 0.7 s, Pretendard 렌더 확인(`fc-list`). 스크린샷이 시안과 일치.
- 전체 `./gradlew test` 184건 통과(Testcontainers Postgres 포함).

## 7. 운영 주의·한계

- 변환 이미지가 **2.5 GB**(Gotenberg 기본). 첫 배포 빌드가 길다. 변환 중 크로미움 ~300 MB, `mem_limit 512m` 안.
- 변환은 **한 번에 1건**(`GotenbergClient` 세마포어 + `--chromium-max-queue-size=2`). 동시에 누르면 뒤 사람은 최대 30 s 대기 후 503. 견적서 생성 빈도가 낮다는 전제.
- 메일 API 는 202 뒤 발송 성패를 화면에 알리지 않는다. 실패는 백엔드 로그(`견적서 메일 실패`).
- 견적서 링크는 견적 상세 페이지가 아니라 `{site-url}/estimates`(목록) — 프런트에 견적별 URL 이 없다.
- 폰트 파일을 저장소에 넣었다. 웹 화면 폰트를 바꾸면 이 파일도 같이 바꿔야 견적서와 화면이 일치한다.
- 검증 영상은 만료되는 서명 URL 이라 PDF 에 넣지 않는다.

## 8. 남은 것

- EC2 배포 뒤 실제 견적으로 다운로드·메일 1회 확인(`MAIL_ENABLED` 환경).
- 비교 기준값(10 % / 1 %p)은 실제 검증 결과를 몇 번 본 뒤 `estimate.verify-compare` 로 조정.
- 웹 화면에도 `runs[].kpi`·`verification` 을 그리려면 프런트 작업만 필요(응답에 이미 있음).
