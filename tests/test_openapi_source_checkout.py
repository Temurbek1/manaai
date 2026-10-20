import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def test_standalone_export_uses_its_checkout_not_an_editable_install(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    target = scripts / "export_openapi.py"
    shutil.copyfile(Path(__file__).parents[1] / "scripts" / target.name, target)
    (checkout / "admin-ui").mkdir()
    local_app = checkout / "app"
    local_app.mkdir()
    (local_app / "__init__.py").write_text("")
    (local_app / "main.py").write_text(
        "class App:\n"
        "    def openapi(self):\n"
        "        return {'checkout': 'correct'}\n"
        "def create_app():\n"
        "    return App()\n"
    )
    unrelated = tmp_path / "unrelated"
    (unrelated / "app").mkdir(parents=True)
    (unrelated / "app" / "__init__.py").write_text(
        "raise RuntimeError('Must not import an unrelated editable checkout')\n"
    )
    result = subprocess.run(
        [sys.executable, str(target)],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(unrelated), "OPENAI_API_KEY": "unit-export"},
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads((checkout / "admin-ui" / "openapi.json").read_text()) == {
        "checkout": "correct"
    }
