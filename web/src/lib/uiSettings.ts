// Texts the organization set under Admin > Appearance. They replace the built-in texts in the i18n bundles, so
// every t("chat.suggestions") etc. shows them without knowing about the settings.

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import { api } from "@/api/client";
import type { UiSettings, UiTexts } from "@/api/types";
import i18n, { builtInBundles, hasStoredLanguage } from "@/i18n";

const LANGUAGES = ["tr", "en"] as const;

// Translation key ("section.name") each text replaces
export const TEXT_KEYS: Record<Exclude<keyof UiTexts, "suggestions">, [string, string]> = {
  welcome: ["chat", "welcomeText"],
  welcome_guest: ["chat", "welcomeGuest"],
  disclaimer: ["chat", "disclaimer"],
  request_example: ["chat", "requestSuggestion"],
  unit_label: ["users", "unit"],
  program_label: ["users", "program"],
  level_label: ["users", "level"],
};

type Bundle = Record<string, Record<string, unknown>>;

/** The built-in bundle of a language (a copy). */
export function builtInTexts(language: "tr" | "en"): Bundle {
  return JSON.parse(JSON.stringify(builtInBundles[language])) as Bundle;
}

/** Built bundles replace the previous ones, so a text the admin cleared falls back to the built-in one. */
export function applyUiSettings(settings: UiSettings) {
  for (const language of LANGUAGES) {
    const bundle = builtInTexts(language);
    const texts = settings.texts?.[language];
    if (settings.app_name) bundle.app.name = settings.app_name;
    if (texts) {
      for (const [field, [section, key]] of Object.entries(TEXT_KEYS)) {
        const value = texts[field as keyof typeof TEXT_KEYS];
        if (value) bundle[section][key] = value;
      }
      if (texts.suggestions?.length) bundle.chat.suggestions = texts.suggestions;
    }
    i18n.addResourceBundle(language, "translation", bundle, false, true);
  }
  if (settings.default_language && !hasStoredLanguage() && settings.default_language !== i18n.language) {
    void i18n.changeLanguage(settings.default_language);
    document.documentElement.lang = settings.default_language;
  }
  document.title = i18n.t("app.name");
}

/** Loads the organization's texts once per page view (also before login: the login page shows the name). */
export function useUiSettings() {
  const settings = useQuery({
    queryKey: ["ui-settings"],
    queryFn: () => api<UiSettings>("/api/v1/ui-settings"),
    staleTime: Infinity,
  });
  useEffect(() => {
    if (settings.data) applyUiSettings(settings.data);
  }, [settings.data]);
}
