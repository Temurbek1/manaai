import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "@jest/globals";
import { GoalReport } from "./GoalReport";
import syntheticReport from "@/test/fixtures/native-parent-report.json";

describe("GoalReport", () => {
  it("renders cohort calculations as a semantic table without executing cell markup", () => {
    const { container } = render(
      <GoalReport
        text={
          "| Метрика | Результат |\n|---|---|\n| D1 родителей | **60%** |\n| Источник | `<img src=x>` |"
        }
      />,
    );
    expect(
      screen.getByRole("table", { name: "Данные анализа" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("columnheader")).toHaveLength(2);
    expect(screen.getByRole("cell", { name: "60%" })).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Таблица анализа" }),
    ).toHaveAttribute("tabindex", "0");
    expect(container.querySelector("img, script, a")).toBeNull();
  });

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

  it("recognizes adjacent headings, paragraphs, lists and tables without blank lines", () => {
    render(
      <GoalReport
        text={
          "## Источник и границы\nТолько синтетический срез.\n" +
          "## Воронка\nКонверсия — это расчёт.\n" +
          "| Этап | Конверсия |\n|---|---|\n| Регистрация | **85%** |\n" +
          "## Ограничения\n- Родители отдельно\n- Оплаты не равны тарифам\n" +
          "## План\n1. Проверить источник\n2. Сохранить исходную цель\n" +
          "Новые действия не запускались."
        }
      />,
    );
    expect(screen.getAllByRole("heading")).toHaveLength(4);
    expect(
      screen.getByRole("heading", { name: "Источник и границы" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "85%" })).toBeInTheDocument();
    expect(screen.getAllByRole("list")).toHaveLength(2);
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
    expect(
      screen.getByText("Новые действия не запускались."),
    ).toBeInTheDocument();
  });

  it("renders the complete real-model synthetic artifact with its tables and final condition", () => {
    const { container } = render(<GoalReport text={syntheticReport.text} />);
    expect(screen.getAllByRole("heading")).toHaveLength(8);
    expect(screen.getAllByRole("table")).toHaveLength(2);
    expect(screen.getAllByRole("columnheader")).toHaveLength(8);
    expect(screen.getAllByRole("cell")).toHaveLength(32);
    expect(
      screen.getByRole("cell", { name: "680/800 = 85%" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "30%" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Источник и границы" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Вывод" })).toBeInTheDocument();
    expect(
      screen.getByText(
        /Сначала качество данных, затем удержание; никаких действий без согласования/,
      ),
    ).toBeInTheDocument();
    expect(container.textContent).toContain("25.09.2026, 00:00 UTC");
    expect(container.textContent).toContain("не измерение реальных клиентов");
    expect(container.textContent).not.toContain("##");
    expect(container.textContent).not.toContain("|---");
    expect(container.querySelector("script, img, a, button")).toBeNull();
  });

  it("preserves malformed table content instead of hiding rows", () => {
    render(
      <GoalReport
        text={
          "## Проверка\n| Метрика | Доля |\n|---|---|\n| Полная строка | 60% |\n| Не теряй хвост |"
        }
      />,
    );
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByText(/Не теряй хвост/)).toHaveTextContent("60%");
    expect(
      screen.getByRole("heading", { name: "Проверка" }),
    ).toBeInTheDocument();
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
