export const CHAT_AGENTS = [
  {
    id: "operations-orchestrator",
    name: "Оркестратор",
    short: "O",
    description: "Приоритеты, цели и координация команды",
    planned: true,
    prompts: [
      "Помоги расставить приоритеты",
      "Как сформулировать цель для команды?",
      "Составим план работы на неделю",
    ],
  },
  {
    id: "growth-agent",
    name: "Рост и конверсия",
    short: "G",
    description: "Реклама, воронки и точки роста",
    planned: false,
    prompts: [
      "Что известно о конверсии?",
      "Разбери последний отчёт",
      "Где искать возможности роста?",
    ],
  },
  {
    id: "retention-agent",
    name: "Удержание и лояльность",
    short: "R",
    description: "Вовлечённость, возвращаемость и лояльность",
    planned: false,
    prompts: [
      "Что мы знаем об удержании?",
      "Каким данным можно доверять?",
      "Помоги составить план возврата пользователей",
    ],
  },
  {
    id: "technical-agent",
    name: "Техническая надёжность",
    short: "T",
    description: "Надёжность, ошибки и технические риски",
    planned: true,
    prompts: [
      "Помоги описать техническую проблему",
      "Составим план проверки",
      "Что нужно для разбора инцидента?",
    ],
  },
] as const;

export type ChatAgentId = (typeof CHAT_AGENTS)[number]["id"];
export const CHAT_BASE = "/api/v1/admin/operation/chat";
