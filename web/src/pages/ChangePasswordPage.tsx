import { KeyRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Button, Field, Input, Notice } from "@/components/ui";

export function ChangePasswordPage() {
  const { t } = useTranslation();
  const { changePassword, logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (next !== confirm) {
      setError(t("password.mismatch"));
      return;
    }
    setBusy(true);
    try {
      await changePassword(current, next);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-dvh items-center justify-center p-4">
      <form onSubmit={submit} className="glass animate-fade-up w-full max-w-md space-y-4 p-8">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-200">
          <KeyRound className="h-6 w-6" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold">{t("password.title")}</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("password.subtitle")}</p>
        </div>
        <Field label={t("password.current")} htmlFor="current">
          <Input
            id="current"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
          />
        </Field>
        <Field label={t("password.new")} htmlFor="new">
          <Input id="new" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required />
        </Field>
        <Field label={t("password.confirm")} htmlFor="confirm">
          <Input
            id="confirm"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
        </Field>
        {error && <Notice tone="rose">{error}</Notice>}
        <div className="flex gap-2">
          <Button type="button" variant="secondary" onClick={() => void logout()}>
            {t("nav.logout")}
          </Button>
          <Button type="submit" className="flex-1" loading={busy}>
            {t("password.submit")}
          </Button>
        </div>
      </form>
    </div>
  );
}
