import type { ReactNode } from "react";

const HEADING = /^ {0,3}#{1,3}\s/;
const TABLE_SEPARATOR = /^\s*\|?\s*:?-+:?\s*\|/;

function listKind(line: string): "unordered" | "ordered" | null {
  if (/^[-•]\s/.test(line)) return "unordered";
  if (/^\d+\.\s/.test(line)) return "ordered";
  return null;
}

function reportBlocks(text: string): string[][] {
  const lines = text.split(/\r?\n/);
  const blocks: string[][] = [];
  let index = 0;
  function tableAt(position: number): boolean {
    return (
      Boolean(lines[position]?.includes("|")) &&
      TABLE_SEPARATOR.test(lines[position + 1] ?? "")
    );
  }
  while (index < lines.length) {
    const line = lines[index]!;
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (HEADING.test(line)) {
      blocks.push([line]);
      index += 1;
      continue;
    }
    if (tableAt(index)) {
      const table = [line, lines[index + 1]!];
      index += 2;
      while (index < lines.length && lines[index]!.includes("|")) {
        table.push(lines[index]!);
        index += 1;
      }
      blocks.push(table);
      continue;
    }
    const kind = listKind(line);
    const paragraph = [line];
    index += 1;
    while (
      index < lines.length &&
      lines[index]!.trim() &&
      !HEADING.test(lines[index]!) &&
      !tableAt(index) &&
      listKind(lines[index]!) === kind
    ) {
      paragraph.push(lines[index]!);
      index += 1;
    }
    blocks.push(paragraph);
  }
  return blocks;
}

function inline(text: string): ReactNode[] {
  return text
    .split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g)
    .map((part, index) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={index}>{part.slice(2, -2)}</strong>
      ) : part.startsWith("`") && part.endsWith("`") ? (
        <code key={index}>{part.slice(1, -1)}</code>
      ) : (
        part
      ),
    );
}

// Deliberately small text renderer: React escapes HTML; no HTML, arbitrary URLs or tool actions.
export function GoalReport({ text }: { text: string }): React.JSX.Element {
  return (
    <>
      {reportBlocks(text).map((lines, index) => {
        const block = lines.join("\n");
        if (lines.length >= 3 && /^\s*\|?\s*:?-+:?\s*\|/.test(lines[1]!)) {
          const cells = lines.map((line) =>
            line
              .trim()
              .replace(/^\||\|$/g, "")
              .split("|")
              .map((cell) => cell.trim()),
          );
          const headers = cells[0]!;
          if (
            headers.length <= 8 &&
            cells.every((row) => row.length === headers.length)
          )
            return (
              <div
                key={index}
                className="goal-report-table"
                role="region"
                aria-label="Таблица анализа"
                tabIndex={0}
              >
                <table aria-label="Данные анализа">
                  <thead>
                    <tr>
                      {headers.map((cell, column) => (
                        <th key={column} scope="col">
                          {inline(cell)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {cells.slice(2).map((row, item) => (
                      <tr key={item}>
                        {row.map((cell, column) => (
                          <td key={column}>{inline(cell)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
        }
        if (lines.length === 1 && HEADING.test(block))
          return (
            <h3 key={index}>{inline(block.replace(/^ {0,3}#{1,3}\s+/, ""))}</h3>
          );
        if (lines.every((line) => /^[-•]\s/.test(line)))
          return (
            <ul key={index}>
              {lines.map((line, item) => (
                <li key={item}>{inline(line.replace(/^[-•]\s+/, ""))}</li>
              ))}
            </ul>
          );
        if (lines.every((line) => /^\d+\.\s/.test(line)))
          return (
            <ol key={index}>
              {lines.map((line, item) => (
                <li key={item}>{inline(line.replace(/^\d+\.\s+/, ""))}</li>
              ))}
            </ol>
          );
        return <p key={index}>{inline(block)}</p>;
      })}
    </>
  );
}
