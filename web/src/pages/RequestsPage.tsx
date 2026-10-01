import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardList, Inbox, Plus, XCircle } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { RequestStatus, ServiceRequest } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { Badge, Button, Card, CardTitle, EmptyState, Field, Input, Select, Spinner, Textarea } from "@/components/ui";
import { formatDate } from "@/lib/utils";

const STATUSES: RequestStatus[] = ["open", "in_progress", "resolved", "rejected", "cancelled"];
const STATUS_TONES = { open: "sky", in_progress: "amber", resolved: "green", rejected: "rose", cancelled: "slate" } as const;

interface RequestList {
  requests: ServiceRequest[];
  categories: string[];
}

function StaffControls({ request }: { request: ServiceRequest }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [status, setStatus] = useState<RequestStatus>(request.status);
  const [note, setNote] = useState(request.resolution_note);
  const save = useMutation({
    mutationFn: () => api(`/api/v1/requests/${request.id}`, { method: "PATCH", json: { status, resolution_note: note } }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["requests"] });
      toast(t("users.saved"));
    },
    onError: (e) => toast(t("common.error", { error: (e as Error).message }), "error"),
  });
  return (
    <div className="mt-3 grid gap-2 sm:grid-cols-[10rem_1fr_auto]">
      <Select value={status} onChange={(e) => setStatus(e.target.value as RequestStatus)} aria-label={t("requests.statusFilter")}>
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {t(`status.${s}`)}
          </option>
        ))}
      </Select>
      <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("requests.note")} aria-label={t("requests.note")} />
      <Button size="md" onClick={() => save.mutate()} loading={save.isPending}>
        {t("requests.save")}
      </Button>
    </div>
  );
}

export default function RequestsPage() {
  const { t, i18n } = useTranslation();
  const { user, isStaff } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [all, setAll] = useState(false);
  const [statusFilter, setStatusFilter] = useState<RequestStatus | "">("");
  const [category, setCategory] = useState("");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");

  const list = useQuery({
    queryKey: ["requests", all, statusFilter],
    queryFn: () =>
      api<RequestList>("/api/v1/requests", { query: { all_users: all || undefined, status: statusFilter || undefined } }),
  });
  const categories = list.data?.categories ?? [];

  const create = useMutation({
    mutationFn: () =>
      api<{ request: ServiceRequest }>("/api/v1/requests", {
        json: { category: category || categories[0], title, description },
      }),
    onSuccess: (data) => {
      toast(t("requests.created", { id: data.request.id }));
      setTitle("");
      setDescription("");
      void queryClient.invalidateQueries({ queryKey: ["requests"] });
    },
    onError: (e) => toast(t("common.error", { error: (e as Error).message }), "error"),
  });

  const cancel = useMutation({
    mutationFn: (id: number) => api(`/api/v1/requests/${id}`, { method: "PATCH", json: { status: "cancelled" } }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["requests"] }),
    onError: (e) => toast(t("common.error", { error: (e as Error).message }), "error"),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  const categoryLabel = (name: string) => t(`categories.${name}`, { defaultValue: name });

  return (
    <div className="h-full overflow-y-auto p-2 sm:p-4">
      <div className="mx-auto grid max-w-5xl gap-4 lg:grid-cols-[22rem_1fr]">
        <div className="lg:col-span-2">
          <h1 className="flex items-center gap-2 text-2xl font-semibold">
            <ClipboardList className="h-6 w-6 text-violet-600 dark:text-violet-300" />
            <span className="gradient-text">{t("requests.title")}</span>
          </h1>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t("requests.subtitle")}</p>
        </div>

        <Card className="h-fit">
          <CardTitle icon={<Plus className="h-4 w-4" />}>{t("requests.new")}</CardTitle>
          <form onSubmit={submit} className="space-y-3">
            <Field label={t("requests.category")} htmlFor="category">
              <Select id="category" value={category || categories[0] || ""} onChange={(e) => setCategory(e.target.value)}>
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {categoryLabel(c)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label={t("requests.titleField")} htmlFor="title">
              <Input id="title" value={title} onChange={(e) => setTitle(e.target.value)} minLength={3} maxLength={200} required />
            </Field>
            <Field label={t("requests.description")} htmlFor="description">
              <Textarea id="description" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={4000} />
            </Field>
            <Button type="submit" className="w-full" loading={create.isPending}>
              {t("requests.submit")}
            </Button>
          </form>
        </Card>

        <Card>
          <div className="mb-3 flex flex-wrap items-center gap-3">
            <Select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as RequestStatus | "")}
              className="w-40"
              aria-label={t("requests.statusFilter")}
            >
              <option value="">{t("status.all")}</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {t(`status.${s}`)}
                </option>
              ))}
            </Select>
            {isStaff && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} className="accent-violet-600" />
                {t("requests.all")}
              </label>
            )}
          </div>
          {list.isLoading && <Spinner />}
          {list.data && list.data.requests.length === 0 && (
            <EmptyState icon={<Inbox className="h-8 w-8" />}>{t("requests.empty")}</EmptyState>
          )}
          <ul className="space-y-3">
            {list.data?.requests.map((request) => (
              <li key={request.id} className="animate-fade-up rounded-xl border border-violet-100 bg-white/60 p-4 dark:border-white/10 dark:bg-white/[0.03]">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs text-slate-400">#{request.id}</span>
                  <span className="font-medium">{request.title}</span>
                  <Badge tone={STATUS_TONES[request.status]}>{t(`status.${request.status}`)}</Badge>
                  <Badge tone="slate">{categoryLabel(request.category)}</Badge>
                  <span className="ml-auto text-xs text-slate-500">{formatDate(request.created_at, i18n.language)}</span>
                </div>
                {request.description && (
                  <p className="mt-2 text-sm whitespace-pre-line text-slate-600 dark:text-slate-300">{request.description}</p>
                )}
                {request.resolution_note && (
                  <p className="mt-2 rounded-lg bg-violet-50 px-3 py-2 text-sm dark:bg-white/5">📝 {request.resolution_note}</p>
                )}
                {all && <p className="mt-1 text-xs text-slate-500">{t("requests.by", { user: request.username })}</p>}
                {isStaff ? (
                  <StaffControls request={request} />
                ) : (
                  request.status === "open" &&
                  request.username === user?.username && (
                    <Button
                      variant="ghost"
                      size="sm"
                      className="mt-2 text-rose-600"
                      onClick={() => cancel.mutate(request.id)}
                      loading={cancel.isPending && cancel.variables === request.id}
                    >
                      <XCircle className="h-4 w-4" />
                      {t("requests.cancel")}
                    </Button>
                  )
                )}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
