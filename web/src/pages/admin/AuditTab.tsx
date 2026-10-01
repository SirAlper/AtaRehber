import { useMutation, useQuery } from "@tanstack/react-query";
import { Activity, AlertOctagon, FileUp, LogIn, MessageSquareText, ShieldCheck, ThumbsUp } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { AuditEntry } from "@/api/types";
import { Badge, Button, Card, CardTitle, Input, Notice, Select, Spinner } from "@/components/ui";
import { formatDate } from "@/lib/utils";

interface AuditStats {
  total_records: number;
  queries_executed: number;
  stream_queries_executed: number;
  documents_uploaded: number;
  login_events: number;
  error_events: number;
  feedback_events: number;
}

interface ChainCheck {
  valid: boolean;
  checked_entries: number;
  first_invalid_id?: number;
}

function Stat({ icon, label, value }: { icon: ReactNode; label: string; value?: number }) {
  return (
    <div className="glass flex items-center gap-3 p-4">
      <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-200">
        {icon}
      </div>
      <div>
        <p className="text-2xl font-semibold tabular-nums">{value ?? "—"}</p>
        <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
      </div>
    </div>
  );
}

const STATUS_TONE: Record<string, "green" | "rose" | "amber" | "slate"> = {
  success: "green",
  error: "rose",
  denied: "rose",
  warning: "amber",
  cancelled: "slate",
};

export function AuditTab() {
  const { t, i18n } = useTranslation();
  const [username, setUsername] = useState("");
  const [action, setAction] = useState("");
  const [status, setStatus] = useState("");

  const stats = useQuery({ queryKey: ["audit-stats"], queryFn: () => api<AuditStats>("/api/v1/admin/audit-stats") });
  const logs = useQuery({
    queryKey: ["audit-logs", username, action, status],
    queryFn: () =>
      api<{ logs: AuditEntry[]; total: number }>("/api/v1/admin/audit-logs", {
        query: { username: username || undefined, action: action || undefined, status: status || undefined, limit: 100 },
      }),
  });
  const verify = useMutation({ mutationFn: () => api<ChainCheck>("/api/v1/admin/audit-verify") });
  const s = stats.data;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <Stat icon={<Activity className="h-5 w-5" />} label={t("audit.total")} value={s?.total_records} />
        <Stat
          icon={<MessageSquareText className="h-5 w-5" />}
          label={t("audit.queries")}
          value={s ? s.queries_executed + s.stream_queries_executed : undefined}
        />
        <Stat icon={<FileUp className="h-5 w-5" />} label={t("audit.uploads")} value={s?.documents_uploaded} />
        <Stat icon={<LogIn className="h-5 w-5" />} label={t("audit.logins")} value={s?.login_events} />
        <Stat icon={<AlertOctagon className="h-5 w-5" />} label={t("audit.errors")} value={s?.error_events} />
        <Stat icon={<ThumbsUp className="h-5 w-5" />} label={t("audit.feedback")} value={s?.feedback_events} />
      </div>

      <Card>
        <CardTitle
          icon={<Activity className="h-4 w-4" />}
          action={
            <Button size="sm" variant="secondary" loading={verify.isPending} onClick={() => verify.mutate()}>
              <ShieldCheck className="h-4 w-4" />
              {t("audit.verify")}
            </Button>
          }
        >
          {t("admin.audit")}
        </CardTitle>
        {verify.data && (
          <div className="mb-3">
            <Notice tone={verify.data.valid ? "green" : "rose"}>
              {verify.data.valid
                ? t("audit.valid", { count: verify.data.checked_entries })
                : t("audit.invalid", { id: verify.data.first_invalid_id })}
            </Notice>
          </div>
        )}
        <div className="mb-3 grid gap-2 sm:grid-cols-3">
          <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder={t("audit.user")} aria-label={t("audit.user")} />
          <Input value={action} onChange={(e) => setAction(e.target.value)} placeholder={t("audit.action")} aria-label={t("audit.action")} />
          <Select value={status} onChange={(e) => setStatus(e.target.value)} aria-label={t("audit.status")}>
            <option value="">{t("status.all")}</option>
            {Object.keys(STATUS_TONE).map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </Select>
        </div>
        {logs.isLoading && <Spinner />}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-xs text-slate-500 uppercase dark:text-slate-400">
              <tr>
                <th className="py-2 pr-3 font-medium">{t("audit.time")}</th>
                <th className="py-2 pr-3 font-medium">{t("audit.user")}</th>
                <th className="py-2 pr-3 font-medium">{t("audit.action")}</th>
                <th className="py-2 pr-3 font-medium">{t("audit.status")}</th>
                <th className="py-2 font-medium">{t("audit.detail")}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-violet-100 dark:divide-white/5">
              {logs.data?.logs.map((entry, index) => (
                <tr key={entry.id ?? index}>
                  <td className="py-2 pr-3 whitespace-nowrap text-slate-500">{formatDate(entry.timestamp, i18n.language)}</td>
                  <td className="py-2 pr-3">{entry.username}</td>
                  <td className="py-2 pr-3 font-mono text-xs">{entry.action}</td>
                  <td className="py-2 pr-3">
                    <Badge tone={STATUS_TONE[entry.status] ?? "slate"}>{entry.status}</Badge>
                  </td>
                  <td className="max-w-md truncate py-2 text-slate-600 dark:text-slate-300" title={entry.detail}>
                    {entry.detail}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
