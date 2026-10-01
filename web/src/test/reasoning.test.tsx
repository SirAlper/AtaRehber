import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "@/api/client";
import type { QueryResult } from "@/api/types";
import { VerificationNote } from "@/chat/AnswerParts";
import type { ChatMessage } from "@/chat/conversations";
import { NoticeBell } from "@/components/NoticeBell";
import i18n from "@/i18n";
import { AssistantMessage } from "@/pages/ChatPage";

afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

function result(extra: Partial<QueryResult>): QueryResult {
  return { answer: "a", sources: [], active_agent: "doc_agent", ...extra };
}

function withQueries(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

describe("verification notes", () => {
  it("tell that an unanswered question went to staff and that data answers come from the database", () => {
    void i18n.changeLanguage("tr");
    const { rerender } = render(<VerificationNote result={result({ verification: { level: "unverified", issues: ["not_found"] } })} />);
    expect(screen.getByText(/personelin inceleme listesine eklendi/)).toBeInTheDocument();
    rerender(<VerificationNote result={result({ verification: { level: "verified", issues: ["data"] } })} />);
    expect(screen.getByText("Veritabanı sonucuyla doğrulandı")).toBeInTheDocument();
  });
});

describe("questions back", () => {
  const message: ChatMessage = {
    id: "m1",
    role: "assistant",
    content: "",
    result: result({
      answer: "Hangi izin?\n\n- Yıllık\n- Mazeret",
      clarification: { question: "Hangi izin?", options: ["Yıllık", "Mazeret"] },
    }),
  };

  it("show the options as buttons that answer the question", async () => {
    const onPick = vi.fn();
    render(<AssistantMessage message={message} staff={false} onFeedback={() => {}} onPick={onPick} />);
    expect(screen.getByText("Hangi izin?")).toBeInTheDocument();
    // The options are buttons, not also a Markdown list
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Mazeret" }));
    expect(onPick).toHaveBeenCalledWith("Mazeret");
  });

  it("cannot be answered from an older message", () => {
    render(<AssistantMessage message={message} staff={false} onFeedback={() => {}} />);
    expect(screen.getByRole("button", { name: "Yıllık" })).toBeDisabled();
  });
});

describe("notice bell", () => {
  it("counts staff answers and marks one as seen", async () => {
    void i18n.changeLanguage("tr");
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input).endsWith("/seen")) return new Response(JSON.stringify({ marked: 1 }));
      const answers = [{ id: "f1", question: "Yemekhane kaçta?", answer: "**11.30**", updated_at: "2026-10-01T09:00:00Z" }];
      return new Response(JSON.stringify({ answers: init?.method === "POST" ? [] : answers }));
    });
    setAccessToken("token");
    render(withQueries(<NoticeBell />));
    const bell = screen.getByRole("button", { name: "Sorularınıza gelen cevaplar" });
    await waitFor(() => expect(bell).toHaveTextContent("1"));
    await userEvent.click(bell);
    expect(screen.getByText("Yemekhane kaçta?")).toBeInTheDocument();
    // jsdom has no showModal(), so the dialog counts as hidden there
    await userEvent.click(screen.getByRole("button", { name: "Okudum", hidden: true }));
    const seen = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/api/v1/faq/answers/seen"));
    expect(JSON.parse(String(seen?.[1]?.body))).toEqual({ ids: ["f1"] });
  });
});
