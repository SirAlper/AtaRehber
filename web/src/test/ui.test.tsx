import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { QueryResult, Source } from "@/api/types";
import { EvidenceList, SourcesPanel, VerificationNote } from "@/chat/AnswerParts";
import i18n, { resources } from "@/i18n";

function keys(value: unknown, prefix = ""): string[] {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.entries(value).flatMap(([key, child]) => keys(child, `${prefix}${key}.`));
  }
  return [prefix];
}

const used: Source = {
  source: "YÖNETMELİK.txt",
  chunk_index: 64,
  article: "Madde 30 – Ek süreler",
  reranker_score: 0.99,
  content: "[YÖNETMELİK | Madde 30]\n(2) Son sınıf öğrencilerine iki ek sınav hakkı verilir.",
  evidence: [{ text: "(2) Son sınıf öğrencilerine iki ek sınav hakkı verilir.", citation: "Madde 30/2" }],
  used: true,
};
const other: Source = { source: "YÖNETMELİK.txt", chunk_index: 47, article: "Madde 20 – Sınavlar", content: "Sınav türleri." };

function answer(verification: QueryResult["verification"], sources: Source[] = [used, other]): QueryResult {
  return { answer: "İki.", sources, active_agent: "doc_agent", hallucination_grade: "yes", verification };
}

describe("texts", () => {
  it("exist in Turkish and English with the same keys", () => {
    expect(keys(resources.en.translation).sort()).toEqual(keys(resources.tr.translation).sort());
  });
});

describe("answer parts", () => {
  it("show the evidence with its citation", () => {
    void i18n.changeLanguage("tr");
    render(<EvidenceList sources={[used, other]} />);
    expect(screen.getByText(/Madde 30\/2/)).toBeInTheDocument();
    expect(screen.getByText("“(2) Son sınıf öğrencilerine iki ek sınav hakkı verilir.”")).toBeInTheDocument();
  });

  it("explain each verification level", () => {
    const { rerender } = render(<VerificationNote result={answer({ level: "verified", issues: ["transitional"] })} />);
    expect(screen.getByText("Belgelerle doğrulandı")).toBeInTheDocument();
    expect(screen.getByText(/geçici bir maddeye dayanıyor/)).toBeInTheDocument();
    rerender(<VerificationNote result={answer({ level: "partial", issues: ["partial"] })} />);
    expect(screen.getByText(/Kısmen doğrulandı/)).toBeInTheDocument();
    rerender(<VerificationNote result={answer({ level: "unverified", issues: [] })} />);
    expect(screen.getByText(/İlgili olabilecek bölümler: Madde 30, Madde 20/)).toBeInTheDocument();
  });

  it("list used sources first and show retrieval details to staff only", async () => {
    const { rerender } = render(<SourcesPanel sources={[other, used]} staff={false} />);
    await userEvent.click(screen.getByRole("button", { name: /Kaynaklar \(2\)/ }));
    const items = screen.getAllByRole("listitem").map((item) => item.textContent ?? "");
    expect(items[0]).toContain("Madde 30");
    expect(screen.getByText("İlgili olabilecek diğer bölümler")).toBeInTheDocument();
    expect(screen.queryByText(/parça #/)).not.toBeInTheDocument();
    // The loader's header line is not repeated
    expect(screen.queryByText(/\[YÖNETMELİK/)).not.toBeInTheDocument();
    rerender(<SourcesPanel sources={[other, used]} staff />);
    expect(screen.getByText(/parça #64/)).toBeInTheDocument();
  });
});
