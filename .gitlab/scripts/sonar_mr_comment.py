#!/usr/bin/env python3
"""Post the latest local SonarQube analysis summary to a GitLab MR."""

import base64
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


MARKER = "<!-- sonar-local-review -->"
PROJECT_KEY = "S15P21A106"
MAX_REVIEW_ISSUES = 3
REVIEW_SEVERITIES = {"BLOCKER", "CRITICAL", "MAJOR"}
SEVERITY_RANK = {"BLOCKER": 3, "CRITICAL": 2, "MAJOR": 1}
TYPE_RANK = {"VULNERABILITY": 3, "BUG": 2, "CODE_SMELL": 1}
DIFF_HUNK_PATTERN = re.compile(
    r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@"
)


def require_env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def request_json(url, headers=None, data=None, method="GET", timeout=30):
    request = urllib.request.Request(
        url,
        headers=headers or {},
        data=data,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"HTTP {error.code} while requesting {url}: {detail}"
        ) from error


def sonar_get(base_url, headers, path, params):
    query = urllib.parse.urlencode(params)
    return request_json(f"{base_url}{path}?{query}", headers=headers)


def fetch_merge_request_diffs(base_url, project_id, mr_iid, headers):
    """Fetch every available file diff for the current GitLab MR."""
    encoded_project_id = urllib.parse.quote(project_id, safe="")
    encoded_mr_iid = urllib.parse.quote(mr_iid, safe="")
    endpoint = (
        f"{base_url}/projects/{encoded_project_id}"
        f"/merge_requests/{encoded_mr_iid}/diffs"
    )
    diffs = []
    page = 1
    per_page = 100

    while True:
        query = urllib.parse.urlencode({"page": page, "per_page": per_page})
        page_diffs = request_json(f"{endpoint}?{query}", headers=headers)
        if not isinstance(page_diffs, list):
            raise RuntimeError("GitLab MR diffs API returned an unexpected response")
        diffs.extend(page_diffs)
        if len(page_diffs) < per_page:
            return diffs
        page += 1


def changed_new_lines(diff_text):
    """Return the new-side line numbers added or modified by a unified diff."""
    changed = set()
    new_line = None

    for text in (diff_text or "").splitlines():
        hunk = DIFF_HUNK_PATTERN.match(text)
        if hunk:
            new_line = int(hunk.group(1))
            continue
        if new_line is None or text.startswith("\\"):
            continue
        if text.startswith("+"):
            changed.add(new_line)
            new_line += 1
        elif text.startswith("-"):
            continue
        elif text.startswith(" "):
            new_line += 1

    return changed


def build_changed_scope(diffs):
    """Build changed-file and exact changed-new-line sets from GitLab diffs."""
    changed_files = set()
    changed_lines = {}

    for item in diffs:
        if item.get("deleted_file"):
            continue
        path = (item.get("new_path") or "").replace("\\", "/").lstrip("./")
        if not path:
            continue
        changed_files.add(path)
        lines = changed_new_lines(item.get("diff", ""))
        changed_lines.setdefault(path, set()).update(lines)
        if item.get("too_large") or item.get("collapsed"):
            print(
                f"GitLab did not provide the complete diff for {path}; "
                "line-level SonarQube issues may be omitted.",
                file=sys.stderr,
            )

    return changed_files, changed_lines


def fetch_sonar_issues(base_url, headers):
    """Fetch every unresolved issue so MR filtering is not biased by API order."""
    issues = []
    page = 1
    page_size = 500

    while True:
        result = sonar_get(
            base_url,
            headers,
            "/api/issues/search",
            {
                "componentKeys": PROJECT_KEY,
                "resolved": "false",
                "ps": page_size,
                "p": page,
            },
        )
        page_issues = result.get("issues", [])
        issues.extend(page_issues)
        total = result.get("paging", {}).get("total", len(issues))
        if not page_issues or len(issues) >= total:
            return issues
        page += 1


def issue_path(issue):
    return issue.get("component", "").split(":", 1)[-1].replace("\\", "/").lstrip("./")


def issue_line(issue):
    value = issue.get("line")
    if value is None:
        value = issue.get("textRange", {}).get("startLine")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def issue_priority(issue):
    """Prioritize runtime/security issues before maintainability findings."""
    severity = issue.get("severity", "UNKNOWN")
    issue_type = issue.get("type", "ISSUE")
    is_runtime_or_security = issue_type in {"BUG", "VULNERABILITY"}
    if is_runtime_or_security and severity in {"BLOCKER", "CRITICAL"}:
        bucket = 4
    elif is_runtime_or_security:
        bucket = 3
    elif severity in {"BLOCKER", "CRITICAL"}:
        bucket = 2
    else:
        bucket = 1
    return (
        bucket,
        SEVERITY_RANK.get(severity, 0),
        TYPE_RANK.get(issue_type, 0),
    )


def select_mr_issues(issues, changed_files, changed_lines, limit=MAX_REVIEW_ISSUES):
    """Select and group major SonarQube issues located in the current MR diff."""
    grouped = {}

    for issue in issues:
        severity = issue.get("severity", "UNKNOWN")
        if severity not in REVIEW_SEVERITIES:
            continue

        path = issue_path(issue)
        if path not in changed_files:
            continue

        line_number = issue_line(issue)
        if line_number is not None and line_number not in changed_lines.get(path, set()):
            continue

        rule = issue.get("rule") or issue.get("message", "")
        key = (path, rule)
        if key not in grouped:
            selected = dict(issue)
            selected["_path"] = path
            selected["_lines"] = set()
            selected["_messages"] = []
            grouped[key] = selected
        if line_number is not None:
            grouped[key]["_lines"].add(line_number)
        message = issue.get("message", "")
        if message and message not in grouped[key]["_messages"]:
            grouped[key]["_messages"].append(message)

    ranked = sorted(
        grouped.values(),
        key=lambda item: (
            -issue_priority(item)[0],
            -issue_priority(item)[1],
            -issue_priority(item)[2],
            item["_path"],
            min(item["_lines"]) if item["_lines"] else 0,
        ),
    )
    return ranked[:limit]


def format_issue_location(issue):
    path = issue["_path"]
    line_numbers = sorted(issue.get("_lines", []))
    if not line_numbers:
        return path
    visible = ",".join(str(number) for number in line_numbers[:5])
    if len(line_numbers) > 5:
        visible += f",+{len(line_numbers) - 5}곳"
    return f"{path}:{visible}"


def wait_for_analysis(headers, report_path, timeout=300, interval=2):
    """Wait for the exact SonarQube Compute Engine task from this pipeline."""
    try:
        properties = dict(
            line.split("=", 1)
            for line in Path(report_path).read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
    except OSError as error:
        raise RuntimeError(f"Cannot read SonarQube task report: {report_path}") from error

    task_url = properties.get("ceTaskUrl")
    if not task_url:
        raise RuntimeError("SonarQube task report does not contain ceTaskUrl")

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = request_json(task_url, headers=headers).get("task", {})
        status = task.get("status", "UNKNOWN")
        if status == "SUCCESS":
            analysis_id = task.get("analysisId")
            if not analysis_id:
                raise RuntimeError("Completed SonarQube task has no analysisId")
            return analysis_id
        if status in {"FAILED", "CANCELED"}:
            raise RuntimeError(f"SonarQube analysis task ended with status: {status}")
        time.sleep(interval)

    raise RuntimeError(f"Timed out waiting for SonarQube analysis after {timeout} seconds")


def read_code_context(project_root, relative_path, line_number, radius=8):
    """Read a small, line-numbered source excerpt without leaving the project."""
    if not relative_path or not line_number:
        return "(주변 코드를 확인할 수 없음)"

    root = Path(project_root).resolve()
    source = (root / relative_path).resolve()
    try:
        source.relative_to(root)
    except ValueError:
        return "(프로젝트 외부 경로이므로 주변 코드를 읽지 않음)"

    if not source.is_file():
        return "(분석된 파일을 현재 작업 디렉터리에서 찾을 수 없음)"

    try:
        source_lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(주변 코드를 읽을 수 없음)"

    start = max(1, int(line_number) - radius)
    end = min(len(source_lines), int(line_number) + radius)
    return "\n".join(
        f"{number:>5}: {source_lines[number - 1]}"
        for number in range(start, end + 1)
    )


def normalize_review(content):
    """Keep the generated review short and safe for a Markdown list item."""
    content = (content or "").strip()
    if "```" in content:
        content = content.split("```", 1)[0].strip()
    for marker in ("예를 들어", "수정 예시", "다음 코드"):
        if marker in content:
            content = content.split(marker, 1)[0].strip()
    for label in ("이슈 원인:", "원인:", "영향:", "수정 방향:"):
        content = content.replace(label, "")
    content = " ".join(content.split())
    content = content.lstrip("-* ")
    return content[:1000].strip()


def ollama_review(base_url, model, timeout, issue, path, line_number, code_context):
    system_prompt = """당신은 GitLab Merge Request를 검토하는 한국어 코드 리뷰어입니다.
SonarQube 이슈와 주변 코드를 근거로 문제의 원인, 영향, 수정 방향을 자연스러운 한국어로 설명하세요.
출력은 500자 이내의 짧은 문단 하나여야 합니다.
모든 문장을 자연스러운 존댓말 서술문으로 완결하고 명사 나열로 끝내지 마세요.
코드, 코드 블록, 구체적인 변수명이나 대입문 예시, 제목, 목록, 인사말을 작성하지 마세요.
원문을 단순 번역하거나 같은 의미를 반복하거나 확인할 수 없는 내용을 추측하지 마세요."""
    issue_messages = issue.get("_messages") or [issue.get("message", "")]
    message_text = "\n".join(f"- {message}" for message in issue_messages)
    related_lines = ", ".join(
        str(number) for number in sorted(issue.get("_lines", []))
    )
    prompt = f"""다음 이슈를 검토하세요.

파일: {path}
라인: {line_number or '알 수 없음'}
동일 규칙 발생 라인: {related_lines or '알 수 없음'}
심각도: {issue.get('severity', 'UNKNOWN')}
유형: {issue.get('type', 'ISSUE')}
규칙: {issue.get('rule', '알 수 없음')}
SonarQube 메시지:
{message_text}

주변 코드:
{code_context}
"""
    payload = json.dumps(
        {
            "model": model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "options": {
                "temperature": 0.1,
                "num_ctx": 4096,
                "num_predict": 220,
            },
        }
    ).encode("utf-8")
    result = request_json(
        f"{base_url}/api/chat",
        headers={"Content-Type": "application/json; charset=utf-8"},
        data=payload,
        method="POST",
        timeout=timeout,
    )
    content = result.get("message", {}).get("content", "")
    review = normalize_review(content)
    if len(review) < 40:
        raise RuntimeError("Ollama returned an empty or incomplete review")
    return review


def main():
    sonar_url = require_env("SONAR_HOST_URL").rstrip("/")
    sonar_token = require_env("SONAR_TOKEN")
    ollama_url = os.environ.get("OLLAMA_HOST_URL", "").rstrip("/")
    ollama_model = os.environ.get(
        "OLLAMA_MODEL", "qwen2.5-coder:7b"
    )
    try:
        ollama_timeout = max(1, int(os.environ.get("OLLAMA_TIMEOUT", "120")))
    except ValueError:
        ollama_timeout = 120
    gitlab_token = require_env("GITLAB_REVIEW_TOKEN")
    gitlab_api = require_env("CI_API_V4_URL").rstrip("/")
    project_id = require_env("CI_PROJECT_ID")
    mr_iid = require_env("CI_MERGE_REQUEST_IID")
    commit_sha = os.environ.get("CI_COMMIT_SHORT_SHA", "unknown")

    encoded_token = base64.b64encode(f"{sonar_token}:".encode()).decode()
    sonar_headers = {"Authorization": f"Basic {encoded_token}"}
    gitlab_headers = {"PRIVATE-TOKEN": gitlab_token}

    wait_for_analysis(
        sonar_headers,
        ".scannerwork/report-task.txt",
    )

    diffs = fetch_merge_request_diffs(
        gitlab_api,
        project_id,
        mr_iid,
        gitlab_headers,
    )
    changed_files, changed_lines = build_changed_scope(diffs)
    all_issues = fetch_sonar_issues(sonar_url, sonar_headers)
    issues = select_mr_issues(all_issues, changed_files, changed_lines)
    print(
        f"Selected {len(issues)} review groups from {len(all_issues)} unresolved "
        f"SonarQube issues across {len(changed_files)} changed files."
    )

    lines = [
        MARKER,
        "## 🔍 SonarQube MR 자동 검토",
        "",
        "**분석 상태:** ✅ 완료",
        f"**검사 커밋:** `{commit_sha}`",
        "**분석 범위:** 이번 MR에서 추가·수정한 코드",
        f"**변경 파일:** {len(changed_files)}개",
        f"**AI 모델:** `{ollama_model}`" if ollama_url else "**AI 검토:** 비활성화",
        "",
        f"### 🤖 주요 정적 분석 이슈 (최대 {MAX_REVIEW_ISSUES}개)",
    ]

    if not issues:
        lines.append(
            "✅ 이번 MR에서 변경된 코드에는 MAJOR 이상의 주요 정적 분석 "
            "이슈가 발견되지 않았습니다."
        )
    else:
        for issue in issues:
            path = issue["_path"]
            issue_lines = sorted(issue.get("_lines", []))
            line_number = issue_lines[0] if issue_lines else None
            location = format_issue_location(issue)
            messages = issue.get("_messages") or [issue.get("message", "")]
            original_message = " / ".join(messages[:3])
            if len(messages) > 3:
                original_message += f" / 외 {len(messages) - 3}건"
            severity = issue.get("severity", "UNKNOWN")
            issue_type = issue.get("type", "ISSUE")

            review = ""
            if ollama_url:
                try:
                    code_context = read_code_context(
                        os.environ.get("CI_PROJECT_DIR", os.getcwd()),
                        path,
                        line_number,
                    )
                    review = ollama_review(
                        ollama_url,
                        ollama_model,
                        ollama_timeout,
                        issue,
                        path,
                        line_number,
                        code_context,
                    )
                except Exception as error:
                    print(
                        f"AI review fallback for {location}: {error}",
                        file=sys.stderr,
                    )

            if not review:
                review = (
                    f"{original_message} "
                    "(AI 설명을 생성하지 못해 SonarQube 원문을 표시합니다.)"
                )
            review = review.replace("|", "\\|")
            lines.append(
                f"- `{severity}` **{issue_type}** `{location}` — {review}"
            )

    lines.extend(
        [
            "",
            "※ GitLab MR 변경 라인과 SonarQube 이슈 위치를 대조한 결과입니다.",
            "※ 동일 파일의 동일 규칙은 하나로 묶고 MAJOR 이상만 표시합니다.",
            "※ AI가 생성한 자동 분석 결과이며 최종 판단은 리뷰어가 수행합니다.",
            "",
            "_같은 MR에서는 새 댓글을 추가하지 않고 기존 댓글을 갱신합니다._",
        ]
    )
    comment_body = "\n".join(lines)

    encoded_project_id = urllib.parse.quote(project_id, safe="")
    notes_url = (
        f"{gitlab_api}/projects/{encoded_project_id}"
        f"/merge_requests/{mr_iid}/notes"
    )
    notes = request_json(
        f"{notes_url}?per_page=100&order_by=updated_at&sort=desc",
        headers=gitlab_headers,
    )
    existing_note = next(
        (note for note in notes if MARKER in note.get("body", "")),
        None,
    )
    payload = urllib.parse.urlencode({"body": comment_body}).encode()

    if existing_note:
        request_json(
            f"{notes_url}/{existing_note['id']}",
            headers=gitlab_headers,
            data=payload,
            method="PUT",
        )
        print("Updated the existing SonarQube MR comment.")
    else:
        request_json(
            notes_url,
            headers=gitlab_headers,
            data=payload,
            method="POST",
        )
        print("Created a new SonarQube MR comment.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"Failed to publish SonarQube MR comment: {error}", file=sys.stderr)
        sys.exit(1)
