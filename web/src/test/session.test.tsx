import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { setAccessToken } from "@/api/client";
import { AuthProvider, useAuth } from "@/auth/AuthContext";
import { useConversations } from "@/chat/conversations";

afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
  localStorage.clear();
});

describe("conversations", () => {
  it("reuse the empty conversation, select the next one after a delete, and are busy as a whole", () => {
    const { result } = renderHook(() => useConversations("ayse"));
    const first = result.current.active.id;
    act(() => result.current.create());
    expect(result.current.conversations).toHaveLength(1);

    act(() =>
      result.current.update(first, (c) => ({ ...c, messages: [{ id: "a", role: "assistant", content: "", pending: true }] })),
    );
    act(() => result.current.create());
    const second = result.current.active.id;
    expect(second).not.toBe(first);
    expect(result.current.conversations).toHaveLength(2);
    // The new conversation has no pending answer, but another one is running
    expect(result.current.busy).toBe(true);

    act(() => result.current.select(first));
    act(() => result.current.remove(first));
    expect(result.current.active.id).toBe(second);
    expect(result.current.busy).toBe(false);
  });
});

describe("session", () => {
  it("forgets cached data of the previous user on logout", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) return new Response("{}", { status: 401 });
      if (url.endsWith("/auth/guest")) return new Response(JSON.stringify({ enabled: false }));
      return new Response("{}");
    });
    const queryClient = new QueryClient();
    queryClient.setQueryData(["requests", false, ""], { requests: [{ id: 1, title: "Yöneticinin talebi" }] });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    );
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.ready).toBe(true));
    await act(() => result.current.logout());
    expect(queryClient.getQueryData(["requests", false, ""])).toBeUndefined();
  });
});
