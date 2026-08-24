# 공유 커밋/브랜치 컨벤션 정의 — commit-msg hook과 GitLab CI(.gitlab-ci.yml)가
# 이 파일 하나를 함께 참조한다. 규칙을 바꿀 때는 여기만 수정하면 로컬/서버가 항상 일치한다.
# 상세 설명: Docs/GIT_CONVENTION.md
#
# 이모지는 일부러 grep -E 정규식에 넣지 않는다: Windows Git Bash의 grep은
# 4바이트 UTF-8(astral) 이모지(🐛 📝 🔧 💄 등)를 정규식 문자 클래스 안에서
# 전혀 인식하지 못하는 버그가 있다(같은 바이트열끼리도 매칭 실패). 대신 첫 단어를
# shell case 패턴으로 검사한다 — case는 이 문제가 없다. 나머지(type/scope/설명/
# 이슈키)는 전부 ASCII라 grep -E로 그대로 검사한다.

# grep 정규식 해석이 로케일마다 달라지는 문제를 차단한다
# (예: en_US.UTF-8에서 한글 범위(가-힣) 컴파일 실패, '.'가 한글 매칭 실패).
# LC_ALL=C의 바이트 단위 매칭은 모든 머신과 CI(alpine grep)에서 동일하게 동작한다.
export LC_ALL=C

is_valid_emoji() {
  case "$1" in
    "✨"|"🐛"|"♻️"|"📝"|"✅"|"🔧"|"💄") return 0 ;;
    *) return 1 ;;
  esac
}

JIRA_KEY_PATTERN='S15P21A106-[0-9]+'
# emoji를 뗀 나머지 부분만 검사하는 패턴. 사용법: emoji 검증은 is_valid_emoji로,
# 나머지는 "${subject#* }" 등으로 첫 단어를 잘라낸 뒤 이 패턴으로 검사한다.
MSG_REST_PATTERN='^(feat|fix|refactor|docs|test|chore|style)(\([a-z0-9_-]+\))?: .+ \('"$JIRA_KEY_PATTERN"'\)$'

STATIC_BRANCHES="main develop"
# 설명 부분은 한글/영문/숫자/하이픈을 허용한다 (한글 음절 U+AC00~U+D7A3는
# 3바이트 UTF-8이라 위 이모지 astral 버그와 무관하게 grep -E에서 정상 매칭된다).
BRANCH_PATTERN='^(feature|hotfix)/S15P21A106-[0-9]+-[a-zA-Z0-9가-힣-]+$'
RELEASE_PATTERN='^release/v[0-9]+\.[0-9]+\.[0-9]+$'
