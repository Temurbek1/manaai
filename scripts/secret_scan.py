import re
import subprocess
from pathlib import Path

PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "Meta-style token": re.compile(r"\bEAA[A-Za-z0-9]{20,}\b"),
    "bearer token": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{12,}"),
    "named secret": re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|bot[_-]?token|client[_-]?secret|"
        r"hmac[_-]?secret|password)[\"']?"
        r"\s*[:=]\s*[\"']([^\"'\r\n]{12,})[\"']",
    ),
}
SAFE_TEST_MARKERS = (
    "test-",
    "fake-",
    "known-secret",
    "REAL_LOOKING",
    "[REDACTED]",
    "example",
    "placeholder",
)
BINARY_SUFFIXES = {
    ".ico",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".png",
    ".woff",
    ".woff2",
    ".zip",
}


def candidate_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True,
        capture_output=True,
    )
    return [Path(item) for item in result.stdout.decode().split("\0") if item]


def main() -> None:
    findings: list[tuple[Path, int, str]] = []
    for path in candidate_files():
        if path.suffix.casefold() in BINARY_SUFFIXES or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            for name, pattern in PATTERNS.items():
                if pattern.search(line) is None:
                    continue
                if name != "private key" and any(marker in line for marker in SAFE_TEST_MARKERS):
                    continue
                findings.append((path, line_number, name))

    if findings:
        for path, line_number, name in findings:
            print(f"{path}:{line_number}: potential {name}")
        raise SystemExit(f"Secret scan found {len(findings)} potential leak(s)")
    print(f"Secret scan passed for {len(candidate_files())} tracked/unignored files")


if __name__ == "__main__":
    main()
