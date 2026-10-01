"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { apiGet, apiPost } from "@/api/client";
import type { components } from "@/api/schema";
import { QueryState } from "@/components/QueryState";
import { useSession } from "@/auth/SessionContext";
import { AnalysisButton, AnalysisResult } from "./ChatAnalysis";
import { ChatApprovals } from "./ChatApprovals";
import { ChatMessageDetails } from "./ChatMessageDetails";
import type {
  ChatViewAvailability as Availability,
  ChatViewDetail as Detail,
} from "./contracts";
import { CHAT_AGENTS, CHAT_BASE, type ChatAgentId } from "./agents";

type Topic = components["schemas"]["ChatTopic"];
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
  const [actionError, setActionError] = useState<string | null>(null);
  const [optimistic, setOptimistic] = useState<string | null>(null);
  const [optimisticId, setOptimisticId] = useState<string | null>(null);
  const [createdTopicId, setCreatedTopicId] = useState<string | null>(null);
  const currentTopicId = topicId ?? createdTopicId;
  const input = useRef<HTMLTextAreaElement>(null);
  const end = useRef<HTMLDivElement>(null);
  const guard = useRef(false);
  const requestId = useRef<string | null>(null);
  const requestController = useRef<AbortController | null>(null);
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
  const busy = sending || Boolean(active);
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
      !availability?.enabled ||
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
      setOptimisticId(requestId.current);
      setOptimistic(message);
      await apiPost(
        `${CHAT_BASE}/topics/${target}/messages`,
        {
          request_id: requestId.current,
          message,
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
            {!currentTopicId && (
              <div className="chat-welcome">
                <h2>Над чем поработаем?</h2>
              </div>
            )}
            {topicId && !isLoading && !error && turns.length === 0 && (
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
                          disabled={busy || Boolean(error)}
                          onDone={refresh}
                        />
                      )}
                    {turn.next_action === "approvals" &&
                      turn === latestTurn &&
                      turn.status === "completed" &&
                      agent.id === "growth-agent" && <ChatApprovals />}
                    {turn.status === "completed" && (
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
                Сообщение агенту
              </label>
              <textarea
                id="chat-message"
                ref={input}
                value={draft}
                maxLength={6000}
                placeholder="Опишите задачу…"
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
                <span>
                  {draft.length > 5000 ? `${draft.length} / 6000` : ""}
                </span>
                {active ? (
                  <button
                    className="chat-send"
                    type="button"
                    onClick={() => void stop()}
                    aria-label="Остановить ответ"
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
                      !availability?.enabled ||
                      Boolean(error)
                    }
                    aria-label="Отправить сообщение"
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
          </div>
        </>
      )}
    </section>
  );
}
