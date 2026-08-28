#!/usr/bin/env python3
"""Post the latest local SonarQube analysis summary to a GitLab MR."""

import base64
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request


MARKER = "<!-- sonar-local-review -->"
PROJECT_KEY = "S15P21A106"


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
    prompt = f"""다음 이슈를 검토하세요.

파일: {path}
라인: {line_number or '알 수 없음'}
심각도: {issue.get('severity', 'UNKNOWN')}
유형: {issue.get('type', 'ISSUE')}
SonarQube 메시지: {issue.get('message', '')}

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

    metric_keys = [
        "bugs",
        "vulnerabilities",
        "code_smells",
        "security_hotspots",
        "coverage",
        "duplicated_lines_density",
        "ncloc",
    ]
    measure_result = sonar_get(
        sonar_url,
        sonar_headers,
        "/api/measures/component",
        {"component": PROJECT_KEY, "metricKeys": ",".join(metric_keys)},
    )
    metrics = {
        item["metric"]: item.get("value", "-")
        for item in measure_result.get("component", {}).get("measures", [])
    }

    gate_result = sonar_get(
        sonar_url,
        sonar_headers,
        "/api/qualitygates/project_status",
        {"projectKey": PROJECT_KEY},
    )
    gate_status = gate_result.get("projectStatus", {}).get("status", "UNKNOWN")
    gate_icon = "✅" if gate_status == "OK" else "❌"

    issue_result = sonar_get(
        sonar_url,
        sonar_headers,
        "/api/issues/search",
        {
            "componentKeys": PROJECT_KEY,
            "resolved": "false",
            "ps": 10,
        },
    )

    lines = [
        MARKER,
        "## 🔍 SonarQube MR 자동 검토",
        "",
        f"**결과:** {gate_icon} `{gate_status}`",
        f"**검사 커밋:** `{commit_sha}`",
        "**분석 범위:** 프로젝트 전체",
        f"**AI 모델:** `{ollama_model}`" if ollama_url else "**AI 검토:** 비활성화",
        "",
        "### 프로젝트 전체 현황",
        "",
        "| 항목 | 결과 |",
        "|---|---:|",
        f"| Bugs | {metrics.get('bugs', '-')} |",
        f"| Vulnerabilities | {metrics.get('vulnerabilities', '-')} |",
        f"| Code Smells | {metrics.get('code_smells', '-')} |",
        f"| Security Hotspots | {metrics.get('security_hotspots', '-')} |",
        f"| Coverage | {metrics.get('coverage', '-')}% |",
        f"| Duplicated Lines | {metrics.get('duplicated_lines_density', '-')}% |",
        f"| Lines of Code | {metrics.get('ncloc', '-')} |",
        "",
        "### 🤖 AI 코드 리뷰 (최대 10개)",
    ]

    issues = issue_result.get("issues", [])
    if not issues:
        lines.append("- 발견된 미해결 이슈가 없습니다.")
    else:
        for issue in issues:
            path = issue.get("component", "").split(":", 1)[-1]
            line_number = issue.get("line")
            location = f"{path}:{line_number}" if line_number else path
            original_message = issue.get("message", "")
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
            "※ SonarQube Community Build의 프로젝트 전체 분석 결과입니다.",
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
    gitlab_headers = {"PRIVATE-TOKEN": gitlab_token}
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
