import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";

import { api } from "@/api/client";
import type { FaqNotice } from "@/api/types";
import { Button, EmptyState, Modal } from "@/components/ui";
import { formatDate } from "@/lib/utils";

/** Staff answers to the user's unanswered questions: a bell with the count, the answers in a dialog. */
export function NoticeBell() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const notices = useQuery({
    queryKey: ["faq-answers"],
    queryFn: () => api<{ answers: FaqNotice[] }>("/api/v1/faq/answers"),
    refetchInterval: 60_000,
  });
  const seen = useMutation({
    mutationFn: (ids: string[]) => api("/api/v1/faq/answers/seen", { json: { ids } }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["faq-answers"] }),
  });
  const answers = notices.data?.answers ?? [];

  return (
    <>
      <Button
        variant="ghost"
        size="icon"
        className="relative"
        onClick={() => setOpen(true)}
        aria-label={t("nav.notices")}
        title={t("nav.notices")}
      >
        <Bell className="h-4 w-4" />
        {answers.length > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-fuchsia-600 px-1 text-[10px] font-bold text-white">
            {answers.length}
          </span>
        )}
      </Button>
      <Modal open={open} onClose={() => setOpen(false)} title={t("notices.title")}>
        <p className="mb-4 text-sm text-slate-600 dark:text-slate-300">{t("notices.subtitle")}</p>
        {answers.length === 0 && <EmptyState icon={<Bell className="h-8 w-8" />}>{t("notices.empty")}</EmptyState>}
        <ul className="space-y-3">
          {answers.map((item) => (
            <li key={item.id} className="rounded-xl border border-violet-100 bg-white/60 p-3 dark:border-white/10 dark:bg-white/[0.03]">
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {t("notices.asked")} · {formatDate(item.updated_at, i18n.language)}
              </p>
              <p className="mt-0.5 font-medium">{item.question}</p>
              <div className="markdown mt-2 text-sm">
                <ReactMarkdown>{item.answer}</ReactMarkdown>
              </div>
              <div className="mt-2 flex justify-end">
                <Button size="sm" variant="secondary" loading={seen.isPending} onClick={() => seen.mutate([item.id])}>
                  {t("notices.seen")}
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </Modal>
    </>
  );
}
