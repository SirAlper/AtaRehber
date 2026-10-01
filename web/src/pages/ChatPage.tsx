import { useQuery } from "@tanstack/react-query";
import { ArrowUp, MessageSquarePlus, PanelLeftClose, PanelLeftOpen, Sparkles, Square, Trash2 } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api, ApiError, streamQuery } from "@/api/client";
import type { AgentInfo, QueryResult, StreamEvent } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import {
  AgentBadge,
  agentName,
  AnswerActions,
  EvidenceList,
  level,
  ProgressStages,
  SourcesPanel,
  TracePanel,
  VerificationNote,
} from "@/chat/AnswerParts";
import { useConversations, type ChatMessage } from "@/chat/conversations";
import { Logo } from "@/components/Background";
import { useToast } from "@/components/Toast";
import { Button, Select } from "@/components/ui";
import { setThinking } from "@/lib/activity";
import { cn, newId } from "@/lib/utils";

function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown text-[0.95rem]">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}

export function AssistantMessage({
  message,
  staff,
  onFeedback,
  onPick,
}: {
  message: ChatMessage;
  staff: boolean;
  onFeedback: (value: "positive" | "negative") => void;
  /** Answers a question the assistant asked back; only for the latest answer */
  onPick?: (option: string) => void;
}) {
  const result = message.result;
  const showEvidence = result && (level(result) === "verified" || level(result) === "partial");
  const options = result?.clarification?.options ?? [];
  return (
    <div className="group flex gap-3">
      <Logo className="mt-1 h-8 w-8 shrink-0 drop-shadow" />
      <div className="glass min-w-0 flex-1 px-4 py-3">
        {message.pending && <ProgressStages stages={message.stages ?? []} />}
        {message.error && <p className="text-sm text-rose-700 dark:text-rose-300">{message.error}</p>}
        {result && (
          <>
            <AgentBadge result={result} />
            {result.clarification ? (
              // The question back; its options become buttons below instead of a list
              <Markdown text={result.clarification.question} />
            ) : (
              <Markdown text={result.answer} />
            )}
            {options.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {options.map((option) => (
                  <Button key={option} variant="secondary" size="sm" disabled={!onPick} onClick={() => onPick?.(option)}>
                    {option}
                  </Button>
                ))}
              </div>
            )}
            {showEvidence && <EvidenceList sources={result.sources} />}
            <VerificationNote result={result} />
            <SourcesPanel sources={result.sources} staff={staff} />
            {staff && <TracePanel trace={result.agent_trace ?? []} />}
            <AnswerActions text={result.answer} feedback={message.feedback} onFeedback={onFeedback} />
          </>
        )}
      </div>
    </div>
  );
}

function UserMessage({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-gradient-to-br from-violet-600 to-fuchsia-600 px-4 py-2.5 text-[0.95rem] whitespace-pre-wrap text-white shadow-lg shadow-violet-600/20">
        {text}
      </div>
    </div>
  );
}

export function ChatPage() {
  const { t, i18n } = useTranslation();
  const { user, isGuest, isStaff } = useAuth();
  const toast = useToast();
  const { conversations, active, busy, select, create, update, remove } = useConversations(
    isGuest ? null : (user?.username ?? null),
  );
  const [input, setInput] = useState("");
  const [agent, setAgent] = useState("auto");
  const [sidebar, setSidebar] = useState(true);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // The background comes alive while an answer is being prepared
  useEffect(() => {
    setThinking(busy);
    return () => setThinking(false);
  }, [busy]);

  const history = conversations.filter((c) => c.messages.length);

  const agents = useQuery({
    queryKey: ["agents"],
    queryFn: () => api<{ agents: AgentInfo[] }>("/api/v1/agents"),
    enabled: !isGuest,
  });

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [active.messages]);

  useEffect(() => {
    const area = textareaRef.current;
    if (!area) return;
    area.style.height = "auto";
    area.style.height = `${Math.min(area.scrollHeight, 200)}px`;
  }, [input]);

  function progressLine(event: StreamEvent): string | null {
    switch (event.type) {
      case "agent_selected":
        return event.agent === "supervisor" ? null : t("progress.agent", { agent: agentName(t, event.agent, event.display_name) });
      case "plan":
        return t("progress.plan", { count: event.steps.length });
      case "handoff":
        return t("progress.handoff", { agent: agentName(t, event.to) });
      case "progress":
        return ["searching", "writing", "verifying", "refining"].includes(event.stage) ? t(`progress.${event.stage}`) : null;
      default:
        return null;
    }
  }

  async function ask(question: string) {
    const text = question.trim();
    if (!text || busy) return;
    setInput("");
    const conversationId = active.id;
    const answerId = newId();
    update(conversationId, (c) => ({
      ...c,
      title: c.title || text.slice(0, 60),
      messages: [
        ...c.messages,
        { id: newId(), role: "user", content: text },
        { id: answerId, role: "assistant", content: "", pending: true, stages: [t("progress.thinking")] },
      ],
    }));
    const setAnswer = (change: (m: ChatMessage) => ChatMessage) =>
      update(conversationId, (c) => ({ ...c, messages: c.messages.map((m) => (m.id === answerId ? change(m) : m)) }));

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const result: QueryResult = await streamQuery(
        { question: text, session_id: conversationId, agent: agent === "auto" ? undefined : agent },
        (event) => {
          const line = progressLine(event);
          if (line) setAnswer((m) => ({ ...m, stages: [...(m.stages ?? []), line] }));
        },
        controller.signal,
      );
      setAnswer((m) => ({ ...m, pending: false, content: result.answer, result }));
    } catch (e) {
      let error: string;
      if (controller.signal.aborted) error = t("chat.stopped");
      else if (e instanceof ApiError && e.code === "llm_unavailable") error = t("chat.llmUnavailable");
      else if (e instanceof ApiError && e.status === 503) error = t("chat.busy");
      else if (e instanceof ApiError && e.status === 401) error = t("chat.sessionExpired");
      // The server's own text is English and technical
      else if (e instanceof ApiError && e.status >= 500) error = t("chat.failed");
      else error = t("chat.error", { error: e instanceof Error ? e.message : String(e) });
      setAnswer((m) => ({ ...m, pending: false, error }));
    } finally {
      abortRef.current = null;
    }
  }

  async function sendFeedback(message: ChatMessage, value: "positive" | "negative") {
    const index = active.messages.findIndex((m) => m.id === message.id);
    const question = active.messages[index - 1]?.content ?? "";
    update(active.id, (c) => ({ ...c, messages: c.messages.map((m) => (m.id === message.id ? { ...m, feedback: value } : m)) }));
    try {
      // The rated agent counts in the per-agent statistics
      await api("/api/v1/feedback", { json: { question, feedback: value, agent: message.result?.active_agent ?? "" } });
      toast(t("chat.thanks"));
    } catch (e) {
      toast(t("common.error", { error: e instanceof Error ? e.message : String(e) }), "error");
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void ask(input);
    }
  }

  const suggestions = [
    ...(t("chat.suggestions", { returnObjects: true }) as string[]),
    // Guests cannot file requests
    ...(isGuest ? [] : [t("chat.requestSuggestion")]),
  ];

  return (
    <div className="flex h-full gap-3 p-2 sm:p-4">
      {sidebar && !isGuest && (
        <aside className="glass hidden w-64 shrink-0 flex-col p-3 md:flex">
          <Button onClick={create} className="w-full">
            <MessageSquarePlus className="h-4 w-4" />
            {t("chat.newChat")}
          </Button>
          <p className="mt-4 mb-2 px-1 text-xs font-semibold tracking-wide text-slate-500 uppercase dark:text-slate-400">
            {t("chat.history")}
          </p>
          <ul className="-mx-1 flex-1 space-y-0.5 overflow-y-auto px-1">
            {history.length === 0 && <li className="px-2 text-sm text-slate-400">{t("chat.empty")}</li>}
            {history.map((c) => (
              <li key={c.id} className="group/item relative">
                <button
                  onClick={() => select(c.id)}
                  className={cn(
                    "w-full truncate rounded-lg px-2.5 py-2 pr-8 text-left text-sm transition",
                    c.id === active.id
                      ? "bg-violet-100 font-medium text-violet-900 dark:bg-violet-500/20 dark:text-white"
                      : "text-slate-600 hover:bg-violet-50 dark:text-slate-300 dark:hover:bg-white/5",
                  )}
                  title={c.title}
                >
                  {c.title || t("chat.untitled")}
                </button>
                <button
                  onClick={() => remove(c.id)}
                  className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded p-1 text-slate-400 opacity-0 transition group-hover/item:opacity-100 hover:text-rose-600 focus:opacity-100"
                  aria-label={t("chat.delete")}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </aside>
      )}

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="mb-2 flex items-center gap-2">
          {!isGuest && (
            <Button
              variant="ghost"
              size="icon"
              className="hidden md:inline-flex"
              onClick={() => setSidebar((value) => !value)}
              aria-label={t("chat.history")}
            >
              {sidebar ? <PanelLeftClose className="h-4 w-4" /> : <PanelLeftOpen className="h-4 w-4" />}
            </Button>
          )}
          {!isGuest && (
            <Button variant="secondary" size="icon" className="shrink-0 md:hidden" onClick={create} aria-label={t("chat.newChat")}>
              <MessageSquarePlus className="h-4 w-4" />
            </Button>
          )}
          {/* On phones the conversation list is a menu */}
          {!isGuest && history.length > 0 && (
            <Select
              value={active.messages.length ? active.id : ""}
              onChange={(e) => e.target.value && select(e.target.value)}
              className="h-9 min-w-0 flex-1 text-xs md:hidden"
              aria-label={t("chat.history")}
            >
              {!active.messages.length && <option value="">{t("chat.newChat")}</option>}
              {history.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title || t("chat.untitled")}
                </option>
              ))}
            </Select>
          )}
          {!isGuest && (agents.data?.agents?.length ?? 0) > 0 && (
            <div className="ml-auto flex min-w-0 items-center gap-2">
              <label htmlFor="agent" className="hidden text-xs text-slate-500 sm:inline dark:text-slate-400">
                {t("chat.agent")}
              </label>
              <Select
                id="agent"
                value={agent}
                onChange={(e) => setAgent(e.target.value)}
                className="h-9 w-auto max-w-[45vw] text-xs sm:max-w-xs"
                aria-label={t("chat.agent")}
              >
                <option value="auto">{t("chat.agentAuto")}</option>
                {agents.data!.agents
                  .filter((a) => a.name !== "auto")
                  .map((a) => (
                    <option key={a.name} value={a.name}>
                      {agentName(t, a.name, a.display_name)}
                    </option>
                  ))}
              </Select>
            </div>
          )}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto pr-1">
          {active.messages.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center px-4 text-center">
              <div className="relative">
                {/* A gradient, not a blur filter: blur renders as speckles without GPU acceleration */}
                <div className="absolute -inset-6 animate-pulse rounded-full bg-[radial-gradient(closest-side,color-mix(in_oklab,var(--color-fuchsia-400)_35%,transparent),transparent)]" />
                <Logo className="relative h-16 w-16 drop-shadow-xl" />
              </div>
              <h1 className="mt-5 text-2xl font-semibold">
                <span className="gradient-text">{t("chat.welcomeTitle")}</span>
              </h1>
              <p className="mt-2 max-w-md text-slate-600 dark:text-slate-300">
                {isGuest ? t("chat.welcomeGuest") : t("chat.welcomeText")}
              </p>
              <div className="mt-6 grid w-full max-w-2xl gap-2 sm:grid-cols-2">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => void ask(s)}
                    className="glass flex items-start gap-2 px-4 py-3 text-left text-sm transition hover:-translate-y-0.5 hover:shadow-violet-500/20"
                  >
                    <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-fuchsia-500" />
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="mx-auto max-w-3xl space-y-5 py-2" lang={i18n.language}>
              {active.messages.map((message, index) =>
                message.role === "user" ? (
                  <UserMessage key={message.id} text={message.content} />
                ) : (
                  <AssistantMessage
                    key={message.id}
                    message={message}
                    staff={isStaff}
                    onFeedback={(value) => void sendFeedback(message, value)}
                    // Only the latest question back can still be answered
                    onPick={index === active.messages.length - 1 && !busy ? (option) => void ask(option) : undefined}
                  />
                ),
              )}
              <div ref={endRef} />
            </div>
          )}
        </div>

        <div className="mx-auto mt-2 w-full max-w-3xl">
          <div className="glass flex items-end gap-2 p-2 focus-within:ring-4 focus-within:ring-violet-500/15">
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={t("chat.placeholder")}
              aria-label={t("chat.placeholder")}
              maxLength={4000}
              className="max-h-52 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[0.95rem] placeholder:text-slate-400 focus:outline-none"
            />
            {busy ? (
              <Button variant="secondary" size="icon" onClick={() => abortRef.current?.abort()} aria-label={t("chat.stop")}>
                <Square className="h-4 w-4" />
              </Button>
            ) : (
              <Button size="icon" onClick={() => void ask(input)} disabled={!input.trim()} aria-label={t("chat.send")}>
                <ArrowUp className="h-4 w-4" />
              </Button>
            )}
          </div>
          <p className="mt-1.5 text-center text-[11px] text-slate-500 dark:text-slate-400">
            {/* Phones have no Shift+Enter */}
            <span className="hidden sm:inline">{t("chat.enterHint")} · </span>
            {t("chat.disclaimer")}
          </p>
        </div>
      </section>
    </div>
  );
}
