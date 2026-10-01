import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, MessageSquareReply, Pencil, SearchCheck, ShieldAlert, ThumbsDown, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";

import { api } from "@/api/client";
import type { AuditEntry, FaqEntry } from "@/api/types";
import { useToast } from "@/components/Toast";
import { Badge, Button, Card, CardTitle, EmptyState, Field, Input, Modal, Spinner, Textarea } from "@/components/ui";
import { formatDate, splitGroups } from "@/lib/utils";

interface Draft {
  /** Set when an existing staff answer is changed */
  id?: string;
  question: string;
  answer: string;
  groups: string;
}

function reasonBadge(item: AuditEntry, t: (key: string) => string) {
  if (item.reason === "negative_feedback") {
    return (
      <Badge tone="rose">
        <ThumbsDown className="h-3 w-3" />
        {t("review.negative")}
      </Badge>
    );
  }
  // Unverified and unanswered ("not found") answers are both recorded as warnings
  return (
    <Badge tone="amber">
      <ShieldAlert className="h-3 w-3" />
      {t("review.unverified")}
    </Badge>
  );
}

export function ReviewTab() {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Draft | null>(null);

  const review = useQuery({
    queryKey: ["review"],
    queryFn: () => api<{ items: AuditEntry[] }>("/api/v1/admin/review", { query: { limit: 50 } }),
  });
  const faq = useQuery({ queryKey: ["faq"], queryFn: () => api<{ entries: FaqEntry[] }>("/api/v1/admin/faq") });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["review"] });
    void queryClient.invalidateQueries({ queryKey: ["faq"] });
  };
  const fail = (e: unknown) => toast(t("common.error", { error: (e as Error).message }), "error");

  const save = useMutation({
    mutationFn: (d: Draft) => {
      const json = { question: d.question.trim(), answer: d.answer.trim(), groups: splitGroups(d.groups) };
      return d.id
        ? api(`/api/v1/admin/faq/${d.id}`, { method: "PUT", json })
        : api("/api/v1/admin/faq", { json });
    },
    onSuccess: () => {
      toast(t(draft?.id ? "users.saved" : "review.saved"));
      setDraft(null);
      refresh();
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/v1/admin/faq/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: fail,
  });

  return (
    <div className="space-y-4">
      <Card>
        <CardTitle icon={<SearchCheck className="h-4 w-4" />}>{t("admin.review")}</CardTitle>
        <p className="-mt-2 mb-4 text-sm text-slate-600 dark:text-slate-300">{t("review.subtitle")}</p>
        {review.isLoading && <Spinner />}
        {review.data?.items.length === 0 && <EmptyState icon={<SearchCheck className="h-8 w-8" />}>{t("review.empty")}</EmptyState>}
        <ul className="space-y-2">
          {review.data?.items.map((item, index) => (
            <li key={index} className="rounded-xl border border-violet-100 bg-white/60 p-3 dark:border-white/10 dark:bg-white/[0.03]">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {reasonBadge(item, t)}
                <span className="font-medium">{item.username}</span>
                <span className="ml-auto text-xs text-slate-500">{formatDate(item.timestamp, i18n.language)}</span>
              </div>
              <div className="mt-2 flex flex-wrap items-start gap-2">
                <p className="min-w-0 flex-1 text-sm text-slate-700 dark:text-slate-200">
                  {item.question || <span className="text-slate-400">{t("review.noQuestion")}</span>}
                </p>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => setDraft({ question: item.question ?? "", answer: "", groups: "" })}
                >
                  <MessageSquareReply className="h-3.5 w-3.5" />
                  {t("review.answer")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <CardTitle icon={<BookOpenCheck className="h-4 w-4" />}>{t("review.faqTitle")}</CardTitle>
        {faq.isLoading && <Spinner />}
        {faq.data?.entries.length === 0 && <EmptyState>{t("review.faqEmpty")}</EmptyState>}
        <ul className="space-y-2">
          {faq.data?.entries.map((entry) => (
            <li key={entry.id} className="rounded-xl border border-violet-100 bg-white/60 p-3 dark:border-white/10 dark:bg-white/[0.03]">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium">{entry.question}</span>
                {entry.groups.length > 0 && <Badge tone="amber">{entry.groups.join(", ")}</Badge>}
                <span className="ml-auto text-xs text-slate-500">
                  {t("review.askedBy", { count: entry.asked.length })} · {entry.author} ·{" "}
                  {formatDate(entry.updated_at ?? entry.created_at, i18n.language)}
                </span>
              </div>
              <div className="markdown mt-1.5 text-sm text-slate-700 dark:text-slate-200">
                <ReactMarkdown>{entry.answer}</ReactMarkdown>
              </div>
              <div className="mt-1 flex gap-1">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() =>
                    setDraft({ id: entry.id, question: entry.question, answer: entry.answer, groups: entry.groups.join(", ") })
                  }
                >
                  <Pencil className="h-3.5 w-3.5" />
                  {t("review.edit")}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-rose-600"
                  onClick={() => window.confirm(t("review.confirmDelete")) && remove.mutate(entry.id)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                  {t("review.delete")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <Modal open={!!draft} onClose={() => setDraft(null)} title={t("review.answerTitle")} wide>
        {draft && (
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              save.mutate(draft);
            }}
          >
            <p className="text-sm text-slate-600 dark:text-slate-300">{t("review.answerHint")}</p>
            <Field label={t("review.question")} htmlFor="faq-question">
              <Input
                id="faq-question"
                value={draft.question}
                onChange={(e) => setDraft({ ...draft, question: e.target.value })}
                required
                minLength={3}
                maxLength={500}
              />
            </Field>
            <Field label={t("review.answerText")} htmlFor="faq-answer">
              <Textarea
                id="faq-answer"
                value={draft.answer}
                onChange={(e) => setDraft({ ...draft, answer: e.target.value })}
                required
                maxLength={4000}
                className="min-h-36"
              />
            </Field>
            <Field label={t("documents.groups")} hint={t("documents.groupsHint")} htmlFor="faq-groups">
              <Input id="faq-groups" value={draft.groups} onChange={(e) => setDraft({ ...draft, groups: e.target.value })} />
            </Field>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setDraft(null)}>
                {t("common.cancel")}
              </Button>
              <Button type="submit" loading={save.isPending}>
                {t("common.save")}
              </Button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
}
