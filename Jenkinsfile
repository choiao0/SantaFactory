// 폴더 번호 접두사를 바꾸면 아래 4_Web/... 경로 문자열도 같이 고칠 것.
// 안 고치면 에러 없이 "변경 없음"으로 빠져 배포가 중단됨.

pipeline {
    agent any

    options {
        disableConcurrentBuilds()
        timestamps()
    }

    environment {
        STATE_DIR  = '/var/lib/jenkins/deploy-state'
        SHA_FILE   = '/var/lib/jenkins/deploy-state/last-deployed.sha'
        WEB_ROOT   = '/srv/www'
        KEEP_COUNT = '3'
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

                    env.BUILD_BE = (fullBuild || common ||
                        paths.contains('\n4_Web/SantaFactoryBE/')) ? 'true' : 'false'
                    env.BUILD_FE = (fullBuild || common ||
                        paths.contains('\n4_Web/SantaFactoryFE/')) ? 'true' : 'false'

                    echo "배포 대상: backend=${env.BUILD_BE}, frontend=${env.BUILD_FE}"
                }
            }
        }

        stage('백엔드 빌드·배포') {
            when { expression { env.SKIP_ALL != 'true' && env.BUILD_BE == 'true' } }
            steps {
                withCredentials([file(credentialsId: 'app-env', variable: 'APP_ENV_FILE')]) {
                    sh '''
                        cp "$APP_ENV_FILE" 4_Web/.env
                        docker compose -f 4_Web/docker-compose.yml build backend
                        docker compose -f 4_Web/docker-compose.yml up -d --no-deps backend
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
                sh '''
                    docker build -t santafactory-fe:$BUILD_NUMBER 4_Web/SantaFactoryFE
                    mkdir -p "$WEB_ROOT/santafactory-$BUILD_NUMBER"
                    docker run --rm -v "$WEB_ROOT/santafactory-$BUILD_NUMBER":/out \
                        santafactory-fe:$BUILD_NUMBER sh -c "cp -r /app/dist/. /out/"
                    ln -sfn "$WEB_ROOT/santafactory-$BUILD_NUMBER" "$WEB_ROOT/current.tmp"
                    mv -T "$WEB_ROOT/current.tmp" "$WEB_ROOT/current"
                '''
                sh '''
                    cd "$WEB_ROOT"
                    ls -1d santafactory-* 2>/dev/null | sort -t- -k2 -n | head -n -"$KEEP_COUNT" | xargs -r rm -rf
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
            sh 'rm -f 4_Web/.env'
        }
    }
}
