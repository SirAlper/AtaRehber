import { useQuery } from "@tanstack/react-query";
import { Gauge } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { AgentStat } from "@/api/types";
import { agentName } from "@/chat/AnswerParts";
import { Card, CardTitle, EmptyState, Select, Spinner } from "@/components/ui";
import { cn } from "@/lib/utils";

const PERIODS = [7, 30, 90];

function seconds(ms: number) {
  return ms ? `${(ms / 1000).toFixed(1)} s` : "—";
}

function percent(rate: number) {
  return `${Math.round(rate * 100)}%`;
}

/** Per-agent questions, speed, unverified and failed answers, and user ratings (from the audit log). */
export function StatsTab() {
  const { t } = useTranslation();
  const [days, setDays] = useState(30);
  const stats = useQuery({
    queryKey: ["agent-stats", days],
    queryFn: () => api<{ agents: AgentStat[] }>("/api/v1/admin/agent-stats", { query: { days } }),
  });
  const rows = stats.data?.agents ?? [];

  return (
    <Card>
      <CardTitle
        icon={<Gauge className="h-4 w-4" />}
        action={
          <Select value={days} onChange={(e) => setDays(Number(e.target.value))} className="h-9 w-36 text-xs" aria-label={t("stats.period", { days })}>
            {PERIODS.map((value) => (
              <option key={value} value={value}>
                {t("stats.period", { days: value })}
              </option>
            ))}
          </Select>
        }
      >
        {t("stats.title")}
      </CardTitle>
      {stats.isLoading && <Spinner />}
      {stats.data && rows.length === 0 && <EmptyState icon={<Gauge className="h-8 w-8" />}>{t("stats.empty")}</EmptyState>}
      {rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs tracking-wide text-slate-500 uppercase dark:text-slate-400">
              <tr>
                <th className="py-2 pr-3 font-semibold">{t("stats.agent")}</th>
                <th className="py-2 pr-3 text-right font-semibold">{t("stats.questions")}</th>
                <th className="py-2 pr-3 text-right font-semibold">{t("stats.median")}</th>
                <th className="py-2 pr-3 text-right font-semibold">{t("stats.slow")}</th>
                <th className="py-2 pr-3 text-right font-semibold">{t("stats.unverified")}</th>
                <th className="py-2 pr-3 text-right font-semibold">{t("stats.errors")}</th>
                <th className="py-2 text-right font-semibold">{t("stats.ratings")}</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {rows.map((row) => (
                <tr key={row.agent} className="border-t border-violet-100 dark:border-white/5">
                  <td className="py-2 pr-3 font-medium">
                    {row.agent === "unknown" ? t("stats.unknown") : agentName(t, row.agent)}
                  </td>
                  <td className="py-2 pr-3 text-right">{row.questions}</td>
                  <td className="py-2 pr-3 text-right">{seconds(row.median_ms)}</td>
                  <td className="py-2 pr-3 text-right">{seconds(row.p90_ms)}</td>
                  <td className={cn("py-2 pr-3 text-right", row.warning_rate >= 0.2 && "font-semibold text-amber-600 dark:text-amber-300")}>
                    {row.warnings} ({percent(row.warning_rate)})
                  </td>
                  <td className={cn("py-2 pr-3 text-right", row.errors > 0 && "font-semibold text-rose-600 dark:text-rose-300")}>
                    {row.errors}
                  </td>
                  <td className="py-2 text-right">
                    <span className="text-emerald-600 dark:text-emerald-300">{row.positive}</span>
                    {" / "}
                    <span className={cn(row.negative > row.positive && "font-semibold text-rose-600 dark:text-rose-300")}>{row.negative}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
