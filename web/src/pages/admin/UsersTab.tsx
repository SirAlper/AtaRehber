import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Trash2, UserPlus, Users } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { UserProfile } from "@/api/types";
import { useAuth } from "@/auth/AuthContext";
import { useToast } from "@/components/Toast";
import { Badge, Button, Card, CardTitle, Field, Input, Select, Spinner } from "@/components/ui";
import { splitGroups } from "@/lib/utils";

const ROLES = ["viewer", "editor", "admin"] as const;

function UserRow({ account, self }: { account: UserProfile; self: boolean }) {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [groups, setGroups] = useState(account.groups.join(", "));
  const [role, setRole] = useState(account.role);
  const changed = groups !== account.groups.join(", ") || role !== account.role;
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["users"] });
  const fail = (e: unknown) => toast(t("common.error", { error: (e as Error).message }), "error");

  const patch = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api(`/api/v1/auth/users/${encodeURIComponent(account.username)}`, { method: "PATCH", json: body }),
    onSuccess: () => {
      toast(t("users.saved"));
      refresh();
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: () => api(`/api/v1/auth/users/${encodeURIComponent(account.username)}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: fail,
  });

  return (
    <li className="rounded-xl border border-violet-100 bg-white/60 p-4 dark:border-white/10 dark:bg-white/[0.03]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{account.username}</span>
        <Badge tone={account.disabled ? "slate" : "green"}>{account.disabled ? t("users.disabled") : t("users.active")}</Badge>
        {account.must_change_password && <Badge tone="amber">{t("password.title")}</Badge>}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-[9rem_1fr_auto]">
        <Select value={role} onChange={(e) => setRole(e.target.value as UserProfile["role"])} disabled={self} aria-label={t("users.role")}>
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {t(`roles.${r}`)}
            </option>
          ))}
        </Select>
        <Input value={groups} onChange={(e) => setGroups(e.target.value)} placeholder={t("users.groups")} aria-label={t("users.groups")} />
        <Button disabled={!changed} loading={patch.isPending} onClick={() => patch.mutate({ role, groups: splitGroups(groups) })}>
          {t("common.save")}
        </Button>
      </div>
      {!self && (
        <div className="mt-2 flex flex-wrap gap-1">
          <Button variant="ghost" size="sm" onClick={() => patch.mutate({ disabled: !account.disabled })}>
            {account.disabled ? t("users.enable") : t("users.disable")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              const password = window.prompt(t("users.newPassword"));
              if (password) patch.mutate({ password });
            }}
          >
            <KeyRound className="h-3.5 w-3.5" />
            {t("users.resetPassword")}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="text-rose-600"
            onClick={() => window.confirm(t("users.confirmDelete", { name: account.username })) && remove.mutate()}
          >
            <Trash2 className="h-3.5 w-3.5" />
            {t("users.delete")}
          </Button>
        </div>
      )}
    </li>
  );
}

export function UsersTab() {
  const { t } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<(typeof ROLES)[number]>("viewer");
  const [groups, setGroups] = useState("");

  const users = useQuery({ queryKey: ["users"], queryFn: () => api<UserProfile[]>("/api/v1/auth/users") });
  const create = useMutation({
    mutationFn: () => api("/api/v1/auth/register", { json: { username, password, role, groups: splitGroups(groups) } }),
    onSuccess: () => {
      toast(t("users.created", { name: username }));
      setUsername("");
      setPassword("");
      setGroups("");
      void queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast(t("common.error", { error: (e as Error).message }), "error"),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate();
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
      <Card className="h-fit">
        <CardTitle icon={<UserPlus className="h-4 w-4" />}>{t("users.create")}</CardTitle>
        <form onSubmit={submit} className="space-y-3">
          <Field label={t("users.username")} htmlFor="new-username">
            <Input id="new-username" value={username} onChange={(e) => setUsername(e.target.value)} required minLength={3} autoComplete="off" />
          </Field>
          <Field label={t("users.password")} htmlFor="new-password">
            <Input id="new-password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="new-password" />
          </Field>
          <Field label={t("users.role")} htmlFor="new-role">
            <Select id="new-role" value={role} onChange={(e) => setRole(e.target.value as (typeof ROLES)[number])}>
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {t(`roles.${r}`)}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t("users.groups")} hint={t("documents.groupsHint")} htmlFor="new-groups">
            <Input id="new-groups" value={groups} onChange={(e) => setGroups(e.target.value)} placeholder="ogrenci" />
          </Field>
          <Button type="submit" className="w-full" loading={create.isPending}>
            {t("users.submit")}
          </Button>
        </form>
      </Card>
      <Card>
        <CardTitle icon={<Users className="h-4 w-4" />}>{t("admin.users")}</CardTitle>
        {users.isLoading && <Spinner />}
        <ul className="space-y-2">
          {users.data?.map((account) => (
            <UserRow key={account.username} account={account} self={account.username === user?.username} />
          ))}
        </ul>
      </Card>
    </div>
  );
}
