import {
  AlertTriangle,
  BadgeCheck,
  Bot,
  ChevronDown,
  Copy,
  Database,
  FileText,
  Inbox,
  GitBranch,
  Quote,
  ShieldAlert,
  ThumbsDown,
  ThumbsUp,
  Wrench,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { QueryResult, Source, TraceEntry } from "@/api/types";
import { Badge, Button } from "@/components/ui";
import { articleShort, chunkText, cn, documentName } from "@/lib/utils";

const BUILT_IN_AGENTS = ["supervisor", "doc_agent", "db_agent", "compliance_agent", "request_agent", "multi_agent"];

export function agentName(t: (key: string) => string, name: string, displayName?: string) {
  return BUILT_IN_AGENTS.includes(name) ? t(`agents.${name}`) : displayName || name;
}

export function AgentBadge({ result }: { result: QueryResult }) {
  const { t } = useTranslation();
  const combined = result.active_agent === "multi_agent";
  return (
    <div className="mb-2 flex flex-wrap items-center gap-1.5">
      <Badge tone={combined ? "sky" : "violet"}>
        {combined ? <GitBranch className="h-3 w-3" /> : <Bot className="h-3 w-3" />}
        {agentName(t, result.active_agent)}
      </Badge>
      {combined &&
        (result.agents ?? []).map((agent) => (
          <Badge key={agent} tone="slate">
            {agentName(t, agent)}
          </Badge>
        ))}
    </div>
  );
}

/** "verified" / "partial" / "unverified", or undefined for answers that were not checked. */
export function level(result: QueryResult) {
  return result.verification?.level ?? (result.hallucination_grade ? "unverified" : undefined);
}

export function VerificationNote({ result }: { result: QueryResult }) {
  const { t } = useTranslation();
  const current = level(result);
  const issues = result.verification?.issues ?? [];
  if (issues.includes("not_found")) {
    // Unanswered: staff see it in their review list and may answer it
    return (
      <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-600 dark:text-slate-300">
        <Inbox className="h-4 w-4 text-violet-500" />
        {t("verification.notFound")}
      </p>
    );
  }
  if (current === "verified" && issues.includes("data")) {
    return (
      <p className="mt-3 flex items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-300">
        <Database className="h-4 w-4" />
        {t("verification.data")}
      </p>
    );
  }
  if (!current || !result.sources.length) return null;
  if (current === "verified") {
    return (
      <div className="mt-3 space-y-2">
        <p className="flex items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-300">
          <BadgeCheck className="h-4 w-4" />
          {result.is_refined ? t("verification.refined") : t("verification.verified")}
        </p>
        {issues.includes("transitional") && (
          <p className="flex items-start gap-1.5 rounded-lg bg-amber-100/80 px-2.5 py-1.5 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {t("verification.transitional")}
          </p>
        )}
      </div>
    );
  }
  if (current === "partial") {
    return (
      <p className="mt-3 flex items-start gap-1.5 rounded-lg bg-amber-100/80 px-2.5 py-1.5 text-xs text-amber-900 dark:bg-amber-500/10 dark:text-amber-200">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        {t("verification.partial")}
      </p>
    );
  }
  const sections = [...new Set(result.sources.map((s) => articleShort(s.article) || documentName(s.source)))].slice(0, 3);
  return (
    <div className="mt-3 space-y-1.5 text-xs">
      <p className="flex items-center gap-1.5 font-medium text-rose-700 dark:text-rose-300">
        <ShieldAlert className="h-4 w-4" />
        {t("verification.unverified")}
      </p>
      <p className="text-slate-600 dark:text-slate-300">{t("verification.related", { sections: sections.join(", ") })}</p>
    </div>
  );
}

export function EvidenceList({ sources }: { sources: Source[] }) {
  const { t } = useTranslation();
  const items = sources.flatMap((source) => (source.evidence ?? []).map((evidence) => ({ evidence, source })));
  if (!items.length) return null;
  return (
    <div className="mt-3 space-y-2">
      {items.map(({ evidence, source }, index) => (
        <figure
          key={index}
          className="rounded-xl border-l-4 border-violet-500 bg-gradient-to-r from-violet-100/80 to-fuchsia-50/50 px-3.5 py-2.5 dark:from-violet-500/15 dark:to-fuchsia-500/5"
        >
          <figcaption className="mb-1 flex flex-wrap items-center gap-x-2 text-xs font-semibold text-violet-800 dark:text-violet-200">
            <Quote className="h-3.5 w-3.5" />
            {t("sources.evidence")}
            <span>· {evidence.citation || articleShort(source.article)}</span>
            <span className="font-normal text-slate-500 dark:text-slate-400">· {documentName(source.source)}</span>
          </figcaption>
          <blockquote className="text-sm text-slate-700 dark:text-slate-200">“{evidence.text}”</blockquote>
        </figure>
      ))}
    </div>
  );
}

function pageLabel(t: (key: string, options?: Record<string, unknown>) => string, source: Source) {
  if (source.page == null) return "";
  if (source.page_end && source.page_end !== source.page)
    return t("sources.pages", { start: source.page, end: source.page_end });
  return t("sources.page", { page: source.page });
}

/** Highlight the evidence sentences inside a source's text. */
function Highlighted({ text, marks }: { text: string; marks: string[] }) {
  const found = marks.filter((mark) => mark && text.includes(mark));
  if (!found.length) return <>{text}</>;
  const pattern = new RegExp(`(${found.map((m) => m.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
  return (
    <>
      {text.split(pattern).map((part, index) =>
        found.includes(part) ? (
          <mark key={index} className="rounded bg-fuchsia-200/70 px-0.5 text-slate-900 dark:bg-fuchsia-500/30 dark:text-white">
            {part}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

const PREVIEW = 420;

function SourceItem({ source, index, staff }: { source: Source; index: number; staff: boolean }) {
  const { t } = useTranslation();
  const [full, setFull] = useState(false);
  const text = chunkText(source.content);
  const marks = (source.evidence ?? []).map((e) => e.text);
  const firstMark = Math.max(0, Math.min(...marks.map((m) => text.indexOf(m)).filter((i) => i >= 0), Infinity));
  const start = !full && Number.isFinite(firstMark) && firstMark > PREVIEW / 2 ? firstMark - 120 : 0;
  const shown = full ? text : text.slice(start, start + PREVIEW);
  const title = [documentName(source.source), pageLabel(t, source), source.article].filter(Boolean).join(" — ");
  return (
    <li className="rounded-xl border border-violet-100 bg-white/60 p-3 dark:border-white/10 dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
        <FileText className="h-4 w-4 text-violet-500" />
        <span>
          {index}. {title}
        </span>
        {staff && (
          <span className="text-xs font-normal text-slate-500">
            {t("sources.chunk", { index: source.chunk_index ?? 0 })}
            {source.reranker_score != null && ` · ${t("sources.score", { score: source.reranker_score })}`}
          </span>
        )}
      </div>
      <p className="mt-2 text-sm whitespace-pre-line text-slate-600 dark:text-slate-300">
        {start > 0 && "… "}
        <Highlighted text={shown} marks={marks} />
        {!full && start + PREVIEW < text.length && " …"}
      </p>
      {text.length > PREVIEW && (
        <button
          className="mt-1 text-xs font-medium text-violet-700 hover:underline dark:text-violet-300"
          onClick={() => setFull((value) => !value)}
        >
          {full ? t("sources.lessText") : t("sources.fullText")}
        </button>
      )}
    </li>
  );
}

/** Sources the answer relies on first; other chunks of the same article merged. */
export function SourcesPanel({ sources, staff }: { sources: Source[]; staff: boolean }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const groups = new Map<string, Source>();
  for (const source of sources) {
    const key = `${source.source}|${source.article ?? source.chunk_index}`;
    const current = groups.get(key);
    if (!current || (source.used && !current.used)) groups.set(key, source);
  }
  const unique = [...groups.values()];
  const used = unique.filter((s) => s.used);
  const others = unique.filter((s) => !s.used);
  if (!unique.length) return null;
  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-xs font-semibold text-violet-700 hover:text-violet-900 dark:text-violet-300 dark:hover:text-white"
      >
        <ChevronDown className={cn("h-4 w-4 transition", open && "rotate-180")} />
        {t("sources.title", { count: unique.length })}
      </button>
      {open && (
        <ul className="animate-fade-up mt-2 space-y-2">
          {used.map((source, index) => (
            <SourceItem key={index} source={source} index={index + 1} staff={staff} />
          ))}
          {used.length > 0 && others.length > 0 && (
            <li className="pt-1 text-xs font-medium text-slate-500 dark:text-slate-400">{t("sources.related")}</li>
          )}
          {others.map((source, index) => (
            <SourceItem key={`o${index}`} source={source} index={used.length + index + 1} staff={staff} />
          ))}
        </ul>
      )}
    </div>
  );
}

export function TracePanel({ trace }: { trace: TraceEntry[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  if (!trace.length) return null;
  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex items-center gap-1.5 text-xs font-medium text-slate-500 hover:text-violet-700 dark:text-slate-400 dark:hover:text-violet-200"
      >
        <Wrench className="h-3.5 w-3.5" />
        {t("sources.trace", { count: trace.length })}
      </button>
      {open && (
        <ol className="animate-fade-up mt-2 space-y-1.5 border-l-2 border-violet-200 pl-3 text-xs dark:border-violet-500/30">
          {trace.map((step, index) => (
            <li key={index} className="text-slate-600 dark:text-slate-300">
              <span className="font-mono font-medium text-violet-700 dark:text-violet-300">{step.agent}</span>{" "}
              {step.action}
              {step.target_agent && ` → ${step.target_agent}`}
              {step.status && <span className="text-slate-400"> · {step.status}</span>}
              {step.duration_ms != null && <span className="text-slate-400"> · {step.duration_ms} ms</span>}
              {step.tools_called?.length ? <span className="text-slate-400"> · {step.tools_called.join(", ")}</span> : null}
              {step.search_query && <div className="text-slate-400">🔎 {step.search_query}</div>}
              {step.sql && <pre className="mt-1 overflow-x-auto rounded bg-slate-900 p-2 text-slate-100">{step.sql}</pre>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function ProgressStages({ stages }: { stages: string[] }) {
  return (
    <ol className="space-y-1.5" aria-live="polite">
      {stages.map((stage, index) => {
        const current = index === stages.length - 1;
        return (
          <li
            key={index}
            className={cn(
              "flex items-center gap-2 text-sm",
              current ? "font-medium text-violet-800 dark:text-violet-200" : "text-slate-400 dark:text-slate-500",
            )}
          >
            <span
              className={cn(
                "h-2 w-2 rounded-full",
                current ? "animate-pulse bg-gradient-to-r from-violet-500 to-fuchsia-500" : "bg-violet-300 dark:bg-violet-700",
              )}
            />
            {stage}
          </li>
        );
      })}
      <li className="shimmer mt-1 h-2 w-40 rounded-full" />
    </ol>
  );
}

export function AnswerActions({
  text,
  feedback,
  onFeedback,
}: {
  text: string;
  feedback?: "positive" | "negative";
  onFeedback: (value: "positive" | "negative") => void;
}) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-3 flex items-center gap-1 opacity-80 transition group-hover:opacity-100">
      <Button
        variant="ghost"
        size="sm"
        onClick={() => {
          void navigator.clipboard?.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
      >
        <Copy className="h-3.5 w-3.5" />
        {copied ? t("chat.copied") : t("chat.copy")}
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className={cn("h-8 w-8", feedback === "positive" && "text-emerald-600 dark:text-emerald-300")}
        onClick={() => onFeedback("positive")}
        aria-label={t("chat.helpful")}
        aria-pressed={feedback === "positive"}
        disabled={!!feedback}
      >
        <ThumbsUp className="h-3.5 w-3.5" />
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className={cn("h-8 w-8", feedback === "negative" && "text-rose-600 dark:text-rose-300")}
        onClick={() => onFeedback("negative")}
        aria-label={t("chat.notHelpful")}
        aria-pressed={feedback === "negative"}
        disabled={!!feedback}
      >
        <ThumbsDown className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}
