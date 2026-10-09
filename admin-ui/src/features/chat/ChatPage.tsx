"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { apiGet, apiPost } from "@/api/client";
import type { components } from "@/api/schema";
import { QueryState } from "@/components/QueryState";
import { hasRole, useSession } from "@/auth/SessionContext";
import {
  GOALS_BASE,
  GoalWorkspace,
  type Goal,
  type GoalsAvailability,
} from "./GoalWorkspace";
import { AnalysisButton, AnalysisResult } from "./ChatAnalysis";
import { ChatApprovals } from "./ChatApprovals";
import { ChatMessageDetails } from "./ChatMessageDetails";
import type {
  ChatViewAvailability as Availability,
  ChatViewDetail as Detail,
} from "./contracts";
import { CHAT_AGENTS, CHAT_BASE, type ChatAgentId } from "./agents";

type Topic = components["schemas"]["ChatTopic"];
type ModelChoice = "auto" | "gpt-5.4-mini" | "gpt-6.1-sol" | "gpt-6-astra";
type ReasoningChoice = "auto" | "low" | "medium" | "high";
const ACTIVE = ["reading", "thinking"];

export function ChatPage({
  agentId,
  topicId,
}: {
  agentId: ChatAgentId;
  topicId?: string | undefined;
}): React.JSX.Element {
  const agent = CHAT_AGENTS.find((item) => item.id === agentId)!;
  const router = useRouter();
  const { session } = useSession();
  const draftKey = `mana:chat-draft:${session.user.user_id}:${topicId ?? agentId}`;
  const productKey = `mana:chat-product:${session.user.user_id}`;
  const { mutate } = useSWRConfig();
  const [product, setProduct] = useState<"mana" | "360rec">(() => {
    try {
      return sessionStorage.getItem(productKey) === "360rec"
        ? "360rec"
        : "mana";
    } catch {
      return "mana";
    }
  });
  const [draft, setDraft] = useState(() => {
    try {
      return sessionStorage.getItem(draftKey) ?? "";
    } catch {
      return "";
    }
  });
  const [sending, setSending] = useState(false);
  const [modelChoice, setModelChoice] = useState<ModelChoice>("auto");
  const [reasoning, setReasoning] = useState<ReasoningChoice>("auto");
  const [selectedMode, setMode] = useState<"chat" | "goal">("chat");
  const [actionError, setActionError] = useState<string | null>(null);
  const [optimistic, setOptimistic] = useState<string | null>(null);
  const [optimisticId, setOptimisticId] = useState<string | null>(null);
  const [createdTopicId, setCreatedTopicId] = useState<string | null>(null);
  const currentTopicId = topicId ?? createdTopicId;
  const { data: savedGoals, mutate: refreshGoals } = useSWR<Goal[]>(
    currentTopicId ? `${GOALS_BASE}/topics/${currentTopicId}` : null,
  );
  const goals = Array.isArray(savedGoals) ? savedGoals : [];
  const workingGoal = goals.find(
    (goal) => !["completed", "cancelled"].includes(goal.status),
  );
  const mode = workingGoal ? "goal" : selectedMode;
  const goalBusy = Boolean(
    workingGoal &&
    (["queued", "running"].includes(workingGoal.status) ||
      workingGoal.lease_until),
  );
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const guard = useRef(false);
  const requestId = useRef<string | null>(null);
  const requestController = useRef<AbortController | null>(null);
  const { data: goalsAvailability } = useSWR<GoalsAvailability>(
    `${GOALS_BASE}/availability`,
  );
  const goalsEnabled =
    goalsAvailability?.enabled &&
    Number.isFinite(goalsAvailability.budget_microusd) &&
    hasRole(session, "operator") &&
    agentId !== "technical-agent";
  const {
    data: availability,
    error: availabilityError,
    mutate: refreshAvailability,
  } = useSWR<Availability, Error>(`${CHAT_BASE}/availability`);
  const {
    data,
    error,
    isLoading,
    isValidating,
    mutate: refresh,
  } = useSWR<Detail, Error>(
    currentTopicId ? `${CHAT_BASE}/topics/${currentTopicId}` : null,
    {
      refreshInterval: (current) =>
        sending || current?.turns.some((turn) => ACTIVE.includes(turn.status))
          ? 2000
          : 0,
    },
  );
  const turns = data?.turns ?? [];
  const active = turns.find((turn) => ACTIVE.includes(turn.status));
  const scope = data?.topic.product ?? product;
  const wrongAgent = data && data.topic.agent_id !== agentId;
  const busy = sending || Boolean(active) || goalBusy;
  const modelSelectionEnabled =
    mode === "goal"
      ? goalsAvailability?.model_selection_enabled
      : availability?.model_selection_enabled;
  const inference = modelSelectionEnabled
    ? { model_choice: modelChoice, reasoning }
    : {};
  const latestTurn = turns.at(-1);

  useEffect(() => {
    if (sending || active)
      end.current?.scrollIntoView?.({ block: "end", behavior: "instant" });
  }, [turns.length, sending, active]);

  function updateDraft(value: string): void {
    setDraft(value);
    requestId.current = null;
    try {
      sessionStorage.setItem(draftKey, value);
    } catch {
      /* Storage is optional. */
    }
  }

  async function send(): Promise<void> {
    const message = draft.trim();
    if (
      !message ||
      guard.current ||
      busy ||
      !(mode === "goal" ? goalsEnabled : availability?.enabled) ||
      wrongAgent
    )
      return;
    guard.current = true;
    setSending(true);
    setActionError(null);
    let target = currentTopicId;
    const controller = new AbortController();
    requestController.current = controller;
    try {
      if (!target) {
        const created = await apiPost<Topic>(`${CHAT_BASE}/topics`, {
          agent_id: agentId,
          product,
          title: message.replace(/\s+/g, " ").slice(0, 80),
        });
        target = created.topic_id;
        setCreatedTopicId(target);
        await mutate(`${CHAT_BASE}/topics`);
      }
      requestId.current ??= crypto.randomUUID();
      if (mode === "goal") {
        if (workingGoal) {
          await apiPost(
            `${GOALS_BASE}/${workingGoal.goal_id}/commands`,
            {
              request_id: requestId.current,
              command: "steer",
              message,
              expected_revision: workingGoal.revision,
            },
            controller.signal,
          );
          await refreshGoals();
        } else
          await apiPost(
            `${GOALS_BASE}/topics/${target}`,
            {
              request_id: requestId.current,
              objective: message,
              max_steps: goalsAvailability!.max_steps,
              budget_microusd: goalsAvailability!.budget_microusd,
              ...inference,
            },
            controller.signal,
          );
        await mutate(`${GOALS_BASE}/topics/${target}`);
        updateDraft("");
        setMode("chat");
        if (!topicId) router.push(`/chat/${agentId}/topic/${target}`);
        return;
      }
      setOptimisticId(requestId.current);
      setOptimistic(message);
      await apiPost(
        `${CHAT_BASE}/topics/${target}/messages`,
        {
          request_id: requestId.current,
          message,
          ...inference,
        },
        controller.signal,
      );
      const saved = await apiGet<Detail>(`${CHAT_BASE}/topics/${target}`);
      await mutate(`${CHAT_BASE}/topics/${target}`, saved, false);
      updateDraft("");
      if (!topicId) router.push(`/chat/${agentId}/topic/${target}`);
      else await refresh();
    } catch (caught) {
      if (controller.signal.aborted) return;
      setActionError(
        caught instanceof Error
          ? caught.message
          : "Не удалось отправить сообщение. Черновик сохранён.",
      );
      if (target && !topicId) {
        // The server may already be processing the message. Open persisted history, never auto-resend.
        try {
          sessionStorage.setItem(
            `mana:chat-draft:${session.user.user_id}:${target}`,
            message,
          );
        } catch {
          /* Storage is optional. */
        }
        router.push(`/chat/${agentId}/topic/${target}`);
      } else await refresh().catch(() => undefined);
    } finally {
      guard.current = false;
      if (requestController.current === controller)
        requestController.current = null;
      setSending(false);
      setOptimistic(null);
      input.current?.focus();
    }
  }

  async function stop(): Promise<void> {
    if (workingGoal && goalBusy) {
      try {
        await apiPost(`${GOALS_BASE}/${workingGoal.goal_id}/commands`, {
          request_id: crypto.randomUUID(),
          command: "pause",
          expected_revision: workingGoal.revision,
        });
        await refreshGoals();
      } catch (caught) {
        setActionError(
          caught instanceof Error
            ? caught.message
            : "Не удалось приостановить цель.",
        );
        await refreshGoals().catch(() => undefined);
      }
      return;
    }
    if (!active || !currentTopicId) return;
    try {
      await apiPost(
        `${CHAT_BASE}/topics/${currentTopicId}/messages/${active.turn_id}/stop`,
        {},
      );
      requestController.current?.abort();
      updateDraft("");
      await refresh();
      if (!topicId) router.push(`/chat/${agentId}/topic/${currentTopicId}`);
    } catch {
      setActionError("Не удалось остановить ответ. Проверьте состояние темы.");
    }
  }

  function chooseProduct(value: "mana" | "360rec"): void {
    setProduct(value);
    try {
      sessionStorage.setItem(productKey, value);
    } catch {
      /* Storage is optional. Existing topics keep their server-owned scope. */
    }
  }

  return (
    <section
      className={`chat-page${!currentTopicId ? " chat-page-new" : ""}`}
      aria-label={`Чат: ${agent.name}`}
    >
      <header className="chat-header">
        <div>
          <span className={`agent-avatar ${agent.id}`} aria-hidden="true">
            {agent.short}
          </span>
          <div>
            <h1>{agent.name}</h1>
            {(currentTopicId || agent.planned) && (
              <p>
                {currentTopicId ? (data?.topic.title ?? "Загружаем тему…") : ""}
                {agent.planned
                  ? `${currentTopicId ? " · " : ""}Только планирование`
                  : ""}
              </p>
            )}
          </div>
        </div>
        {currentTopicId ? (
          <span
            className="product-chip"
            aria-label={`Приложение: ${scope === "mana" ? "MANA" : "360REC"}`}
          >
            {scope === "mana" ? "MANA" : "360REC"}
          </span>
        ) : (
          <label className="chat-product-picker">
            <span className="sr-only">Приложение</span>
            <select
              value={product}
              onChange={(event) =>
                chooseProduct(event.target.value as "mana" | "360rec")
              }
              disabled={busy}
            >
              <option value="mana">MANA</option>
              <option value="360rec">360REC</option>
            </select>
          </label>
        )}
      </header>
      {topicId && (
        <QueryState
          error={error}
          loading={isLoading}
          hasData={Boolean(data)}
          retrying={isValidating}
          onRetry={refresh}
          subject="переписку"
        />
      )}
      {wrongAgent ? (
        <p role="alert">
          Эта тема принадлежит другому агенту. Выберите её в меню.
        </p>
      ) : (
        <>
          <div
            className="chat-transcript"
            role="log"
            aria-label="Переписка"
            aria-live="polite"
            aria-relevant="additions text"
          >
            {currentTopicId && !wrongAgent && (
              <GoalWorkspace
                key={currentTopicId}
                topicId={currentTopicId}
                inlineSteering={false}
              />
            )}
            {!currentTopicId && (
              <div className="chat-welcome">
                <h2>Над чем поработаем?</h2>
              </div>
            )}
            {topicId &&
              !isLoading &&
              !error &&
              turns.length === 0 &&
              goals.length === 0 && (
                <p className="chat-empty">
                  Тема создана. Напишите первое сообщение.
                </p>
              )}
            {turns.map((turn) => (
              <div className="chat-turn" key={turn.turn_id}>
                <article
                  className="chat-message user-message"
                  aria-label="Ваше сообщение"
                >
                  <p>{turn.message}</p>
                </article>
                <article
                  className="chat-message agent-message"
                  aria-label={`Ответ: ${agent.name}`}
                >
                  <span
                    className={`agent-avatar ${agent.id}`}
                    aria-hidden="true"
                  >
                    {agent.short}
                  </span>
                  <div className="message-body">
                    {ACTIVE.includes(turn.status) ? (
                      <p className="chat-progress" role="status">
                        <span className="working-dot" />
                        {turn.status === "reading"
                          ? "Проверяю сохранённые отчёты…"
                          : "Готовлю ответ с учётом контекста…"}
                      </p>
                    ) : (
                      <p
                        className={
                          turn.status === "failed" ? "chat-failed" : ""
                        }
                      >
                        {turn.answer}
                      </p>
                    )}
                    {turn.analysis_requested && currentTopicId && (
                      <AnalysisResult
                        topicId={currentTopicId}
                        turnId={turn.turn_id}
                      />
                    )}
                    {(turn.next_action === "analyze" ||
                      turn.next_action === "mana_parents") &&
                      currentTopicId &&
                      turn === latestTurn &&
                      turn.status === "completed" &&
                      !turn.analysis_requested &&
                      !agent.planned &&
                      (turn.next_action !== "mana_parents" ||
                        (agent.id === "retention-agent" &&
                          scope === "mana" &&
                          availability?.parent_summary_enabled)) && (
                        <AnalysisButton
                          key={turn.turn_id}
                          kind={
                            turn.next_action === "mana_parents"
                              ? "mana_parents"
                              : "default"
                          }
                          topicId={currentTopicId}
                          confirmation={turn.read_confirmation ?? null}
                          disabled={busy || Boolean(error)}
                          onDone={refresh}
                        />
                      )}
                    {turn.next_action === "approvals" &&
                      turn === latestTurn &&
                      turn.status === "completed" &&
                      agent.id === "growth-agent" && <ChatApprovals />}
                    {(turn.status === "completed" ||
                      turn.status === "failed") && (
                      <ChatMessageDetails turn={turn} />
                    )}
                  </div>
                </article>
              </div>
            ))}
            {optimistic &&
              !turns.some((turn) => turn.request_id === optimisticId) && (
                <div className="chat-turn">
                  <article
                    className="chat-message user-message"
                    aria-label="Отправляемое сообщение"
                  >
                    <p>{optimistic}</p>
                  </article>
                  <p className="chat-progress" role="status">
                    Отправляем сообщение и ожидаем ответ…
                  </p>
                </div>
              )}
            <div ref={end} />
          </div>
          <div className="chat-compose-area">
            {actionError && (
              <p className="chat-error" role="alert">
                {actionError}
              </p>
            )}
            {!availability?.enabled && (
              <p className="chat-notice">
                {availabilityError ? (
                  <>
                    <span>Не удалось проверить доступность AI.</span>{" "}
                    <button
                      type="button"
                      onClick={() =>
                        void refreshAvailability().catch(() => undefined)
                      }
                    >
                      Повторить проверку
                    </button>
                  </>
                ) : availability ? (
                  "AI временно недоступен. Переписка сохранена."
                ) : (
                  "Проверяем доступность AI…"
                )}
              </p>
            )}
            <form
              className="chat-composer"
              onSubmit={(event) => {
                event.preventDefault();
                void send();
              }}
            >
              <label className="sr-only" htmlFor="chat-message">
                {workingGoal ? "Уточнение цели" : "Сообщение агенту"}
              </label>
              <textarea
                id="chat-message"
                ref={input}
                value={draft}
                maxLength={6000}
                placeholder={
                  workingGoal
                    ? "Уточните цель или добавьте контекст…"
                    : mode === "goal"
                      ? "Опишите цель и ожидаемый результат…"
                      : "Опишите задачу…"
                }
                rows={2}
                onChange={(event) => updateDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !event.shiftKey &&
                    !event.nativeEvent.isComposing
                  ) {
                    event.preventDefault();
                    void send();
                  }
                }}
                disabled={busy}
                aria-describedby="chat-composer-hint"
              />
              <div className="composer-toolbar">
                {workingGoal ? (
                  <span>Цель</span>
                ) : goalsEnabled ? (
                  <div
                    className="composer-mode"
                    role="group"
                    aria-label="Режим работы"
                  >
                    <button
                      type="button"
                      aria-pressed={mode === "chat"}
                      disabled={busy}
                      onClick={() => {
                        setMode("chat");
                        requestId.current = null;
                      }}
                    >
                      Чат
                    </button>
                    <button
                      type="button"
                      aria-pressed={mode === "goal"}
                      disabled={busy}
                      onClick={() => {
                        setMode("goal");
                        requestId.current = null;
                      }}
                    >
                      Цель
                    </button>
                  </div>
                ) : (
                  <span>
                    {draft.length > 5000 ? `${draft.length} / 6000` : ""}
                  </span>
                )}
                {modelSelectionEnabled && !workingGoal && (
                  <div className="composer-inference">
                    <select
                      aria-label="Модель AI"
                      value={modelChoice}
                      disabled={busy}
                      onChange={(event) => {
                        setModelChoice(event.target.value as ModelChoice);
                        requestId.current = null;
                      }}
                    >
                      <option value="auto">Авто</option>
                      <option value="gpt-5.4-mini">GPT-5.4 Mini</option>
                      <option value="gpt-6.1-sol">GPT-6.1 Sol</option>
                      <option value="gpt-6-astra">GPT-6 Astra</option>
                    </select>
                    <select
                      aria-label="Глубина анализа"
                      value={reasoning}
                      disabled={busy}
                      onChange={(event) => {
                        setReasoning(event.target.value as ReasoningChoice);
                        requestId.current = null;
                      }}
                    >
                      <option value="auto">Размышление: авто</option>
                      <option value="low">Быстро</option>
                      <option value="medium">Обычное</option>
                      <option value="high">Глубокое</option>
                    </select>
                  </div>
                )}
                {active || goalBusy ? (
                  <button
                    className="chat-send"
                    type="button"
                    onClick={() => void stop()}
                    aria-label={
                      goalBusy ? "Поставить цель на паузу" : "Остановить ответ"
                    }
                  >
                    ■
                  </button>
                ) : (
                  <button
                    className="chat-send"
                    type="submit"
                    disabled={
                      busy ||
                      !draft.trim() ||
                      !(mode === "goal"
                        ? goalsEnabled
                        : availability?.enabled) ||
                      (mode === "goal" &&
                        !workingGoal &&
                        draft.trim().length < 10) ||
                      Boolean(error)
                    }
                    aria-label={
                      workingGoal
                        ? "Уточнить цель"
                        : mode === "goal"
                          ? "Поставить цель"
                          : "Отправить сообщение"
                    }
                  >
                    ↑
                  </button>
                )}
              </div>
            </form>
            <p id="chat-composer-hint" className="sr-only">
              AI может ошибаться. Не отправляйте ключи и личные данные. Новые
              сборы и изменения требуют подтверждения. Enter — отправить,
              Shift+Enter — новая строка.
            </p>
            {mode === "goal" && !workingGoal && (
              <p className="goal-update">
                Агент продолжит работу в фоне. Новое чтение данных — только с
                подтверждением.
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
