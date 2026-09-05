from pathlib import Path

ROOTS = [Path("app"), Path("tests"), Path("admin-ui/src"), Path("scripts"), Path("migrations")]
MARKERS = (
    "TODO",
    "FIXME",
    "HACK",
    "pytest.skip",
    "mark.skip(",
    "mark.skipif",
    "mark.xfail",
)
ALLOWED = {
    (
        Path("tests/test_postgres_repository.py"),
        "pytestmark = pytest.mark.skipif(",
    ): "PostgreSQL is executed separately by scripts/postgres_audit.sh",
    (
        Path("tests/test_meta_live_optin.py"),
        "pytest.mark.skipif(",
    ): "Live Meta GET checks require explicit META_LIVE_READONLY_VERIFY opt-in",
    (
        Path("tests/test_product_activity_live_optin.py"),
        "pytest.mark.skipif(",
    ): "Live first-party reads require explicit PRODUCT_ACTIVITY_LIVE_VERIFY opt-in",
}


def main() -> None:
    unexpected: list[tuple[Path, int, str]] = []
    approved: list[tuple[Path, str]] = []
    for root in ROOTS:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".sh", ".ts", ".tsx"}:
                continue
            if path.resolve() == Path(__file__).resolve():
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if not any(marker in line for marker in MARKERS):
                    continue
                allowance = next(
                    (
                        reason
                        for (allowed_path, text), reason in ALLOWED.items()
                        if path == allowed_path and text in line
                    ),
                    None,
                )
                if allowance is None:
                    unexpected.append((path, line_number, line.strip()))
                else:
                    approved.append((path, allowance))
    if unexpected:
        for path, line_number, line in unexpected:
            print(f"{path}:{line_number}: {line}")
        raise SystemExit(f"Found {len(unexpected)} unexpected TODO/skip marker(s)")
    for path, reason in approved:
        print(f"Approved opt-in skip in {path}: {reason}")
    print("TODO/skip scan passed")


if __name__ == "__main__":
    main()
