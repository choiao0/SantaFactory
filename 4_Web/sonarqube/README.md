# EC2 SonarQube 및 GitLab Runner

SonarQube와 GitLab Runner를 애플리케이션 배포와 독립적으로 운영한다.
SonarQube는 전용 PostgreSQL을 사용하고, Runner가 생성하는 job 컨테이너는
`sonar-network`에서 `http://sonarqube:9000/sonarqube`로 접근한다.

## 1. EC2 호스트 준비

SonarQube의 Elasticsearch가 필요로 하는 커널 값을 설정한다.

```bash
echo 'vm.max_map_count=262144' | sudo tee /etc/sysctl.d/99-sonarqube.conf
sudo sysctl --system
```

## 2. 환경변수 생성

```bash
cd 4_Web/sonarqube
cp .env.example .env
openssl rand -base64 36
nano .env
```

`openssl` 출력을 `.env`의 `SONAR_DB_PASSWORD`에 저장한다. `.env`는 Git에
추가하지 않는다.

## 3. 서비스 실행

```bash
docker compose up -d
docker compose ps
docker compose logs -f sonarqube
```

`SonarQube is operational`이 출력되면 `Ctrl+C`로 로그 조회만 종료한다.

EC2 외부에 9000 포트를 공개하지 않고 SSH 터널로 접속할 수 있다.

```powershell
ssh -i "C:\path\to\key.pem" -L 9000:127.0.0.1:9000 ubuntu@EC2_HOST
```

브라우저에서 `http://localhost:9000/sonarqube`에 접속한다.

## 4. GitLab Runner 등록

GitLab 프로젝트의 **Settings > CI/CD > Runners**에서 프로젝트 Runner를 생성한다.

- Tag: `sonar-ec2`
- Run untagged jobs: 해제
- Paused: 해제
- Protected: 프로젝트 정책에 따라 선택

화면에 표시된 Runner authentication token을 사용해 등록한다.

```bash
read -rsp 'Runner token: ' RUNNER_TOKEN && echo
docker compose exec gitlab-runner gitlab-runner register \
  --non-interactive \
  --url 'https://lab.ssafy.com' \
  --token "$RUNNER_TOKEN" \
  --executor 'docker' \
  --docker-image 'alpine:3.20' \
  --docker-network-mode 'sonar-network' \
  --docker-memory '2g' \
  --docker-cpus '2' \
  --description 'EC2 SonarQube Runner'
unset RUNNER_TOKEN
```

동시 job은 1개로 제한한다.

```bash
docker compose exec gitlab-runner \
  sed -i 's/^concurrent = .*/concurrent = 1/' /etc/gitlab-runner/config.toml
docker compose restart gitlab-runner
docker compose exec gitlab-runner gitlab-runner verify
```

## 5. GitLab CI/CD 변수

GitLab 프로젝트의 **Settings > CI/CD > Variables**에 등록한다.

| Key | 용도 | 설정 |
| --- | --- | --- |
| `SONAR_TOKEN` | EC2 SonarQube 분석 토큰 | Masked |
| `GITLAB_REVIEW_TOKEN` | MR 댓글 등록 토큰 | Masked |
| `GMS_API_KEY` | GMS 한국어 리뷰 생성 키 | Masked and hidden |

토큰은 저장소나 Compose 파일에 입력하지 않는다.
GMS에는 선택된 SonarQube 이슈와 해당 라인 주변 코드가 전송된다.

## 6. 상태 확인

```bash
docker compose ps
docker stats --no-stream a106-sonarqube a106-sonar-db a106-gitlab-runner
curl -s http://127.0.0.1:9000/sonarqube/api/system/status
```

MR 파이프라인의 `sonarqube-analysis`와 `sonarqube-mr-comment` job이 모두
성공하면 연동이 완료된 것이다.
