"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { apiPost } from "@/api/client";
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
import { WorkspaceActions } from "./WorkspaceActions";
import { ChatMessageDetails } from "./ChatMessageDetails";
import type { ChatViewAvailability as Availability } from "./contracts";
import { CHAT_AGENTS, CHAT_BASE, type ChatAgentId } from "./agents";
import { useWorkspaceStream } from "./useWorkspaceStream";
import { useChatTranscript } from "./useChatTranscript";

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
  const [selectedMode, setMode] = useState<"auto" | "chat" | "goal">("auto");
  const [analysisScope, setAnalysisScope] = useState<
    "current" | "saved_snapshot"
  >("current");
  const [actionError, setActionError] = useState<string | null>(null);
  const [optimistic, setOptimistic] = useState<string | null>(null);
  const [optimisticId, setOptimisticId] = useState<string | null>(null);
  const [createdTopicId, setCreatedTopicId] = useState<string | null>(null);
  const currentTopicId = topicId ?? createdTopicId;
  const {
    data: savedGoals,
    error: savedGoalsError,
    mutate: refreshGoals,
  } = useSWR<Goal[], Error>(
    currentTopicId ? `${GOALS_BASE}/topics/${currentTopicId}` : null,
  );
  const goals = Array.isArray(savedGoals) ? savedGoals : [];
  const workingGoal = goals.find(
    (goal) => !["completed", "cancelled"].includes(goal.status),
  );
  const goalBusy = Boolean(
    workingGoal &&
    (["queued", "running"].includes(workingGoal.status) ||
      workingGoal.lease_until),
  );
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const transcript = useRef<HTMLDivElement>(null);
  const olderScroll = useRef<{ height: number; top: number } | null>(null);
  const olderGuard = useRef(false);
  const readingEarlier = useRef(false);
  const guard = useRef(false);
  const requestId = useRef<string | null>(null);
  const requestController = useRef<AbortController | null>(null);
  const openedTranscript = useRef<string | null>(null);
  const {
    data: goalsAvailability,
    error: goalsAvailabilityError,
    mutate: refreshGoalsAvailability,
  } = useSWR<GoalsAvailability, Error>(`${GOALS_BASE}/availability`);
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
    refresh,
    hasMore,
    loadingOlder,
    loadOlder,
  } = useChatTranscript(
    currentTopicId,
    session.user.user_id,
    availability
      ? Boolean(availability.transcript_pagination_enabled)
      : availabilityError
        ? false
        : undefined,
    sending,
  );
  const turns = data?.turns ?? [];
  const workspaceEnabled = Boolean(
    goalsEnabled &&
    goalsAvailability?.agent_workspace_enabled &&
    availability?.agent_workspace_enabled,
  );
  // A partially loaded or mismatched native deployment is not permission to
  // silently send the same analytical request to the discussion-only API.
  const workspaceOffered = Boolean(
    hasRole(session, "operator") &&
    agentId !== "technical-agent" &&
    (availability?.agent_workspace_enabled ||
      goalsAvailability?.agent_workspace_enabled),
  );
  const mode = workingGoal
    ? "goal"
    : selectedMode === "auto"
      ? workspaceOffered
        ? "agent"
        : "chat"
      : selectedMode;
  const providerReady = Boolean(
    mode === "goal"
      ? goalsEnabled &&
          !goalsAvailabilityError &&
          (workingGoal ||
            analysisScope === "current" ||
            (workspaceEnabled && !availabilityError))
      : mode === "agent"
        ? workspaceEnabled && !goalsAvailabilityError && !availabilityError
        : availability?.enabled && !availabilityError,
  );
  const executionReady = Boolean(
    providerReady &&
    (!currentTopicId || (data && !error && data.topic.agent_id === agentId)),
  );
  const active = turns.find((turn) => ACTIVE.includes(turn.status));
  const scope = data?.topic.product ?? product;
  const wrongAgent = data && data.topic.agent_id !== agentId;
  const busy = sending || Boolean(active);
  const modelSelectionEnabled =
    mode === "goal"
      ? goalsAvailability?.model_selection_enabled
      : availability?.model_selection_enabled;
  const inference = modelSelectionEnabled
    ? { model_choice: modelChoice, reasoning }
    : {};
  const latestTurn = turns.at(-1);
  const latestRevision = latestTurn
    ? `${latestTurn.turn_id}:${latestTurn.status}:${latestTurn.answer}`
    : null;
  const actionTurns = turns
    .filter(
      (turn) =>
        turn.execution_mode === "agent" &&
        turn.status === "completed" &&
        turn.next_action === "approvals",
    )
    .slice(-3);
  const progressStream = useWorkspaceStream(
    currentTopicId,
    session.user.user_id,
    Boolean(
      goalsAvailability?.event_stream_enabled && (sending || workingGoal),
    ),
  );

  useEffect(() => {
    if ((sending || active) && !olderGuard.current && !readingEarlier.current)
      end.current?.scrollIntoView?.({ block: "end", behavior: "instant" });
  }, [latestRevision, sending, active]);

  useLayoutEffect(() => {
    if (!loadingOlder && olderScroll.current && transcript.current) {
      const before = olderScroll.current;
      transcript.current.scrollTop =
        before.top + transcript.current.scrollHeight - before.height;
      olderScroll.current = null;
    }
  }, [turns.length, loadingOlder]);

  async function earlier(): Promise<void> {
    if (!hasMore || olderGuard.current || !transcript.current) return;
    olderGuard.current = true;
    readingEarlier.current = true;
    olderScroll.current = {
      height: transcript.current.scrollHeight,
      top: transcript.current.scrollTop,
    };
    try {
      await loadOlder();
    } catch {
      // The transcript query displays the read error, never resubmits a task.
    } finally {
      olderGuard.current = false;
    }
  }

  useEffect(() => {
    if (
      !currentTopicId ||
      !data ||
      isLoading ||
      wrongAgent ||
      (savedGoals === undefined && !savedGoalsError) ||
      openedTranscript.current === currentTopicId
    )
      return;
    openedTranscript.current = currentTopicId;
    end.current?.scrollIntoView?.({ block: "end", behavior: "instant" });
  }, [
    currentTopicId,
    data,
    isLoading,
    wrongAgent,
    savedGoals,
    savedGoalsError,
  ]);

  const waitingRevision =
    workingGoal?.status === "waiting" ? workingGoal.revision : null;
  useEffect(() => {
    if (waitingRevision !== null)
      end.current?.scrollIntoView?.({ block: "end", behavior: "instant" });
  }, [waitingRevision]);

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
    if (!message || guard.current || busy || !executionReady || wrongAgent)
      return;
    guard.current = true;
    readingEarlier.current = false;
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
              ...(workspaceEnabled && analysisScope === "saved_snapshot"
                ? { analysis_scope: "saved_snapshot", execution_mode: "agent" }
                : {}),
              ...inference,
            },
            controller.signal,
          );
        await mutate(`${GOALS_BASE}/topics/${target}`);
        updateDraft("");
        setMode("auto");
        setAnalysisScope("current");
        if (!topicId) router.push(`/chat/${agentId}/topic/${target}`);
        return;
      }
      setOptimisticId(requestId.current);
      setOptimistic(message);
      await apiPost(
        `${mode === "agent" ? "/api/v1/admin/operation/workspace" : CHAT_BASE}/topics/${target}/messages`,
        {
          request_id: requestId.current,
          message,
          ...(mode === "agent" ? { execution_mode: "agent" } : {}),
          ...inference,
        },
        controller.signal,
      );
      if (mode === "agent") await mutate(`${GOALS_BASE}/topics/${target}`);
      await refresh();
      updateDraft("");
      if (!topicId) router.push(`/chat/${agentId}/topic/${target}`);
    } catch (caught) {
      if (controller.signal.aborted) return;
      setActionError(
        caught instanceof Error
          ? caught.message
          : "Не удалось отправить сообщение. Черновик сохранён.",
      );
      // A lost handoff response may still have created a durable Goal. Observe
      // it without resubmitting the message or restarting the analysis.
      if (target && mode === "agent")
        await mutate(`${GOALS_BASE}/topics/${target}`).catch(() => undefined);
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
            {(currentTopicId || (agent.planned && !workspaceOffered)) && (
              <p>
                {currentTopicId ? (data?.topic.title ?? "Загружаем тему…") : ""}
                {agent.planned && !workspaceOffered
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
            ref={transcript}
            className="chat-transcript"
            role="log"
            aria-label="Переписка"
            aria-live="polite"
            aria-relevant="additions text"
            onScroll={(event) => {
              const element = event.currentTarget;
              readingEarlier.current =
                element.scrollHeight -
                  element.clientHeight -
                  element.scrollTop >
                100;
              if (event.currentTarget.scrollTop < 48 && !error && !loadingOlder)
                void earlier();
            }}
          >
            {hasMore && (
              <div className="chat-history-control">
                <button
                  type="button"
                  disabled={loadingOlder}
                  onClick={() => void earlier()}
                >
                  {loadingOlder ? "Загружаем…" : "Ранние сообщения"}
                </button>
              </div>
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
                      turn.status === "completed" &&
                      (turn.execution_mode === "agent" &&
                      currentTopicId &&
                      availability?.action_reviews_enabled &&
                      scope === "mana" &&
                      actionTurns.includes(turn) ? (
                        <WorkspaceActions
                          topicId={currentTopicId}
                          turnId={turn.turn_id}
                        />
                      ) : turn.execution_mode === "discussion" &&
                        turn === latestTurn &&
                        agent.id === "growth-agent" ? (
                        <ChatApprovals />
                      ) : null)}
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
            {currentTopicId && !wrongAgent && (
              <GoalWorkspace
                progressStream={progressStream}
                key={currentTopicId}
                topicId={currentTopicId}
                inlineSteering={false}
              />
            )}
            <div ref={end} />
          </div>
          <div className="chat-compose-area">
            {actionError && (
              <p className="chat-error" role="alert">
                {actionError}
              </p>
            )}
            {mode === "agent" && !providerReady && (
              <p className="chat-notice" role="status">
                {!goalsAvailabilityError &&
                !availabilityError &&
                (!goalsAvailability || !availability) ? (
                  "Проверяем рабочий режим…"
                ) : (
                  <>
                    <span>Рабочий режим недоступен. Запрос не отправлен.</span>{" "}
                    <button
                      type="button"
                      onClick={() =>
                        void Promise.all([
                          refreshAvailability(),
                          refreshGoalsAvailability(),
                        ]).catch(() => undefined)
                      }
                    >
                      Повторить проверку
                    </button>
                  </>
                )}
              </p>
            )}
            {mode === "goal" && !providerReady && (
              <p className="chat-notice" role="status">
                {!goalsAvailability && !goalsAvailabilityError ? (
                  "Проверяем работу с целями…"
                ) : (
                  <>
                    <span>Работа с целями недоступна. Черновик сохранён.</span>{" "}
                    <button
                      type="button"
                      onClick={() =>
                        void Promise.all([
                          refreshGoalsAvailability(),
                          refreshAvailability(),
                        ]).catch(() => undefined)
                      }
                    >
                      Повторить проверку
                    </button>
                  </>
                )}
              </p>
            )}
            {mode !== "agent" &&
              (!availability?.enabled || availabilityError) && (
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
                ) : workspaceOffered ? (
                  <select
                    aria-label="Режим работы"
                    value={selectedMode}
                    disabled={busy}
                    onChange={(event) => {
                      setMode(event.target.value as "auto" | "chat" | "goal");
                      requestId.current = null;
                    }}
                  >
                    <option value="auto">Агент</option>
                    <option value="chat">Обсудить</option>
                    <option value="goal" disabled={!goalsEnabled}>
                      Цель
                    </option>
                  </select>
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
                {mode === "goal" &&
                  (workspaceEnabled || analysisScope === "saved_snapshot") &&
                  !workingGoal && (
                    <select
                      aria-label="Область анализа"
                      value={analysisScope}
                      disabled={busy}
                      onChange={(event) => {
                        setAnalysisScope(
                          event.target.value as "current" | "saved_snapshot",
                        );
                        requestId.current = null;
                      }}
                    >
                      <option value="current">Текущее положение</option>
                      <option
                        value="saved_snapshot"
                        disabled={!workspaceEnabled}
                      >
                        Сохранённый срез
                      </option>
                    </select>
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
                {(active || goalBusy) && (
                  <button
                    className="chat-send"
                    type="button"
                    disabled={sending}
                    onClick={() => void stop()}
                    aria-label={
                      goalBusy ? "Поставить цель на паузу" : "Остановить ответ"
                    }
                  >
                    ■
                  </button>
                )}
                {!active && (!goalBusy || draft.trim()) && (
                  <button
                    className="chat-send"
                    type="submit"
                    disabled={
                      busy ||
                      !draft.trim() ||
                      !executionReady ||
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
