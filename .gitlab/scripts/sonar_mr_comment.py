#!/usr/bin/env python3
"""Post the latest local SonarQube analysis summary to a GitLab MR."""

import base64
import json
import os
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


def request_json(url, headers=None, data=None, method="GET"):
    request = urllib.request.Request(
        url,
        headers=headers or {},
        data=data,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
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


def main():
    sonar_url = require_env("SONAR_HOST_URL").rstrip("/")
    sonar_token = require_env("SONAR_TOKEN")
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
        "### 프로젝트 전체 주요 미해결 이슈 (최대 10개)",
    ]

    issues = issue_result.get("issues", [])
    if not issues:
        lines.append("- 발견된 미해결 이슈가 없습니다.")
    else:
        for issue in issues:
            path = issue.get("component", "").split(":", 1)[-1]
            line_number = issue.get("line")
            location = f"{path}:{line_number}" if line_number else path
            message = issue.get("message", "").replace("|", "\\|")
            severity = issue.get("severity", "UNKNOWN")
            issue_type = issue.get("type", "ISSUE")
            lines.append(
                f"- `{severity}` **{issue_type}** `{location}` — {message}"
            )

    lines.extend(
        [
            "",
            "※ SonarQube Community Build의 프로젝트 전체 분석 결과입니다.",
            "※ 자동 분석 결과이며 최종 판단은 리뷰어가 수행합니다.",
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
