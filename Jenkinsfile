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
        COMPOSE_HOST = 'docker compose -f 3_FMS/infra/compose.host-orch.yml'   // (-249) 검증 오케스트레이터
        KEEP_COUNT  = '3'
        // FMS 워커 배포 방식 (S15P21A106-248). Jenkins 전역 환경변수로 바꾼다 — compose: EC2 에서 compose 워커(지금까지),
        // k3s: 사설 레지스트리에 push 하고 k3s 가 GCP 노드에 배치(3_FMS/infra/k8s/README.md). 되돌리기는 값만 compose 로.
        FMS_DEPLOY   = "${env.FMS_DEPLOY ?: 'compose'}"
        // 웹 계층(backend·pdf·frontend) 배포 방식 (S15P21A106-258). 같은 패턴 — compose: EC2 compose(지금까지),
        // k3s: 레지스트리 push 뒤 4_Web/k8s 매니페스트를 apply 해 롤링 배포(4_Web/k8s/README.md). 값이 없으면 compose.
        WEB_DEPLOY   = "${env.WEB_DEPLOY ?: 'compose'}"
        REGISTRY      = '127.0.0.1:5000'        // EC2 가 push 하는 주소(루프백 평문 허용)
        REGISTRY_NODE = 'j15a106.p.ssafy.io'    // 노드가 pull 하는 주소 — nginx 443 /v2/ → 루프백 레지스트리 (3_FMS/infra/nginx/registry-v2.conf, -249). tailnet 미사용
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

                    // 4_Web/k8s/ 는 매니페스트만 바뀌어도(자원·probe) 다시 배포해야 반영된다 (-258)
                    env.BUILD_BE = (fullBuild || common ||
                        paths.contains('\n4_Web/SantaFactoryBE/') ||
                        paths.contains('\n4_Web/pdf/') ||
                        paths.contains('\n4_Web/k8s/')) ? 'true' : 'false'
                    env.BUILD_FE = (fullBuild || common ||
                        paths.contains('\n4_Web/SantaFactoryFE/') ||
                        paths.contains('\n4_Web/k8s/')) ? 'true' : 'false'
                    env.BUILD_FMS = (fullBuild || common ||
                        changedList.any { it.startsWith('3_FMS/') &&
                            !it.startsWith('3_FMS/infra/emqx/') &&
                            !it.startsWith('3_FMS/docs/') }) ? 'true' : 'false'
                    env.BUILD_EMQX = (fullBuild || common ||
                        changedList.any { it.startsWith('3_FMS/infra/emqx/') }) ? 'true' : 'false'
                    // (-249) host-orch 는 별도 compose 스택이라 따로 본다. BUILD_FMS 에도 걸리지만(3_FMS/ 밑) 그쪽은 워커·core 만 다룬다.
                    env.BUILD_HOST_ORCH = (fullBuild || common ||
                        changedList.any { it.startsWith('3_FMS/host_orch/') ||
                            it == '3_FMS/infra/compose.host-orch.yml' ||
                            it == '3_FMS/infra/host_orch.Dockerfile' }) ? 'true' : 'false'

                    echo "배포 대상: backend=${env.BUILD_BE}, frontend=${env.BUILD_FE}, fms=${env.BUILD_FMS}(워커+core), emqx=${env.BUILD_EMQX}, host-orch=${env.BUILD_HOST_ORCH}"

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
                        docker tag santafactory-pdf:latest santafactory-pdf:$BUILD_NUMBER
                    '''
                }
                script {
                    if (env.WEB_DEPLOY == 'k3s') {
                        // k3s (-258): 새 파드가 readiness 를 통과한 뒤에야 옛 파드가 내려간다(4_Web/k8s/backend.yaml). compose 쪽은 롤아웃이 끝난 뒤 stop.
                        withCredentials([file(credentialsId: 'k3s-kubeconfig', variable: 'KUBECONFIG')]) {
                            sh '''
                                for img in santafactory-be santafactory-pdf; do
                                    docker tag $img:$BUILD_NUMBER $REGISTRY/$img:$BUILD_NUMBER
                                    docker push $REGISTRY/$img:$BUILD_NUMBER
                                done
                                # env 는 compose 파일이 조립한 그대로 Secret 으로 — db·rabbitmq·redis·pdf 이름은 4_Web/k8s 의 Service 가 풀어 준다
                                $COMPOSE config --format json \\
                                    | python3 -c 'import sys,json; [print(f"{k}={v}") for k,v in json.load(sys.stdin)["services"]["backend"]["environment"].items()]' \\
                                    > 4_Web/.backend.env
                                kubectl apply -f 4_Web/k8s/namespace.yaml -f 4_Web/k8s/compose-services.yaml
                                kubectl -n web create secret generic backend-env --from-env-file=4_Web/.backend.env --dry-run=client -o yaml | kubectl apply -f -
                                sed -E "s#^( *image: ).*santafactory-pdf:.*#\\1$REGISTRY_NODE/santafactory-pdf:$BUILD_NUMBER#" 4_Web/k8s/pdf.yaml | kubectl apply -f -
                                sed -E "s#^( *image: ).*santafactory-be:.*#\\1$REGISTRY_NODE/santafactory-be:$BUILD_NUMBER#" 4_Web/k8s/backend.yaml | kubectl apply -f -
                                for d in pdf backend; do
                                    if ! kubectl -n web rollout status deployment/$d --timeout=300s; then
                                        echo "k3s $d 롤아웃이 300초 안에 끝나지 않음"
                                        kubectl -n web get pods -o wide || true
                                        kubectl -n web describe deployment/$d | tail -20 || true
                                        exit 1
                                    fi
                                done
                                kubectl -n web get pods -o wide
                                $COMPOSE stop backend pdf
                                for img in santafactory-be santafactory-pdf; do
                                    REGISTRY=$REGISTRY bash 3_FMS/infra/k8s/registry-prune.sh $img "$KEEP_COUNT" || true
                                done
                            '''
                        }
                    } else {
                        sh '''
                            $COMPOSE up -d backend
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
                    '''
                }
                script {
                    if (env.WEB_DEPLOY == 'k3s') {
                        withCredentials([file(credentialsId: 'k3s-kubeconfig', variable: 'KUBECONFIG')]) {
                            sh '''
                                docker tag santafactory-fe:$BUILD_NUMBER $REGISTRY/santafactory-fe:$BUILD_NUMBER
                                docker push $REGISTRY/santafactory-fe:$BUILD_NUMBER
                                kubectl apply -f 4_Web/k8s/namespace.yaml
                                sed -E "s#^( *image: ).*santafactory-fe:.*#\\1$REGISTRY_NODE/santafactory-fe:$BUILD_NUMBER#" 4_Web/k8s/frontend.yaml | kubectl apply -f -
                                if ! kubectl -n web rollout status deployment/frontend --timeout=120s; then
                                    echo "k3s frontend 롤아웃이 120초 안에 끝나지 않음"
                                    kubectl -n web describe deployment/frontend | tail -20 || true
                                    exit 1
                                fi
                                $COMPOSE stop frontend
                                REGISTRY=$REGISTRY bash 3_FMS/infra/k8s/registry-prune.sh santafactory-fe "$KEEP_COUNT" || true
                            '''
                        }
                    } else {
                        sh '''
                            $COMPOSE up -d frontend
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
                    '''
                }
                script {
                    if (env.FMS_DEPLOY == 'k3s') {
                        // k3s: 12개가 새 이미지로 전부 뜬 것을 확인한 뒤에야 EC2 compose 워커를 내린다 — 순서를 바꾸면 노드 합류 전 배포에서 워커가 0 이 된다.
                        withCredentials([file(credentialsId: 'k3s-kubeconfig', variable: 'KUBECONFIG')]) {
                            sh '''
                                docker tag fms-estimate-worker:$BUILD_NUMBER $REGISTRY/fms-estimate-worker:$BUILD_NUMBER
                                docker push $REGISTRY/fms-estimate-worker:$BUILD_NUMBER
                                # 매니페스트가 기준(-249): 자원·개수·정책 변경도 release 로 나간다. image 줄만 이번 빌드 번호로 바꿔 넣는다
                                # (파일의 :latest 는 첫 적용용 자리). apply 뒤 set image 를 따로 하면 latest 로 한 번 더 롤아웃이 돌아 합쳤다.
                                kubectl apply -f 3_FMS/infra/k8s/namespace.yaml
                                sed -E "s#^( *image: ).*fms-estimate-worker:.*#\\1$REGISTRY_NODE/fms-estimate-worker:$BUILD_NUMBER#" \\
                                    3_FMS/infra/k8s/sim-worker-deployment.yaml | kubectl apply -f -
                                if ! kubectl -n fms rollout status deployment/sim-worker --timeout=600s; then
                                    echo "k3s 워커 롤아웃이 600초 안에 끝나지 않음"
                                    kubectl -n fms get pods -o wide || true
                                    kubectl -n fms describe deployment/sim-worker | tail -20 || true
                                    exit 1
                                fi
                                kubectl -n fms get pods -o wide
                                $COMPOSE_FMS up -d --scale estimate-worker=0
                                REGISTRY=$REGISTRY bash 3_FMS/infra/k8s/registry-prune.sh fms-estimate-worker "$KEEP_COUNT" || true
                            '''
                        }
                    } else {
                        sh '''
                            # 워커는 여러 개(compose replicas, 기본 2)라 컨테이너 전부가 running 이어야 통과.
                            # WORKER_REPLICAS=0 (GCP 워커가 처리, 3_FMS/infra/gcp/README.md) 이면 EC2 워커를 올리지 않고 끝낸다.
                            want=${WORKER_REPLICAS:-2}
                            WORKER_REPLICAS=$want $COMPOSE_FMS up -d
                            if [ "$want" = "0" ]; then
                                echo "EC2 FMS 워커 0개 (WORKER_REPLICAS=0)"
                                exit 0
                            fi
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

        stage('host-orch 빌드·배포') {
            // (-249) 검증 오케스트레이터. fms-core 처럼 backbone(external) + santafactory 네트워크가 먼저 있어야 한다.
            // 자격은 둘 — infra/.env(RabbitMQ, app-env 에서 추출) · infra/emqx/.env(MQTT_PW_HOST_ORCH, emqx-env).
            // 09-18 이전에는 EC2 ~/host-orch 사본에서 수동 배포했다. compose 프로젝트 이름(fms-host-orch)과 컨테이너 이름이 같아
            // 첫 Jenkins 배포가 그 컨테이너를 그대로 넘겨받는다.
            when { expression { env.SKIP_ALL != 'true' && env.BUILD_HOST_ORCH == 'true' } }
            steps {
                withCredentials([file(credentialsId: 'app-env', variable: 'APP_ENV_FILE'),
                                 file(credentialsId: 'emqx-env', variable: 'EMQX_ENV_FILE')]) {
                    sh '''
                        grep -E "^(RABBITMQ_USER|RABBITMQ_PASSWORD)=" "$APP_ENV_FILE" > 3_FMS/infra/.env
                        tr -d '\\r' < "$EMQX_ENV_FILE" > 3_FMS/infra/emqx/.env
                        $COMPOSE_HOST build
                        docker tag fms-host-orch:latest fms-host-orch:$BUILD_NUMBER
                        $COMPOSE_HOST up -d
                    '''
                }
                sh '''
                    # fms-core 와 같은 기준 — running 을 본 뒤 10초 두고 RestartCount 0 까지 확인한다.
                    cid=""
                    for i in $(seq 1 30); do
                        cid=$($COMPOSE_HOST ps -q host-orch)
                        if [ -n "$cid" ] && [ "$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null)" = "running" ]; then
                            break
                        fi
                        sleep 2
                    done
                    if [ -z "$cid" ]; then
                        echo "host-orch 컨테이너가 60초 안에 뜨지 않음"
                        $COMPOSE_HOST logs --tail 100 || true
                        exit 1
                    fi
                    sleep 10
                    status=$(docker inspect -f '{{.State.Status}}' "$cid")
                    restarts=$(docker inspect -f '{{.RestartCount}}' "$cid")
                    if [ "$status" != "running" ] || [ "$restarts" -gt 0 ]; then
                        echo "host-orch 가 안정적으로 뜨지 않음 (status=$status, 재시작 $restarts 회)"
                        $COMPOSE_HOST logs --tail 100 || true
                        exit 1
                    fi
                    echo "host-orch 기동 확인 (재시작 0회)"
                '''
            }
        }

        stage('이미지 정리') {
            when { expression { env.SKIP_ALL != 'true' } }
            steps {
                sh '''
                    for img in santafactory-be santafactory-fe santafactory-pdf fms-estimate-worker fms-core fms-host-orch; do
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
            sh 'rm -f 4_Web/.env 4_Web/.backend.env 3_FMS/infra/.env.estimate 3_FMS/infra/.env 3_FMS/infra/emqx/.env'
        }
    }
}
