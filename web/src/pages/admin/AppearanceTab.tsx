import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Palette } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { api } from "@/api/client";
import type { UiSettings, UiTexts } from "@/api/types";
import { useToast } from "@/components/Toast";
import { Button, Card, CardTitle, Field, Input, Select, Spinner, Textarea } from "@/components/ui";
import { builtInTexts, TEXT_KEYS } from "@/lib/uiSettings";
import { formatDate } from "@/lib/utils";

type Language = "tr" | "en";
type TextField = keyof typeof TEXT_KEYS;

const MAX_SUGGESTIONS = 6;
const EMPTY_TEXTS: UiTexts = {
  welcome: "",
  welcome_guest: "",
  disclaimer: "",
  request_example: "",
  unit_label: "",
  program_label: "",
  level_label: "",
  suggestions: [],
};
// Longest accepted length per field (as in src/services/ui_settings.py)
const LIMITS: Record<TextField, number> = {
  welcome: 300,
  welcome_guest: 300,
  disclaimer: 300,
  request_example: 150,
  unit_label: 60,
  program_label: 60,
  level_label: 60,
};
const LABELS: Record<TextField, string> = {
  welcome: "appearance.welcome",
  welcome_guest: "appearance.welcomeGuest",
  disclaimer: "appearance.disclaimer",
  request_example: "appearance.requestExample",
  unit_label: "appearance.unitLabel",
  program_label: "appearance.programLabel",
  level_label: "appearance.levelLabel",
};

/** The assistant's name and the texts users see, per language; empty fields keep the built-in texts. */
export function AppearanceTab() {
  const { t, i18n } = useTranslation();
  const toast = useToast();
  const queryClient = useQueryClient();
  const stored = useQuery({
    queryKey: ["ui-settings-admin"],
    queryFn: () => api<UiSettings>("/api/v1/admin/ui-settings"),
  });
  const [language, setLanguage] = useState<Language>(i18n.language === "en" ? "en" : "tr");
  const [appName, setAppName] = useState("");
  const [texts, setTexts] = useState<Record<Language, UiTexts>>({ tr: EMPTY_TEXTS, en: EMPTY_TEXTS });
  // The suggestions are edited as lines; kept apart so that typing a new line is not undone at once
  const [suggestionLines, setSuggestionLines] = useState<Record<Language, string>>({ tr: "", en: "" });

  useEffect(() => {
    if (!stored.data) return;
    setAppName(stored.data.app_name);
    setTexts({ tr: { ...EMPTY_TEXTS, ...stored.data.texts.tr }, en: { ...EMPTY_TEXTS, ...stored.data.texts.en } });
    setSuggestionLines({
      tr: stored.data.texts.tr.suggestions.join("\n"),
      en: stored.data.texts.en.suggestions.join("\n"),
    });
  }, [stored.data]);

  const save = useMutation({
    mutationFn: () => {
      const lines = (language: Language) =>
        suggestionLines[language]
          .split("\n")
          .map((line) => line.trim())
          .filter(Boolean)
          .slice(0, MAX_SUGGESTIONS);
      return api<UiSettings>("/api/v1/admin/ui-settings", {
        method: "PUT",
        json: {
          app_name: appName.trim(),
          texts: { tr: { ...texts.tr, suggestions: lines("tr") }, en: { ...texts.en, suggestions: lines("en") } },
        },
      });
    },
    onSuccess: () => {
      toast(t("appearance.saved"));
      void queryClient.invalidateQueries({ queryKey: ["ui-settings-admin"] });
      void queryClient.invalidateQueries({ queryKey: ["ui-settings"] });
    },
    onError: (e) => toast(t("common.error", { error: (e as Error).message }), "error"),
  });

  if (stored.isLoading) return <Spinner />;

  const defaults = builtInTexts(language);
  const placeholder = (field: TextField) => String(defaults[TEXT_KEYS[field][0]][TEXT_KEYS[field][1]] ?? "");
  const setText = (field: TextField, value: string) =>
    setTexts((current) => ({ ...current, [language]: { ...current[language], [field]: value } }));
  const textInput = (field: TextField, long = false) => {
    const props = {
      id: `appearance-${field}`,
      value: texts[language][field],
      placeholder: placeholder(field),
      maxLength: LIMITS[field],
    };
    return (
      <Field label={t(LABELS[field])} htmlFor={props.id}>
        {long ? (
          <Textarea {...props} className="min-h-16" onChange={(e) => setText(field, e.target.value)} />
        ) : (
          <Input {...props} onChange={(e) => setText(field, e.target.value)} />
        )}
      </Field>
    );
  };

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <Card>
      <CardTitle
        icon={<Palette className="h-4 w-4" />}
        action={
          <Select
            value={language}
            onChange={(e) => setLanguage(e.target.value as Language)}
            className="h-9 w-32 text-xs"
            aria-label={t("appearance.language")}
          >
            <option value="tr">Türkçe</option>
            <option value="en">English</option>
          </Select>
        }
      >
        {t("appearance.title")}
      </CardTitle>
      <p className="mb-4 text-sm text-slate-600 dark:text-slate-300">{t("appearance.subtitle")}</p>
      <form onSubmit={submit} className="space-y-4">
        <Field label={t("appearance.appName")} htmlFor="appearance-name">
          <Input
            id="appearance-name"
            value={appName}
            onChange={(e) => setAppName(e.target.value)}
            placeholder={String(defaults.app.name)}
            maxLength={40}
          />
        </Field>
        {textInput("welcome", true)}
        {textInput("welcome_guest", true)}
        <Field label={t("appearance.suggestions")} hint={t("appearance.suggestionsHint")} htmlFor="appearance-suggestions">
          <Textarea
            id="appearance-suggestions"
            value={suggestionLines[language]}
            onChange={(e) => setSuggestionLines((current) => ({ ...current, [language]: e.target.value }))}
            placeholder={(defaults.chat.suggestions as string[]).join("\n")}
            rows={4}
          />
        </Field>
        {textInput("request_example")}
        {textInput("disclaimer", true)}
        <fieldset className="space-y-2">
          <legend className="mb-1.5 text-sm font-medium text-slate-700 dark:text-slate-200">{t("appearance.profileLabels")}</legend>
          <div className="grid gap-3 sm:grid-cols-3">
            {textInput("unit_label")}
            {textInput("program_label")}
            {textInput("level_label")}
          </div>
        </fieldset>
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" loading={save.isPending}>
            {t("common.save")}
          </Button>
          {stored.data?.updated_by && (
            <span className="text-xs text-slate-500 dark:text-slate-400">
              {t("appearance.updated", {
                name: stored.data.updated_by,
                date: formatDate(stored.data.updated_at, i18n.language),
              })}
            </span>
          )}
        </div>
      </form>
    </Card>
  );
}
