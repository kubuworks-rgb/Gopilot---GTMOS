"""Fail the build if a credential looks like it reached a tracked file.

Runs with no credentials of its own and no network access. Reports only the file
and line number of a match — never the matched value, so a leak is not compounded
by printing it into CI logs.

Usage:  python scripts/secret_scan.py [--staged]
"""

from __future__ import annotations

import argparse
import pathlib
import re
import subprocess
import sys


REPO = pathlib.Path(__file__).resolve().parents[1]

# Binary and vendored content never carries hand-written credentials.
SKIP_DIRECTORIES = {
    ".git",
    "node_modules",
    ".next",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    "coverage",
}
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".woff", ".woff2", ".ttf", ".eot", ".pdf", ".zip", ".gz",
    ".lock",
}
SKIP_FILES = {"package-lock.json"}

RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("OpenAI key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Signed JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    (
        "Populated credential assignment",
        re.compile(
            r"(?i)\b(?:EXA_API_KEY|TAVILY_API_KEY|OPENAI_API_KEY|GITHUB_TOKEN"
            r"|RESEARCH_GATEWAY_TOKEN|FIRMOGRAPHIC_API_KEY|SUPABASE_ANON_KEY"
            r"|SUPABASE_SERVICE_ROLE_KEY|API_KEY|SECRET_KEY|ACCESS_TOKEN)\s*"
            r"[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"
        ),
    ),
)

# Lines a rule may legitimately match: documentation, placeholders, and the
# scanner's own patterns.
#
# `secret-scan: allow` opts a single line out. It is deliberately line-scoped and
# deliberately greppable, so every exemption stays visible in review — a file-level
# opt-out would let a real credential hide behind one annotation.
ALLOWED = re.compile(
    r"(?i)(?:"
    r"<your|<project|example\.com|placeholder|redacted|changeme|xxxx"
    r"|os\.getenv|process\.env|getenv\(|secret-scan:\s*allow"
    r")"
)


def tracked_files(staged: bool) -> list[pathlib.Path]:
    command = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]
    if not staged:
        command = ["git", "ls-files"]
    output = subprocess.run(
        command, cwd=REPO, capture_output=True, text=True, check=True
    ).stdout
    paths = []
    for line in output.splitlines():
        path = REPO / line.strip()
        if not line.strip() or not path.is_file():
            continue
        if set(path.relative_to(REPO).parts) & SKIP_DIRECTORIES:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES or path.name in SKIP_FILES:
            continue
        paths.append(path)
    return paths


def scan(paths: list[pathlib.Path]) -> list[str]:
    findings: list[str] = []
    scanner = pathlib.Path(__file__).resolve()
    for path in paths:
        if path.resolve() == scanner:
            continue  # the rules themselves are not secrets
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if ALLOWED.search(line):
                continue
            for label, pattern in RULES:
                if pattern.search(line):
                    relative = path.relative_to(REPO).as_posix()
                    findings.append(f"{relative}:{number}: {label}")
                    break
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staged",
        action="store_true",
        help="scan staged changes instead of all tracked files",
    )
    arguments = parser.parse_args()

    paths = tracked_files(arguments.staged)
    findings = scan(paths)

    if findings:
        print(f"Potential credentials in {len(findings)} location(s):")
        for finding in findings:
            print(f"  {finding}")
        print("\nValues are intentionally not printed. Inspect the lines above.")
        return 1

    print(f"Secret scan clean across {len(paths)} tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
