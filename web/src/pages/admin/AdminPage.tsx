import { Activity, Bot, FileText, SearchCheck, ServerCog, Users } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { cn } from "@/lib/utils";
import { AgentsTab } from "@/pages/admin/AgentsTab";
import { AuditTab } from "@/pages/admin/AuditTab";
import { DocumentsTab } from "@/pages/admin/DocumentsTab";
import { ReviewTab } from "@/pages/admin/ReviewTab";
import { SystemTab } from "@/pages/admin/SystemTab";
import { UsersTab } from "@/pages/admin/UsersTab";

function Tab({ to, icon, label }: { to: string; icon: ReactNode; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium whitespace-nowrap transition",
          isActive
            ? "bg-white text-violet-800 shadow-sm dark:bg-white/10 dark:text-white"
            : "text-slate-600 hover:text-violet-800 dark:text-slate-300 dark:hover:text-white",
        )
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}

export default function AdminPage() {
  const { t } = useTranslation();
  const { isAdmin } = useAuth();
  return (
    <div className="h-full overflow-y-auto p-2 sm:p-4">
      <div className="mx-auto max-w-6xl">
        <h1 className="mb-3 text-2xl font-semibold">
          <span className="gradient-text">{t("admin.title")}</span>
        </h1>
        <nav className="glass mb-4 flex gap-1 overflow-x-auto p-1.5" aria-label={t("admin.title")}>
          <Tab to="/admin/documents" icon={<FileText className="h-4 w-4" />} label={t("admin.documents")} />
          {isAdmin && (
            <>
              <Tab to="/admin/users" icon={<Users className="h-4 w-4" />} label={t("admin.users")} />
              <Tab to="/admin/agents" icon={<Bot className="h-4 w-4" />} label={t("admin.agents")} />
              <Tab to="/admin/review" icon={<SearchCheck className="h-4 w-4" />} label={t("admin.review")} />
              <Tab to="/admin/audit" icon={<Activity className="h-4 w-4" />} label={t("admin.audit")} />
              <Tab to="/admin/system" icon={<ServerCog className="h-4 w-4" />} label={t("admin.system")} />
            </>
          )}
        </nav>
        <Routes>
          <Route index element={<Navigate to="/admin/documents" replace />} />
          <Route path="documents" element={<DocumentsTab />} />
          {isAdmin && (
            <>
              <Route path="users" element={<UsersTab />} />
              <Route path="agents" element={<AgentsTab />} />
              <Route path="review" element={<ReviewTab />} />
              <Route path="audit" element={<AuditTab />} />
              <Route path="system" element={<SystemTab />} />
            </>
          )}
          <Route path="*" element={<Navigate to="/admin/documents" replace />} />
        </Routes>
      </div>
    </div>
  );
}
