// First page a visitor sees: what the assistant is and how to use it, then on to the login page. The backdrop
// turns into a lava lamp while it is shown (src/lib/lava.ts).

import { ArrowRight, BookOpenCheck, Languages, LockKeyhole, Moon, ShieldCheck, Sparkles, Sun } from "lucide-react";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { Logo } from "@/components/Background";
import { Button } from "@/components/ui";
import { setLanguage } from "@/i18n";
import { setLanding } from "@/lib/activity";
import { useTheme } from "@/lib/theme";

const FEATURES = [
  { icon: BookOpenCheck, key: "sources" },
  { icon: ShieldCheck, key: "honest" },
  { icon: LockKeyhole, key: "local" },
] as const;
const STEPS = [1, 2, 3, 4] as const;

export function LandingPage({ onStart }: { onStart: () => void }) {
  const { t, i18n } = useTranslation();
  const { theme, toggle } = useTheme();
  const language = i18n.language === "en" ? "en" : "tr";
  const name = t("app.name");

  useEffect(() => {
    setLanding(true);
    return () => setLanding(false);
  }, []);

  return (
    <div className="mx-auto flex min-h-dvh w-full max-w-5xl flex-col px-4 pb-10">
      <header className="flex items-center justify-between py-4">
        <div className="flex items-center gap-3">
          <Logo className="h-9 w-9" />
          <span className="gradient-text text-lg font-bold">{name}</span>
        </div>
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" onClick={() => setLanguage(language === "tr" ? "en" : "tr")} aria-label={t("nav.language")}>
            <Languages className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" onClick={toggle} aria-label={t("nav.theme")}>
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </header>

      <section className="animate-fade-up flex min-h-[62dvh] flex-col items-center justify-center py-10 text-center">
        <Logo className="h-16 w-16 drop-shadow-xl" />
        <h1 className="mt-6 text-5xl leading-tight font-bold tracking-tight sm:text-6xl">
          <span className="gradient-text">{name}</span>
        </h1>
        <p className="mt-4 max-w-xl text-lg text-slate-600 dark:text-slate-300">{t("app.tagline")}</p>
        <Button className="mt-8 h-12 px-7 text-base" onClick={onStart}>
          {t("landing.start")}
          <ArrowRight className="h-4.5 w-4.5" />
        </Button>
        <p className="mt-6 flex items-center gap-2 text-sm text-violet-700/80 dark:text-violet-300/80">
          <Sparkles className="h-4 w-4" />
          {t("app.offline")}
        </p>
      </section>

      <section className="glass animate-fade-up p-6 sm:p-8">
        <h2 className="text-2xl font-semibold">{t("landing.whatTitle", { name })}</h2>
        <p className="mt-2 max-w-3xl text-slate-600 dark:text-slate-300">{t("landing.whatText", { name })}</p>
        <ul className="mt-6 grid gap-5 sm:grid-cols-3">
          {FEATURES.map(({ icon: Icon, key }) => (
            <li key={key}>
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-200">
                <Icon className="h-5 w-5" />
              </span>
              <h3 className="mt-3 font-semibold">{t(`landing.${key}Title`)}</h3>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t(`landing.${key}Text`)}</p>
            </li>
          ))}
        </ul>
      </section>

      <section className="glass animate-fade-up mt-6 p-6 sm:p-8">
        <h2 className="text-2xl font-semibold">{t("landing.howTitle")}</h2>
        <ol className="mt-6 grid gap-5 sm:grid-cols-2">
          {STEPS.map((step) => (
            <li key={step} className="flex gap-4">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-gradient-to-r from-violet-600 to-fuchsia-600 text-sm font-semibold text-white">
                {step}
              </span>
              <div>
                <h3 className="font-semibold">{t(`landing.step${step}Title`)}</h3>
                <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{t(`landing.step${step}Text`)}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="mt-8 flex flex-col items-center gap-3 text-center">
          <Button onClick={onStart}>
            {t("landing.start")}
            <ArrowRight className="h-4 w-4" />
          </Button>
          <p className="max-w-xl text-xs text-slate-500 dark:text-slate-400">{t("landing.note")}</p>
        </div>
      </section>
    </div>
  );
}
