import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useTranslation } from "react-i18next";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, setAccessToken, streamQuery } from "@/api/client";
import type { UiSettings, UiTexts } from "@/api/types";
import { ToastProvider } from "@/components/Toast";
import i18n from "@/i18n";
import { applyUiSettings } from "@/lib/uiSettings";
import { AppearanceTab } from "@/pages/admin/AppearanceTab";

const EMPTY: UiTexts = {
  welcome: "",
  welcome_guest: "",
  disclaimer: "",
  request_example: "",
  unit_label: "",
  program_label: "",
  level_label: "",
  suggestions: [],
};

function settings(extra: Partial<UiSettings> = {}, tr: Partial<UiTexts> = {}): UiSettings {
  return { app_name: "", texts: { tr: { ...EMPTY, ...tr }, en: EMPTY }, ...extra };
}

afterEach(() => {
  applyUiSettings(settings());
  void i18n.changeLanguage("tr");
  localStorage.clear();
  vi.restoreAllMocks();
  setAccessToken(null);
});

function Probe() {
  const { t } = useTranslation();
  return (
    <>
      <h1>{t("app.name")}</h1>
      <ul>
        {(t("chat.suggestions", { returnObjects: true }) as string[]).map((s) => (
          <li key={s}>{s}</li>
        ))}
      </ul>
    </>
  );
}

describe("organization texts", () => {
  it("replace the built-in ones on screen and come back when cleared", () => {
    void i18n.changeLanguage("tr");
    render(<Probe />);
    expect(screen.getByRole("heading")).toHaveTextContent("OpenLocal Asistan");

    act(() => applyUiSettings(settings({ app_name: "AtaRehber" }, { suggestions: ["Burs ne zaman yatar?"] })));
    expect(screen.getByRole("heading")).toHaveTextContent("AtaRehber");
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["Burs ne zaman yatar?"]);
    expect(document.title).toBe("AtaRehber");

    act(() => applyUiSettings(settings()));
    expect(screen.getByRole("heading")).toHaveTextContent("OpenLocal Asistan");
    expect(screen.getAllByRole("listitem")).toHaveLength(3);
  });

  it("set the language only for users who did not pick one", () => {
    void i18n.changeLanguage("tr");
    applyUiSettings(settings({ default_language: "en" }));
    expect(i18n.language).toBe("en");

    void i18n.changeLanguage("tr");
    localStorage.setItem("olr.language", "tr");
    applyUiSettings(settings({ default_language: "en" }));
    expect(i18n.language).toBe("tr");
  });
});

describe("language model outage", () => {
  it("is told apart from a busy assistant", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "The language model is not available right now." }), {
        status: 503,
        headers: { "X-Error-Code": "llm_unavailable" },
      }),
    );
    const error = await streamQuery({ question: "İzin?" }, () => {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("llm_unavailable");
    expect(i18n.t("chat.llmUnavailable", { lng: "tr" })).toMatch(/Dil modeli şu anda çalışmıyor/);
  });
});

describe("appearance tab", () => {
  it("shows the built-in texts as hints and saves the admin's texts", async () => {
    void i18n.changeLanguage("tr");
    const saved: unknown[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "PUT") {
        saved.push(JSON.parse(String(init.body)));
        return new Response(JSON.stringify(settings()));
      }
      return new Response(JSON.stringify(settings({ updated_by: "admin", updated_at: "2026-10-01T09:00:00Z" })));
    });
    setAccessToken("token");
    render(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <AppearanceTab />
        </ToastProvider>
      </QueryClientProvider>,
    );

    const name = await screen.findByLabelText("Asistanın adı");
    expect(name).toHaveAttribute("placeholder", "OpenLocal Asistan");
    expect(screen.getByLabelText("Örnek sorular").getAttribute("placeholder")).toContain("Yıllık izin hakkı kaç gündür?");
    expect(screen.getByText(/Son değişiklik: admin/)).toBeInTheDocument();

    await userEvent.type(name, "AtaRehber");
    await userEvent.type(screen.getByLabelText("Örnek sorular"), "Burs ne zaman yatar?{Enter}{Enter}Yurt ücreti?");
    await userEvent.type(screen.getByLabelText("Birim alanı"), "Fakülte");
    await userEvent.click(screen.getByRole("button", { name: "Kaydet" }));

    await waitFor(() => expect(saved).toHaveLength(1));
    const body = saved[0] as UiSettings;
    expect(body.app_name).toBe("AtaRehber");
    expect(body.texts.tr.suggestions).toEqual(["Burs ne zaman yatar?", "Yurt ücreti?"]);
    expect(body.texts.tr.unit_label).toBe("Fakülte");
    expect(body.texts.en.suggestions).toEqual([]);
  });
});
