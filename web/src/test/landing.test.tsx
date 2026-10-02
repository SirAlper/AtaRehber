import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import App from "@/App";
import { AuthProvider } from "@/auth/AuthContext";
import { ToastProvider } from "@/components/Toast";
import i18n from "@/i18n";
import { isLanding } from "@/lib/activity";
import { createWorld } from "@/lib/cells";
import { stepLava } from "@/lib/lava";

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

function renderApp() {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = String(input);
    if (url.endsWith("/auth/refresh")) return new Response("{}", { status: 401 });
    if (url.endsWith("/auth/guest")) return new Response(JSON.stringify({ enabled: false }));
    return new Response("{}");
  });
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <ToastProvider>
          <AuthProvider>
            <App />
          </AuthProvider>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("landing page", () => {
  it("explains the assistant first, leads to the login page, and can be opened again from there", async () => {
    void i18n.changeLanguage("tr");
    const view = renderApp();
    expect(await screen.findByRole("heading", { name: "AtaRehber nedir?" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Nasıl kullanılır?" })).toBeInTheDocument();
    expect(isLanding()).toBe(true);

    await userEvent.click(screen.getAllByRole("button", { name: "Sohbete başla" })[0]);
    expect(screen.getByRole("heading", { name: "Hoş geldiniz" })).toBeInTheDocument();
    expect(isLanding()).toBe(false);

    // The same browser tab goes straight to the login page after a reload
    view.unmount();
    renderApp();
    expect(await screen.findByRole("heading", { name: "Hoş geldiniz" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "AtaRehber nedir, nasıl kullanılır?" }));
    expect(screen.getByRole("heading", { name: "AtaRehber nedir?" })).toBeInTheDocument();
  });
});

describe("lava lamp", () => {
  it("lets every blob rise and sink through the lamp, slowly, without leaving it", () => {
    let seed = 5;
    const random = () => {
      seed = (seed * 1664525 + 1013904223) % 4294967296;
      return seed / 4294967296;
    };
    const [width, height] = [170, 110];
    const world = createWorld(width, height, random);
    const cells = [...world.cells];
    const lowest = new Map(cells.map((c) => [c, c.y]));
    const highest = new Map(cells.map((c) => [c, c.y]));
    let fastest = 0;
    for (let t = 0; t < 120 * 30; t++) {
      const before = cells.map((c) => [c.x, c.y]);
      stepLava(world, 1 / 30, random);
      cells.forEach((c, i) => {
        fastest = Math.max(fastest, Math.hypot(c.x - before[i][0], c.y - before[i][1]) * 30);
        lowest.set(c, Math.max(lowest.get(c)!, c.y));
        highest.set(c, Math.min(highest.get(c)!, c.y));
        expect(c.x).toBeGreaterThan(-c.r);
        expect(c.x).toBeLessThan(width + c.r);
        expect(c.y).toBeGreaterThan(-c.r);
        expect(c.y).toBeLessThan(height + c.r);
      });
    }
    expect(world.cells).toEqual(cells);
    for (const cell of cells) expect(lowest.get(cell)! - highest.get(cell)!).toBeGreaterThan(height * 0.5);
    // Canvas pixels per second (a canvas pixel is about 8 screen pixels)
    expect(fastest).toBeLessThan(height * 0.08);
  });
});
