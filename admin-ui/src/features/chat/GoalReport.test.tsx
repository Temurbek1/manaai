import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "@jest/globals";
import { GoalReport } from "./GoalReport";

describe("GoalReport", () => {
  it("renders readable headings, findings and citations without raw markdown", () => {
    render(
      <GoalReport
        text={
          "## Выводы\n\n**D7:** 35%. Источник `report-1`.\n\n- Родители отдельно\n- Оплаты неизвестны"
        }
      />,
    );
    expect(screen.getByRole("heading", { name: "Выводы" })).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText("D7:").tagName).toBe("STRONG");
    expect(screen.getByText("report-1").tagName).toBe("CODE");
  });

  it("never turns model text into HTML, links or provider actions", () => {
    const { container } = render(
      <GoalReport
        text={
          "<script>alert(1)</script>\n\n[click](javascript:alert(1))\n\n<img src=x onerror=alert(1)>"
        }
      />,
    );
    expect(container.querySelector("script, img, a, button")).toBeNull();
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
  });
});
