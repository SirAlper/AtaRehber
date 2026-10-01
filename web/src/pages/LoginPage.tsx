import { BookOpenCheck, Languages, LockKeyhole, Moon, ShieldCheck, Sparkles, Sun, UserRound } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "@/api/client";
import { useAuth } from "@/auth/AuthContext";
import { Logo } from "@/components/Background";
import { Button, Field, Input, Notice } from "@/components/ui";
import { setLanguage } from "@/i18n";
import { useTheme } from "@/lib/theme";

const FEATURES = [
  { icon: BookOpenCheck, tr: "Madde numarasıyla kaynak gösterir", en: "Cites the article it relies on" },
  { icon: ShieldCheck, tr: "Emin olmadığında cevap uydurmaz", en: "Does not invent answers it cannot verify" },
  { icon: LockKeyhole, tr: "Veriler kurum sunucusundan çıkmaz", en: "Data never leaves the organization's server" },
];

export function LoginPage() {
  const { t, i18n } = useTranslation();
  const { login, startGuest, guestEnabled } = useAuth();
  const { theme, toggle } = useTheme();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"login" | "guest" | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy("login");
    try {
      await login(username.trim(), password);
    } catch (e) {
      setError(t("login.failed", { error: e instanceof ApiError ? e.message : String(e) }));
    } finally {
      setBusy(null);
    }
  }

  async function guest() {
    setError("");
    setBusy("guest");
    try {
      await startGuest();
    } catch (e) {
      setError(t("login.failed", { error: e instanceof ApiError ? e.message : String(e) }));
    } finally {
      setBusy(null);
    }
  }

  const language = i18n.language === "en" ? "en" : "tr";
  return (
    <div className="flex min-h-dvh items-center justify-center p-4">
      <div className="absolute top-4 right-4 flex gap-1">
        <Button variant="ghost" size="icon" onClick={() => setLanguage(language === "tr" ? "en" : "tr")} aria-label={t("nav.language")}>
          <Languages className="h-4 w-4" />
        </Button>
        <Button variant="ghost" size="icon" onClick={toggle} aria-label={t("nav.theme")}>
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>

      <div className="grid w-full max-w-5xl items-center gap-10 lg:grid-cols-2">
        <section className="animate-fade-up hidden lg:block">
          <Logo className="h-14 w-14 drop-shadow-xl" />
          <h1 className="mt-6 text-4xl leading-tight font-bold tracking-tight">
            <span className="gradient-text">{t("app.name")}</span>
          </h1>
          <p className="mt-3 max-w-md text-lg text-slate-600 dark:text-slate-300">{t("app.tagline")}</p>
          <ul className="mt-8 space-y-3">
            {FEATURES.map(({ icon: Icon, ...text }) => (
              <li key={text.en} className="flex items-center gap-3 text-slate-700 dark:text-slate-200">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-200">
                  <Icon className="h-4.5 w-4.5" />
                </span>
                {text[language]}
              </li>
            ))}
          </ul>
          <p className="mt-10 flex items-center gap-2 text-sm text-violet-700/80 dark:text-violet-300/80">
            <Sparkles className="h-4 w-4" />
            {t("app.offline")}
          </p>
        </section>

        <section className="glass animate-fade-up mx-auto w-full max-w-md p-8">
          <div className="mb-6 flex items-center gap-3 lg:hidden">
            <Logo className="h-10 w-10" />
            <span className="gradient-text text-xl font-bold">{t("app.name")}</span>
          </div>
          <h2 className="text-2xl font-semibold">{t("login.title")}</h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">{t("login.subtitle")}</p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            <Field label={t("login.username")} htmlFor="username">
              <Input
                id="username"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoFocus
              />
            </Field>
            <Field label={t("login.password")} htmlFor="password">
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </Field>
            {error && <Notice tone="rose">{error}</Notice>}
            <Button type="submit" className="w-full" loading={busy === "login"}>
              {t("login.submit")}
            </Button>
          </form>

          {guestEnabled && (
            <>
              <div className="my-5 flex items-center gap-3 text-xs text-slate-400">
                <span className="h-px flex-1 bg-violet-200 dark:bg-white/10" />
                {t("login.or")}
                <span className="h-px flex-1 bg-violet-200 dark:bg-white/10" />
              </div>
              <Button variant="secondary" className="w-full" onClick={() => void guest()} loading={busy === "guest"}>
                <UserRound className="h-4 w-4" />
                {t("login.guest")}
              </Button>
              <p className="mt-2 text-center text-xs text-slate-500 dark:text-slate-400">{t("login.guestHint")}</p>
            </>
          )}
        </section>
      </div>
    </div>
  );
}
