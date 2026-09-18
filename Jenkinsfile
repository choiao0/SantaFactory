// 폴더 번호 접두사를 바꾸면 아래 4_Web/..., 3_FMS/... 경로 문자열도 같이 고칠 것.
// 안 고치면 에러 없이 "변경 없음"으로 빠져 배포가 중단됨.

pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        timestamps()
    }

    environment {
        STATE_DIR   = '/var/lib/jenkins/deploy-state'
        SHA_FILE    = '/var/lib/jenkins/deploy-state/last-deployed.sha'
        COMPOSE     = 'docker compose -f 4_Web/docker-compose.yml'
        COMPOSE_FMS  = 'docker compose -f 3_FMS/infra/compose.estimate.yml --env-file 3_FMS/infra/.env.estimate'
        COMPOSE_EMQX = 'docker compose -f 3_FMS/infra/emqx/compose.yml'
        COMPOSE_CORE = 'docker compose -f 3_FMS/infra/compose.fms-core.yml'
        KEEP_COUNT  = '3'
    }

    stages {

        stage('브랜치 확인') {
            steps {
                script {
                    def branch = env.GIT_BRANCH ?: sh(returnStdout: true,
                        script: 'git rev-parse --abbrev-ref HEAD').trim()
                    if (branch.tokenize('/').last() != 'release') {
                        echo "release 브랜치가 아님(${branch}) — 배포하지 않고 종료"
                        env.SKIP_ALL = 'true'
                    }
                }
            }
        }

        stage('변경 감지') {
            when { expression { env.SKIP_ALL != 'true' } }
            steps {
                script {
                    sh 'mkdir -p "$STATE_DIR"'

                    def baseSha = ''
                    if (fileExists(env.SHA_FILE)) {
                        baseSha = readFile(env.SHA_FILE).trim()
                    }

                    def fullBuild = true
                    def changedFiles = ''
                    if (baseSha && sh(returnStatus: true, script: "git cat-file -e ${baseSha}^{commit}") == 0) {
                        changedFiles = sh(returnStdout: true, script: "git diff --name-only ${baseSha} HEAD")
                        fullBuild = false
                        echo "기준 ${baseSha.take(8)} 이후 변경:\n${changedFiles.trim() ?: '(없음)'}"
                    } else {
                        echo '기준 SHA 없음/유실 — 전체 빌드'
                    }

                    def paths = '\n' + changedFiles + '\n'
                    def common = paths.contains('\n4_Web/docker-compose.yml\n') ||
                                 paths.contains('\nJenkinsfile\n')
                    // FMS/EMQX 는 같은 3_FMS/ 트리 밑에서도 서로 다른 스택이라 줄 단위로 갈라 본다.
                    def changedList = changedFiles.trim() ? changedFiles.trim().tokenize('\n') : []

                    env.BUILD_BE = (fullBuild || common ||
                        paths.contains('\n4_Web/SantaFactoryBE/') ||
                        paths.contains('\n4_Web/pdf/')) ? 'true' : 'false'
                    env.BUILD_FE = (fullBuild || common ||
                        paths.contains('\n4_Web/SantaFactoryFE/')) ? 'true' : 'false'
                    env.BUILD_FMS = (fullBuild || common ||
                        changedList.any { it.startsWith('3_FMS/') &&
                            !it.startsWith('3_FMS/infra/emqx/') &&
                            !it.startsWith('3_FMS/docs/') }) ? 'true' : 'false'
                    env.BUILD_EMQX = (fullBuild || common ||
                        changedList.any { it.startsWith('3_FMS/infra/emqx/') }) ? 'true' : 'false'

                    echo "배포 대상: backend=${env.BUILD_BE}, frontend=${env.BUILD_FE}, fms=${env.BUILD_FMS}(워커+core), emqx=${env.BUILD_EMQX}"

                    // 표시는 BE/FE 와 같은 레벨로 맞춘다 — EMQX 는 FMS 도메인의 일부라 별도 항목으로 안 보이고 FMS 에 흡수.
                    def fmsShown = (env.BUILD_FMS == 'true' || env.BUILD_EMQX == 'true')
                    currentBuild.description =
                        "BE ${env.BUILD_BE == 'true' ? '✅' : '⬜'}  " +
                        "FE ${env.BUILD_FE == 'true' ? '✅' : '⬜'}  " +
                        "FMS ${fmsShown ? '✅' : '⬜'}"
                }
            }
        }

        stage('백엔드 빌드·배포') {
            when { expression { env.SKIP_ALL != 'true' && env.BUILD_BE == 'true' } }
            steps {
                withCredentials([file(credentialsId: 'app-env', variable: 'APP_ENV_FILE')]) {
                    sh '''
                        cp -f "$APP_ENV_FILE" 4_Web/.env
                        $COMPOSE build backend pdf
                        docker tag santafactory-be:latest santafactory-be:$BUILD_NUMBER
                        $COMPOSE up -d backend
                    '''
                }
                sh '''
                    for i in $(seq 1 75); do
                        code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ || true)
                        if [ "$code" != "000" ]; then
                            echo "backend 기동 확인 (HTTP $code)"
                            exit 0
                        fi
                        sleep 2
                    done
                    echo "backend 가 150초 안에 응답하지 않음"
                    docker logs --tail 100 a106-backend || true
                    exit 1
                '''
            }
        }

        stage('프론트 빌드·배포') {
            when { expression { env.SKIP_ALL != 'true' && env.BUILD_FE == 'true' } }
            steps {
                withCredentials([file(credentialsId: 'app-env', variable: 'APP_ENV_FILE')]) {
                    sh '''
                        cp -f "$APP_ENV_FILE" 4_Web/.env
                        $COMPOSE build frontend
                        docker tag santafactory-fe:latest santafactory-fe:$BUILD_NUMBER
                        $COMPOSE up -d frontend
                    '''
                }
                sh '''
                    for i in $(seq 1 15); do
                        code=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/ || true)
                        if [ "$code" = "200" ]; then
                            echo "frontend 기동 확인 (HTTP $code)"
                            exit 0
                        fi
                        sleep 2
                    done
                    echo "frontend 가 30초 안에 응답하지 않음"
                    docker logs --tail 50 a106-frontend || true
                    exit 1
                '''
            }
        }

        stage('FMS 워커 빌드·배포') {
            // santafactory_default 네트워크가 external 이라 4_Web 스택(백엔드 스테이지에서 rabbitmq 까지 같이 뜸)이 먼저 있어야 한다.
            when { expression { env.SKIP_ALL != 'true' && env.BUILD_FMS == 'true' } }
            steps {
                withCredentials([file(credentialsId: 'app-env', variable: 'APP_ENV_FILE')]) {
                    sh '''
                        grep -E "^(RABBITMQ_USER|RABBITMQ_PASSWORD)=" "$APP_ENV_FILE" > 3_FMS/infra/.env.estimate
                        $COMPOSE_FMS build
                        docker tag fms-estimate-worker:latest fms-estimate-worker:$BUILD_NUMBER
                        $COMPOSE_FMS up -d
                    '''
                }
                sh '''
                    # 워커는 여러 개(compose replicas, 기본 2)라 컨테이너 전부가 running 이어야 통과.
                    for i in $(seq 1 30); do
                        cids=$($COMPOSE_FMS ps -q estimate-worker)
                        total=$(echo "$cids" | grep -c . || true)
                        running=0
                        for cid in $cids; do
                            if [ "$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null)" = "running" ]; then
                                running=$((running + 1))
                            fi
                        done
                        if [ "$total" -gt 0 ] && [ "$running" -eq "$total" ]; then
                            echo "FMS 워커 ${running}개 기동 확인"
                            exit 0
                        fi
                        sleep 2
                    done
                    echo "FMS 워커가 60초 안에 전부 기동하지 않음 (running ${running}/${total})"
                    $COMPOSE_FMS logs --tail 100 || true
                    exit 1
                '''
            }
        }

        stage('EMQX 배포') {
            // RabbitMQ 스택과 무관한 독립 브로커 — 순서 의존성 없음.
            when { expression { env.SKIP_ALL != 'true' && env.BUILD_EMQX == 'true' } }
            steps {
                withCredentials([file(credentialsId: 'emqx-env', variable: 'EMQX_ENV_FILE')]) {
                    sh '''
                        tr -d '\\r' < "$EMQX_ENV_FILE" > 3_FMS/infra/emqx/.env
                        3_FMS/infra/emqx/bootstrap_users.sh
                        $COMPOSE_EMQX up -d
                    '''
                }
                sh '''
                    for i in $(seq 1 30); do
                        status=$(docker inspect -f "{{.State.Health.Status}}" emqx 2>/dev/null || true)
                        if [ "$status" = "healthy" ]; then
                            echo "EMQX 기동 확인"
                            exit 0
                        fi
                        sleep 2
                    done
                    echo "EMQX 가 60초 안에 healthy 상태가 되지 않음"
                    $COMPOSE_EMQX logs --tail 100 || true
                    exit 1
                '''
            }
        }

        stage('fms-core 빌드·배포') {
            // EMQX 뒤에 온다 — compose.fms-core.yml 의 backbone 네트워크가 external(backbone_default)이라 EMQX 스택이 먼저 있어야 한다.
            // 자격증명은 EMQX 와 같은 파일(infra/emqx/.env, MQTT_PW_FMS_CORE)이라 여기서도 쓴다 — EMQX 스테이지는 안 돌 수 있다(BUILD_EMQX=false).
            when { expression { env.SKIP_ALL != 'true' && env.BUILD_FMS == 'true' } }
            steps {
                withCredentials([file(credentialsId: 'emqx-env', variable: 'EMQX_ENV_FILE')]) {
                    sh '''
                        tr -d '\\r' < "$EMQX_ENV_FILE" > 3_FMS/infra/emqx/.env
                        $COMPOSE_CORE build
                        docker tag fms-core:latest fms-core:$BUILD_NUMBER
                        $COMPOSE_CORE up -d
                    '''
                }
                sh '''
                    # 이 컨테이너는 HTTP 포트가 없어 running 으로만 본다. 다만 restart: unless-stopped 라
                    # **기동 직후 한 번 running 을 보는 것으로는 부족하다** — import 오류(-234 의 numba 누락이 그랬다)는
                    # 재시작 루프로 나타나므로, 자리 잡을 시간을 준 뒤 RestartCount 까지 확인한다.
                    cid=""
                    for i in $(seq 1 30); do
                        cid=$($COMPOSE_CORE ps -q fms-core)
                        if [ -n "$cid" ] && [ "$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null)" = "running" ]; then
                            break
                        fi
                        sleep 2
                    done
                    if [ -z "$cid" ]; then
                        echo "fms-core 컨테이너가 60초 안에 뜨지 않음"
                        $COMPOSE_CORE logs --tail 100 || true
                        exit 1
                    fi
                    sleep 10
                    status=$(docker inspect -f '{{.State.Status}}' "$cid")
                    restarts=$(docker inspect -f '{{.RestartCount}}' "$cid")
                    if [ "$status" != "running" ] || [ "$restarts" -gt 0 ]; then
                        echo "fms-core 가 안정적으로 뜨지 않음 (status=$status, 재시작 $restarts 회)"
                        $COMPOSE_CORE logs --tail 100 || true
                        exit 1
                    fi
                    echo "fms-core 기동 확인 (재시작 0회)"
                '''
            }
        }

        stage('이미지 정리') {
            when { expression { env.SKIP_ALL != 'true' } }
            steps {
                sh '''
                    for img in santafactory-be santafactory-fe fms-estimate-worker fms-core; do
                        docker images "$img" --format '{{.Tag}}' \
                            | grep -E '^[0-9]+$' | sort -n | head -n -"$KEEP_COUNT" \
                            | xargs -r -I{} docker rmi "$img:{}"
                    done
                    docker image prune -f > /dev/null
                '''
            }
        }
    }

    post {
        success {
            script {
                if (env.SKIP_ALL != 'true') {
                    sh 'git rev-parse HEAD > "$SHA_FILE"'
                }
            }
        }
        always {
            sh 'rm -f 4_Web/.env 3_FMS/infra/.env.estimate 3_FMS/infra/emqx/.env'
        }
    }
}
