import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, setAccessToken, streamQuery } from "@/api/client";

function streamResponse(chunks: string[], status = 200) {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      controller.close();
    },
  });
  return new Response(body, { status });
}

afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

describe("streamQuery", () => {
  it("passes progress events on and resolves with the final answer, across chunk boundaries", async () => {
    const lines = [
      JSON.stringify({ type: "progress", agent: "doc_agent", stage: "searching" }),
      JSON.stringify({ type: "done", answer: "İki ek sınav hakkı.", sources: [], active_agent: "doc_agent" }),
    ].join("\n");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(streamResponse([lines.slice(0, 30), lines.slice(30) + "\n"]));
    setAccessToken("token");
    const events: string[] = [];
    const result = await streamQuery({ question: "Kaç?" }, (event) => events.push(event.type));
    expect(result.answer).toBe("İki ek sınav hakkı.");
    expect(events).toEqual(["progress"]);
  });

  it("reports a busy server as HTTP 503", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "busy" }), { status: 503 }));
    await expect(streamQuery({ question: "Kaç?" }, () => {})).rejects.toMatchObject({ status: 503 });
  });

  it("treats busy reported inside the stream like HTTP 503", async () => {
    const line = JSON.stringify({ type: "error", code: "busy", message: "The assistant is busy." }) + "\n";
    vi.spyOn(globalThis, "fetch").mockResolvedValue(streamResponse([line]));
    await expect(streamQuery({ question: "Kaç?" }, () => {})).rejects.toMatchObject({ status: 503 });
  });
});

describe("api", () => {
  it("renews the access token from the refresh cookie once and retries", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("{}", { status: 401 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ access_token: "fresh", role: "viewer", username: "u", expires_in: 60 }), {
          status: 200,
        }),
      )
      .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    setAccessToken("expired");
    await expect(api<{ ok: boolean }>("/api/v1/stats")).resolves.toEqual({ ok: true });
    const [refreshUrl, refreshInit] = fetchMock.mock.calls[1];
    expect(refreshUrl).toBe("/api/v1/auth/refresh");
    expect((refreshInit as RequestInit).headers).toMatchObject({ "X-Token-Transport": "cookie" });
    expect(((fetchMock.mock.calls[2][1] as RequestInit).headers as Record<string, string>).Authorization).toBe("Bearer fresh");
  });

  it("throws the API's message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: "Yetkisiz" }), { status: 403 }));
    await expect(api("/api/v1/auth/users")).rejects.toEqual(new ApiError(403, "Yetkisiz"));
  });
});
