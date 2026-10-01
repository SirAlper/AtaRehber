import { useQuery } from "@tanstack/react-query";
import { SearchCheck, ShieldAlert, ThumbsDown } from "lucide-react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { AuditEntry } from "@/api/types";
import { Badge, Card, CardTitle, EmptyState, Spinner } from "@/components/ui";
import { formatDate } from "@/lib/utils";

export function ReviewTab() {
  const { t, i18n } = useTranslation();
  const review = useQuery({
    queryKey: ["review"],
    queryFn: () => api<{ items: AuditEntry[] }>("/api/v1/admin/review", { query: { limit: 50 } }),
  });
  return (
    <Card>
      <CardTitle icon={<SearchCheck className="h-4 w-4" />}>{t("admin.review")}</CardTitle>
      <p className="-mt-2 mb-4 text-sm text-slate-600 dark:text-slate-300">{t("review.subtitle")}</p>
      {review.isLoading && <Spinner />}
      {review.data?.items.length === 0 && <EmptyState icon={<SearchCheck className="h-8 w-8" />}>{t("review.empty")}</EmptyState>}
      <ul className="space-y-2">
        {review.data?.items.map((item, index) => {
          const unverified = item.reason === "unverified";
          return (
            <li key={index} className="rounded-xl border border-violet-100 bg-white/60 p-3 dark:border-white/10 dark:bg-white/[0.03]">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <Badge tone={unverified ? "amber" : "rose"}>
                  {unverified ? <ShieldAlert className="h-3 w-3" /> : <ThumbsDown className="h-3 w-3" />}
                  {unverified ? t("review.unverified") : t("review.negative")}
                </Badge>
                <span className="font-medium">{item.username}</span>
                <span className="ml-auto text-xs text-slate-500">{formatDate(item.timestamp, i18n.language)}</span>
              </div>
              <p className="mt-2 text-sm text-slate-700 dark:text-slate-200">
                {(item.detail ?? "").replace(/^\[[^\]]*\]\s*/, "")}
              </p>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
