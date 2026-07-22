import re
from pathlib import Path

PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "Meta-style token": re.compile(r"\bEAA[A-Za-z0-9]{20,}\b"),
    "bearer credential": re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{12,}"),
    "server-only setting": re.compile(
        r"\b(?:META_ACCESS_TOKEN|OPENAI_API_KEY|OPERATION_ADMIN_API_KEY|POSTGRES_PASSWORD)\b",
    ),
}


def main() -> None:
    project_root = Path(__file__).parents[1]
    static_root = project_root / "admin-ui" / ".next" / "static"
    if not static_root.is_dir():
        raise SystemExit("Next.js client bundle is missing; run the production build first")

    findings: list[tuple[Path, str]] = []
    scanned = 0
    for path in static_root.rglob("*"):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scanned += 1
        for name, pattern in PATTERNS.items():
            if pattern.search(content) is not None:
                findings.append((path.relative_to(project_root), name))

    if findings:
        for path, name in findings:
            print(f"{path}: potential {name}")
        raise SystemExit(f"Admin bundle scan found {len(findings)} potential leak(s)")
    print(f"Admin client bundle scan passed for {scanned} text assets")


if __name__ == "__main__":
    main()
