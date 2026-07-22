import argparse
import json
import re
from html import escape
from pathlib import Path
from typing import cast

from pydantic import JsonValue

JsonObject = dict[str, JsonValue]

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bEAA[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{12,}"),
)


def _object(value: JsonValue, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _objects(value: JsonValue, label: str) -> list[JsonObject]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{label} must be an array of objects")
    return cast(list[JsonObject], value)


def _text(value: JsonValue | None, fallback: str = "") -> str:
    return value if isinstance(value, str) else fallback


def _render_markdown(body: str) -> str:
    rendered: list[str] = []
    paragraph: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            rendered.append(f"<p>{escape(' '.join(paragraph))}</p>")
            paragraph.clear()

    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            flush_paragraph()
        elif line.startswith("## "):
            flush_paragraph()
            rendered.append(f"<h2>{escape(line[3:])}</h2>")
        elif line.startswith("# "):
            flush_paragraph()
            rendered.append(f"<h1>{escape(line[2:])}</h1>")
        else:
            paragraph.append(line)
    flush_paragraph()
    return "\n".join(rendered)


def _cell(value: JsonValue) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _render_dataset(name: str, rows: list[JsonObject]) -> str:
    if not rows:
        return (
            f'<section class="dataset"><h3>{escape(name.replace("_", " ").title())}</h3>'
            '<p class="empty">No rows were reported.</p></section>'
        )
    columns = sorted({key for row in rows for key in row})
    head = "".join(f'<th scope="col">{escape(column.replace("_", " "))}</th>' for column in columns)
    body = "".join(
        "<tr>"
        + "".join(f"<td>{escape(_cell(row.get(column)))}</td>" for column in columns)
        + "</tr>"
        for row in rows
    )
    return (
        f'<section class="dataset"><h3>{escape(name.replace("_", " ").title())}</h3>'
        f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody>'
        "</table></div></section>"
    )


def _render_chart(chart: JsonObject, datasets: dict[str, list[JsonObject]]) -> str:
    title = _text(chart.get("title"), "Chart")
    subtitle = _text(chart.get("subtitle"))
    dataset_name = _text(chart.get("dataset"))
    rows = datasets.get(dataset_name, [])
    encodings = _object(chart.get("encodings", {}), "chart encodings")
    x_encoding = _object(encodings.get("x", {}), "chart x encoding")
    y_encoding = _object(encodings.get("y", {}), "chart y encoding")
    x_field = _text(x_encoding.get("field"))
    y_field = _text(y_encoding.get("field"))
    bars: list[str] = []
    for row in rows:
        raw_value = row.get(y_field)
        numeric = float(raw_value) if isinstance(raw_value, int | float) else 0.0
        percent = max(0.0, min(numeric * 100, 100.0))
        label = _cell(row.get(x_field))
        bars.append(
            '<div class="bar-row">'
            f"<span>{escape(label)}</span>"
            f'<div class="bar-track"><i style="width:{percent:.2f}%"></i></div>'
            f"<strong>{percent:.1f}%</strong>"
            "</div>"
        )
    content = "".join(bars) or '<p class="empty">No chart rows were reported.</p>'
    return (
        '<section class="chart">'
        f"<h2>{escape(title)}</h2><p>{escape(subtitle)}</p>{content}"
        "</section>"
    )


def _render_report(artifact: JsonObject) -> str:
    if artifact.get("surface") != "report":
        raise ValueError("artifact surface must be report")
    manifest = _object(artifact.get("manifest", {}), "manifest")
    snapshot = _object(artifact.get("snapshot", {}), "snapshot")
    if manifest.get("version") != 1 or snapshot.get("version") != 1:
        raise ValueError("unsupported artifact version")
    if manifest.get("surface") != "report":
        raise ValueError("manifest surface must be report")

    title = _text(manifest.get("title"), "Portable report")
    description = _text(manifest.get("description"))
    generated_at = _text(manifest.get("generatedAt"), "unavailable")
    status = _text(snapshot.get("status"), "unknown")
    raw_datasets = _object(snapshot.get("datasets", {}), "snapshot datasets")
    datasets = {
        name: _objects(rows, f"dataset {name}")
        for name, rows in raw_datasets.items()
        if isinstance(name, str)
    }
    charts = {
        _text(chart.get("id")): chart
        for chart in _objects(manifest.get("charts", []), "manifest charts")
    }
    blocks: list[str] = []
    for block in _objects(manifest.get("blocks", []), "manifest blocks"):
        block_type = _text(block.get("type"))
        if block_type == "markdown":
            blocks.append(
                f'<section class="copy">{_render_markdown(_text(block.get("body")))}</section>'
            )
        elif block_type == "chart":
            chart = charts.get(_text(block.get("chartId")))
            if chart is not None:
                blocks.append(_render_chart(chart, datasets))

    dataset_sections = "".join(
        _render_dataset(name, rows) for name, rows in sorted(datasets.items())
    )
    sources = _objects(manifest.get("sources", []), "manifest sources")
    source_sections = "".join(
        '<article class="source-card">'
        f"<h3>{escape(_text(source.get('label'), 'Evidence source'))}</h3>"
        f"<p>{escape(_text(source.get('path'), 'unavailable'))}</p>"
        f"<pre>{escape(json.dumps(source.get('query'), indent=2, sort_keys=True))}</pre>"
        "</article>"
        for source in sources
    )

    template = (
        Path(__file__)
        .with_name("portable_report_template.html")
        .read_text(
            encoding="utf-8",
        )
    )
    replacements = {
        "@@TITLE@@": escape(title),
        "@@DESCRIPTION@@": escape(description),
        "@@STATUS@@": escape(status),
        "@@GENERATED_AT@@": escape(generated_at),
        "@@BLOCKS@@": "".join(blocks),
        "@@DATASETS@@": dataset_sections,
        "@@SOURCES@@": source_sections,
    }
    for marker, value in replacements.items():
        template = template.replace(marker, value)
    return template


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a self-contained sanitized HTML report")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    raw = arguments.input.read_text(encoding="utf-8")
    if any(pattern.search(raw) is not None for pattern in SECRET_PATTERNS):
        raise SystemExit("Portable artifact contains a potential credential")
    parsed = cast(JsonValue, json.loads(raw))
    artifact = _object(parsed, "artifact")
    report = _render_report(artifact)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_suffix(f"{arguments.output.suffix}.tmp")
    temporary.write_text(report, encoding="utf-8")
    temporary.replace(arguments.output)
    print(f"Portable report generated: {arguments.output}")


if __name__ == "__main__":
    main()
