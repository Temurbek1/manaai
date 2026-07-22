import json
import os
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).parents[1]
    os.chdir(project_root)
    os.environ.setdefault("OPENAI_API_KEY", "openapi-schema-placeholder")
    from app.main import create_app

    target = project_root / "admin-ui" / "openapi.json"
    target.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
