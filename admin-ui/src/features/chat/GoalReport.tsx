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
