import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pytest import MonkeyPatch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/postgres_audit.sh"
CONTAINER_ID = "ab" * 32


def stub_commands(directory: Path, monkeypatch: MonkeyPatch) -> Path:
    tools = directory / "stub-bin"
    tools.mkdir()
    trace = directory / "trace.jsonl"
    monkeypatch.setenv("AUDIT_STUB_TRACE", str(trace))
    monkeypatch.setenv("PATH", f"{tools}:{os.environ['PATH']}")
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("AUDIT_STUB_ENDPOINT", "unix:///var/run/docker.sock")
    for name in (
        "AUDIT_STUB_RUN_FAILURE",
        "AUDIT_STUB_CONTAINER_ID",
        "AUDIT_STUB_MIGRATION_FAILURE",
    ):
        monkeypatch.delenv(name, raising=False)
    program = f"""#!{sys.executable}
import json
import os
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['AUDIT_STUB_TRACE'], 'a', encoding='utf-8') as stream:
    stream.write(json.dumps([name, args]) + '\\n')
if name == 'docker':
    if args[:2] != ['context', 'inspect'] and (
        os.environ.get('DOCKER_CONTEXT')
        or os.environ.get('DOCKER_HOST') != os.environ['AUDIT_STUB_ENDPOINT']
    ):
        sys.exit(7)
    if args[:2] == ['context', 'inspect']:
        print(os.environ['AUDIT_STUB_ENDPOINT'])
    elif args[:1] == ['run']:
        if os.environ.get('AUDIT_STUB_RUN_FAILURE') == '1':
            sys.exit(1)
        print(os.environ.get('AUDIT_STUB_CONTAINER_ID', '{CONTAINER_ID}'))
    elif args[:1] == ['port']:
        print('127.0.0.1:54321')
elif os.environ.get('AUDIT_STUB_MIGRATION_FAILURE') == '1':
    sys.exit(1)
"""
    binaries = [tools / "docker", directory / ".venv/bin/alembic", directory / ".venv/bin/pytest"]
    for binary in binaries:
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_text(program, encoding="utf-8")
        binary.chmod(0o700)
    return trace


def run_script(directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=directory,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def trace_commands(trace: Path) -> list[tuple[str, list[str]]]:
    return (
        [
            (record[0], record[1])
            for line in trace.read_text(encoding="utf-8").splitlines()
            for record in [json.loads(line)]
        ]
        if trace.exists()
        else []
    )


@pytest.mark.parametrize(
    "endpoint",
    ["ssh://production.example", "tcp://production.example:2376", "tcp://127.0.0.1:2375"],
)
@pytest.mark.parametrize("via_environment", [False, True])
def test_remote_endpoint_refused_before_container_or_migration_operations(
    tmp_path: Path, monkeypatch: MonkeyPatch, endpoint: str, via_environment: bool
) -> None:
    trace = stub_commands(tmp_path, monkeypatch)
    if via_environment:
        monkeypatch.setenv("DOCKER_HOST", endpoint)
    else:
        monkeypatch.setenv("AUDIT_STUB_ENDPOINT", endpoint)
    result = run_script(tmp_path)
    assert result.returncode == 2
    assert "local Unix Docker socket" in result.stderr
    commands = trace_commands(trace)
    assert len(commands) == (0 if via_environment else 1)
    assert all(
        command[0] == "docker" and command[1][:2] == ["context", "inspect"] for command in commands
    )


@pytest.mark.parametrize("failed_create", [False, True])
def test_local_audit_only_uses_and_cleans_its_successfully_created_container_id(
    tmp_path: Path, monkeypatch: MonkeyPatch, failed_create: bool
) -> None:
    trace = stub_commands(tmp_path, monkeypatch)
    if failed_create:
        monkeypatch.setenv("AUDIT_STUB_RUN_FAILURE", "1")
    result = run_script(tmp_path)
    assert result.returncode == (1 if failed_create else 0)
    commands = trace_commands(trace)
    docker_args = [command[1] for command in commands if command[0] == "docker"]
    operations = [args for args in docker_args if args[0] in {"exec", "port", "rm"}]
    if failed_create:
        assert operations == []
        assert all(command[0] == "docker" for command in commands)
    else:
        assert ["rm", "-f", CONTAINER_ID] in operations
        assert all(args[1 if args[0] != "rm" else 2] == CONTAINER_ID for args in operations)
        assert ("alembic", ["downgrade", "base"]) in commands
        assert ("pytest", ["-q", "tests/test_postgres_repository.py"]) in commands


def test_migration_failure_still_cleans_owned_id(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    trace = stub_commands(tmp_path, monkeypatch)
    monkeypatch.setenv("AUDIT_STUB_MIGRATION_FAILURE", "1")
    assert run_script(tmp_path).returncode == 1
    assert ("docker", ["rm", "-f", CONTAINER_ID]) in trace_commands(trace)


def test_invalid_create_output_does_not_become_cleanup_target(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    trace = stub_commands(tmp_path, monkeypatch)
    monkeypatch.setenv("AUDIT_STUB_CONTAINER_ID", "existing-important-service")
    assert run_script(tmp_path).returncode == 2
    assert not any(
        command[0] != "docker" or command[1][0] in {"exec", "port", "rm"}
        for command in trace_commands(trace)
    )


@pytest.mark.parametrize(
    "context_endpoint,expected", [("unix:///var/run/docker.sock", 0), ("ssh://remote.example", 2)]
)
def test_explicit_context_overrides_host_for_endpoint_validation(
    tmp_path: Path, monkeypatch: MonkeyPatch, context_endpoint: str, expected: int
) -> None:
    trace = stub_commands(tmp_path, monkeypatch)
    monkeypatch.setenv("DOCKER_CONTEXT", "explicit-audit-context")
    monkeypatch.setenv("DOCKER_HOST", "tcp://different-daemon.example:2376")
    monkeypatch.setenv("AUDIT_STUB_ENDPOINT", context_endpoint)
    result = run_script(tmp_path)
    assert result.returncode == expected
    assert trace_commands(trace)[0] == (
        "docker",
        ["context", "inspect", "explicit-audit-context", "--format", "{{.Endpoints.docker.Host}}"],
    )
