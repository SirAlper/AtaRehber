import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, Cpu, Database, HardDrive, Play, RotateCcw, Sparkles, Wrench } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { Backup, Stats } from "@/api/types";
import { useToast } from "@/components/Toast";
import { Badge, Button, Card, CardTitle, Input, Spinner, Textarea } from "@/components/ui";
import { formatDate } from "@/lib/utils";

interface DatabaseStatus {
  connection: { status: string; dialect?: string | null; tables?: string[]; message?: string };
  schema_summary?: string;
}

interface QueryResultRows {
  status: string;
  message?: string;
  columns: string[];
  rows: Record<string, unknown>[];
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-violet-100 py-2 text-sm last:border-0 dark:border-white/5">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  );
}

export function SystemTab() {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [sql, setSql] = useState("");
  const [table, setTable] = useState("");
  const [days, setDays] = useState(30);
  const fail = (e: unknown) => toast(t("common.error", { error: (e as Error).message }), "error");
  const done = () => toast(t("system.done"));

  const stats = useQuery({ queryKey: ["stats"], queryFn: () => api<Stats>("/api/v1/stats") });
  const database = useQuery({ queryKey: ["database"], queryFn: () => api<DatabaseStatus>("/api/v1/database/status") });
  const backups = useQuery({ queryKey: ["backups"], queryFn: () => api<{ backups: Backup[] }>("/api/v1/admin/backups") });

  const runQuery = useMutation({
    mutationFn: () => api<QueryResultRows>("/api/v1/database/test-query", { json: { query: sql } }),
    onError: fail,
  });
  const sync = useMutation({
    mutationFn: () => api<{ message?: string }>("/api/v1/database/sync-table", { json: { table_name: table } }),
    onSuccess: done,
    onError: fail,
  });
  const backup = useMutation({
    mutationFn: () => api("/api/v1/admin/backup", { method: "POST" }),
    onSuccess: () => {
      done();
      void queryClient.invalidateQueries({ queryKey: ["backups"] });
    },
    onError: fail,
  });
  const restore = useMutation({
    mutationFn: (name: string) => api<{ message: string }>("/api/v1/admin/restore", { method: "POST", query: { backup_name: name } }),
    onSuccess: (data) => toast(data.message),
    onError: fail,
  });
  const maintenance = useMutation({ mutationFn: () => api("/api/v1/admin/maintenance/run", { method: "POST" }), onSuccess: done, onError: fail });
  const cleanup = useMutation({
    mutationFn: () => api("/api/v1/admin/cleanup-sessions", { method: "POST", query: { max_age_days: days } }),
    onSuccess: done,
    onError: fail,
  });

  const s = stats.data;
  const connection = database.data?.connection;
  const connected = connection?.status === "connected" || connection?.status === "success";

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardTitle icon={<Cpu className="h-4 w-4" />}>{t("system.models")}</CardTitle>
        {stats.isLoading && <Spinner />}
        {s && (
          <>
            <Row label={t("system.answerModel")}>{s.llm_model}</Row>
            <Row label={t("system.llmStatus")}>
              <Badge tone={s.llm_status === "ok" ? "green" : "rose"}>{s.llm_status}</Badge>
            </Row>
            <Row label={t("system.device")}>{s.device}</Row>
            <Row label={t("system.documents")}>{s.total_documents}</Row>
            <Row label={t("system.chunks")}>{s.total_chunks}</Row>
          </>
        )}
      </Card>

      <Card>
        <CardTitle icon={<Wrench className="h-4 w-4" />}>{t("system.maintenance")}</CardTitle>
        <div className="space-y-3">
          <Button variant="secondary" className="w-full" loading={maintenance.isPending} onClick={() => maintenance.mutate()}>
            <Sparkles className="h-4 w-4" />
            {t("system.maintenance")}
          </Button>
          <div className="flex gap-2">
            <Input
              type="number"
              min={1}
              max={365}
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="w-24"
              aria-label={t("system.days")}
            />
            <Button variant="secondary" className="flex-1" loading={cleanup.isPending} onClick={() => cleanup.mutate()}>
              {t("system.cleanup")} ({days} {t("system.days")})
            </Button>
          </div>
        </div>
      </Card>

      <Card className="lg:col-span-2">
        <CardTitle icon={<Database className="h-4 w-4" />}>{t("system.database")}</CardTitle>
        {database.isLoading && <Spinner />}
        {connection && (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <Badge tone={connected ? "green" : "slate"}>
                {connected ? t("system.connected", { dialect: connection.dialect ?? "" }) : t("system.notConnected")}
              </Badge>
              {connection.tables?.map((name) => (
                <Badge key={name} tone="violet">
                  {name}
                </Badge>
              ))}
            </div>
            {connected && (
              <>
                <Textarea value={sql} onChange={(e) => setSql(e.target.value)} placeholder="SELECT * FROM …" className="min-h-20 font-mono text-xs" aria-label={t("system.testQuery")} />
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" loading={runQuery.isPending} disabled={!sql.trim()} onClick={() => runQuery.mutate()}>
                    <Play className="h-3.5 w-3.5" />
                    {t("system.run")}
                  </Button>
                  <Input value={table} onChange={(e) => setTable(e.target.value)} placeholder={t("system.tables")} className="h-8 w-48" aria-label={t("system.tables")} />
                  <Button size="sm" variant="secondary" loading={sync.isPending} disabled={!table.trim()} onClick={() => sync.mutate()}>
                    {t("system.sync")}
                  </Button>
                </div>
                {runQuery.data && (
                  <div className="overflow-x-auto rounded-xl border border-violet-100 dark:border-white/10">
                    {runQuery.data.status !== "success" ? (
                      <p className="p-3 text-sm text-rose-600">{runQuery.data.message}</p>
                    ) : (
                      <table className="w-full text-left text-xs">
                        <thead className="bg-violet-50 dark:bg-white/5">
                          <tr>
                            {runQuery.data.columns.map((column) => (
                              <th key={column} className="px-2 py-1.5 font-semibold">
                                {column}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {runQuery.data.rows.map((row, index) => (
                            <tr key={index} className="border-t border-violet-100 dark:border-white/5">
                              {runQuery.data!.columns.map((column) => (
                                <td key={column} className="px-2 py-1.5">
                                  {String(row[column] ?? "")}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </Card>

      <Card className="lg:col-span-2">
        <CardTitle
          icon={<Archive className="h-4 w-4" />}
          action={
            <Button size="sm" loading={backup.isPending} onClick={() => backup.mutate()}>
              <HardDrive className="h-4 w-4" />
              {t("system.createBackup")}
            </Button>
          }
        >
          {t("system.backups")}
        </CardTitle>
        {backups.isLoading && <Spinner />}
        <ul className="space-y-2">
          {backups.data?.backups.map((item) => (
            <li key={item.name} className="flex flex-wrap items-center gap-2 rounded-xl border border-violet-100 px-3 py-2 text-sm dark:border-white/10">
              <Badge tone={item.type === "full" ? "violet" : "slate"}>{item.type}</Badge>
              <span className="font-mono text-xs">{item.name}</span>
              <span className="ml-auto text-xs text-slate-500">{formatDate(item.created_at, i18n.language)}</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => window.confirm(t("system.confirmRestore", { name: item.name })) && restore.mutate(item.name)}
              >
                <RotateCcw className="h-3.5 w-3.5" />
                {t("system.restore")}
              </Button>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
