import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import i18n from "@/i18n";
import AdminPage from "@/pages/admin/AdminPage";

vi.mock("@/auth/AuthContext", () => ({ useAuth: () => ({ isAdmin: true, isStaff: true }) }));
// The tabs themselves load data; only the navigation between them is tested here
vi.mock("@/pages/admin/DocumentsTab", () => ({ DocumentsTab: () => <p>DocumentsTab</p> }));
vi.mock("@/pages/admin/UsersTab", () => ({ UsersTab: () => <p>UsersTab</p> }));
vi.mock("@/pages/admin/AgentsTab", () => ({ AgentsTab: () => <p>AgentsTab</p> }));
vi.mock("@/pages/admin/ReviewTab", () => ({ ReviewTab: () => <p>ReviewTab</p> }));
vi.mock("@/pages/admin/StatsTab", () => ({ StatsTab: () => <p>StatsTab</p> }));
vi.mock("@/pages/admin/AuditTab", () => ({ AuditTab: () => <p>AuditTab</p> }));
vi.mock("@/pages/admin/SystemTab", () => ({ SystemTab: () => <p>SystemTab</p> }));
vi.mock("@/pages/admin/AppearanceTab", () => ({ AppearanceTab: () => <p>AppearanceTab</p> }));

function Location() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

function renderAt(path: string) {
  void i18n.changeLanguage("tr");
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="admin/*" element={<AdminPage />} />
      </Routes>
      <Location />
    </MemoryRouter>,
  );
}

describe("admin tabs", () => {
  it("go to the tab instead of adding it to the current address", async () => {
    renderAt("/admin/agents");
    await userEvent.click(screen.getByRole("link", { name: "Belgeler" }));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/admin\/documents$/);
    await userEvent.click(screen.getByRole("link", { name: "Özel Ajanlar" }));
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/admin\/agents$/);
  });

  it("send an unknown address to the documents tab once", () => {
    renderAt("/admin/agents/documents/documents");
    expect(screen.getByTestId("location")).toHaveTextContent(/^\/admin\/documents$/);
  });
});
