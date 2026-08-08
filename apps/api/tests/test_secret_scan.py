"""The secret scanner must actually detect credentials, not just pass.

A scanner that never fires is worse than none, because it looks like coverage.
"""

from __future__ import annotations

import importlib.util
import pathlib

import pytest


SCANNER = (
    pathlib.Path(__file__).resolve().parents[3] / "scripts" / "secret_scan.py"
)
_spec = importlib.util.spec_from_file_location("secret_scan", SCANNER)
assert _spec and _spec.loader
secret_scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(secret_scan)


# Synthetic, non-functional values shaped like the real thing. Each line carries the
# scanner's own line-scoped pragma, so this file does not trip the repository scan.
PLANTED = [
    ("aws.txt", "aws_key = AKIAIOSFODNN7EXAMPLE"),  # secret-scan: allow
    ("gh.txt", "token: ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"),  # secret-scan: allow
    ("key.pem", "-----BEGIN RSA PRIVATE KEY-----"),  # secret-scan: allow
    ("env.txt", "EXA_API_KEY=abcdefghijklmnop1234567890"),  # secret-scan: allow
    ("google.txt", "AIza" + "b" * 35),  # secret-scan: allow
    (
        "jwt.txt",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r",  # secret-scan: allow
    ),
]


@pytest.mark.parametrize("name,content", PLANTED, ids=[item[0] for item in PLANTED])
def test_planted_credentials_are_detected(
    tmp_path: pathlib.Path, name: str, content: str
) -> None:
    target = tmp_path / name
    target.write_text(content, encoding="utf-8")

    monkey_repo = secret_scan.REPO
    secret_scan.REPO = tmp_path
    try:
        findings = secret_scan.scan([target])
    finally:
        secret_scan.REPO = monkey_repo

    assert findings, f"scanner missed a planted credential in {name}"


def test_findings_never_include_the_credential_value(tmp_path: pathlib.Path) -> None:
    secret = "AKIAIOSFODNN7EXAMPLE"  # secret-scan: allow
    target = tmp_path / "leak.txt"
    target.write_text(f"aws_key = {secret}", encoding="utf-8")

    monkey_repo = secret_scan.REPO
    secret_scan.REPO = tmp_path
    try:
        findings = secret_scan.scan([target])
    finally:
        secret_scan.REPO = monkey_repo

    assert findings
    assert all(secret not in finding for finding in findings), (
        "a finding must not echo the credential into CI logs"
    )


def test_placeholders_and_env_lookups_are_not_flagged(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "config.py"
    target.write_text(
        "\n".join(
            [
                'EXA_API_KEY = os.getenv("EXA_API_KEY")',
                "JWKS_URL=https://<project>.supabase.co/auth/v1/.well-known/jwks.json",
                "GITHUB_TOKEN=",
                "api_key = process.env.API_KEY",
            ]
        ),
        encoding="utf-8",
    )

    monkey_repo = secret_scan.REPO
    secret_scan.REPO = tmp_path
    try:
        findings = secret_scan.scan([target])
    finally:
        secret_scan.REPO = monkey_repo

    assert findings == []


def test_line_scoped_pragma_suppresses_a_finding(tmp_path: pathlib.Path) -> None:
    # Split so this source line does not itself look like a key to the scanner.
    unannotated = "AKIA" + "IOSFODNN7EXAMPLB"
    target = tmp_path / "fixture.py"
    target.write_text(
        f"key = 'AKIAIOSFODNN7EXAMPLE'  # secret-scan: allow\nother = '{unannotated}'\n",
        encoding="utf-8",
    )

    monkey_repo = secret_scan.REPO
    secret_scan.REPO = tmp_path
    try:
        findings = secret_scan.scan([target])
    finally:
        secret_scan.REPO = monkey_repo

    assert len(findings) == 1, "only the un-annotated line should be reported"
    assert findings[0].endswith("AWS access key id")
    assert ":2:" in findings[0]


def test_repository_itself_is_clean() -> None:
    findings = secret_scan.scan(secret_scan.tracked_files(staged=False))
    assert findings == [], f"tracked files contain credentials: {findings}"
