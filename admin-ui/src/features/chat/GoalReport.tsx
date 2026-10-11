import type { ReactNode } from "react";

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
      {text.split(/\n\s*\n/).map((block, index) => {
        const lines = block.split("\n");
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
        if (lines.length === 1 && /^#{1,3}\s/.test(block))
          return <h3 key={index}>{inline(block.replace(/^#{1,3}\s+/, ""))}</h3>;
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
