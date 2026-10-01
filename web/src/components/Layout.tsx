import { ClipboardList, Languages, LogOut, MessagesSquare, Moon, Settings2, Sun } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Logo } from "@/components/Background";
import { NoticeBell } from "@/components/NoticeBell";
import { Badge, Button } from "@/components/ui";
import { setLanguage } from "@/i18n";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

function NavItem({ to, icon, label, end }: { to: string; icon: ReactNode; label: string; end?: boolean }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition",
          isActive
            ? "bg-gradient-to-r from-violet-600/90 to-fuchsia-600/90 text-white shadow-md shadow-violet-600/20"
            : "text-slate-600 hover:bg-violet-100/70 hover:text-violet-800 dark:text-slate-300 dark:hover:bg-white/10 dark:hover:text-white",
        )
      }
    >
      {icon}
      <span className="hidden sm:inline">{label}</span>
    </NavLink>
  );
}

export function Layout() {
  const { t, i18n } = useTranslation();
  const { user, logout, isStaff, isGuest } = useAuth();
  const { theme, toggle } = useTheme();

  return (
    <div className="flex h-dvh flex-col">
      <header className="glass relative z-10 mx-2 mt-2 flex items-center gap-2 rounded-2xl px-3 py-2 sm:mx-4 sm:mt-3 sm:px-4">
        <div className="mr-2 flex items-center gap-2.5">
          <Logo className="h-8 w-8 drop-shadow-md" />
          <span className="gradient-text hidden text-lg font-bold tracking-tight md:inline">{t("app.name")}</span>
        </div>
        <nav className="flex items-center gap-1" aria-label="main">
          <NavItem to="/" end icon={<MessagesSquare className="h-4 w-4" />} label={t("nav.chat")} />
          {!isGuest && (
            <NavItem to="/requests" icon={<ClipboardList className="h-4 w-4" />} label={t("nav.requests")} />
          )}
          {isStaff && <NavItem to="/admin" icon={<Settings2 className="h-4 w-4" />} label={t("nav.admin")} />}
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <div className="mr-2 hidden items-center gap-2 lg:flex">
            {/* A guest's name says no more than the badge */}
            {!isGuest && <span className="text-sm text-slate-600 dark:text-slate-300">{user?.username}</span>}
            <Badge>{t(`roles.${user?.role ?? "viewer"}`)}</Badge>
          </div>
          {/* Guests have no account to receive answers later */}
          {!isGuest && <NoticeBell />}
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setLanguage(i18n.language === "tr" ? "en" : "tr")}
            aria-label={t("nav.language")}
            title={t("nav.language")}
          >
            <Languages className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="icon" onClick={toggle} aria-label={t("nav.theme")} title={t("nav.theme")}>
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => void logout()}
            aria-label={isGuest ? t("nav.endGuest") : t("nav.logout")}
            title={isGuest ? t("nav.endGuest") : t("nav.logout")}
          >
            <LogOut className="h-4 w-4" />
          </Button>
        </div>
      </header>
      <main className="min-h-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}
