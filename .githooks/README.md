# Git Hooks

커밋 메시지 / 브랜치명이 팀 컨벤션(Jira 키 포함)을 따르는지 커밋 시점에
바로 검사하고, 브랜치명의 Jira 키를 커밋 메시지에 자동으로 채워준다.
자세한 규칙은 [`Docs/GIT_CONVENTION.md`](../Docs/GIT_CONVENTION.md) 참고.

## 활성화 (팀원별 최초 1회)

```
git config core.hooksPath .githooks
```

이 레포는 Git LFS를 사용하므로 **git-lfs 설치가 필수**다. 미설치 상태에서는
LFS 훅(`pre-push` 등)이 push를 차단한다. [git-lfs.com](https://git-lfs.com)에서
설치 후 `git lfs install --skip-repo`를 한 번 실행하면 된다
(`--skip-repo`: `.git/hooks`가 아닌 `.githooks`의 공유 훅을 그대로 쓰기 위함).

이후 로컬에서 컨벤션에 맞지 않는 커밋은 `git commit` 시점에 즉시 거부된다.
같은 규칙이 GitLab CI(`.gitlab-ci.yml`)에서도 MR 파이프라인 단계에서
한 번 더 검증되므로, 이 hook을 설정하지 않아도 서버 단에서 최종적으로 걸러진다.
(터미널이든 VSCode의 소스 제어 패널이든 내부적으로 `git commit`을 호출하므로
hook은 어떤 환경에서 커밋하든 동일하게 동작한다.)

## 파일 구성

- `commit-convention.sh` — 정규식(이모지/타입, 브랜치 패턴)을 정의하는 단일 소스.
  `.gitlab-ci.yml`의 lint job도 이 파일을 그대로 source해서 쓰므로, 규칙을 바꿀 때
  이 파일 하나만 고치면 로컬 hook과 CI가 항상 같은 규칙을 검사한다.
- `commit-msg` — 커밋 메시지/브랜치명이 컨벤션을 지키는지 검사, 어기면 커밋을 막는다.
  merge 커밋은 검사에서 제외된다.
- `pre-push` / `post-checkout` / `post-commit` / `post-merge` — Git LFS 훅.
  대용량 파일을 LFS로 주고받기 위해 필요하다 (git-lfs 설치 필수, 위 참고).
- `prepare-commit-msg` — 현재 브랜치명에서 Jira 키(`S15P21A106-123`)를 추출해
  커밋 메시지 제목 끝에 `(S15P21A106-123)`를 자동으로 붙여준다. 이미 이슈 키가
  포함돼 있으면 손대지 않는다. VSCode의 Jira 확장을 어떤 걸 쓰든 상관없이,
  Jira 키가 포함된 브랜치(`feature/S15P21A106-19-...`)에서 커밋하기만
  하면 자동으로 채워진다.
