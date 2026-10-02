import { lazy, Suspense, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Layout } from "@/components/Layout";
import { Spinner } from "@/components/ui";
import { useUiSettings } from "@/lib/uiSettings";
import { ChangePasswordPage } from "@/pages/ChangePasswordPage";
import { ChatPage } from "@/pages/ChatPage";
import { LandingPage } from "@/pages/LandingPage";
import { LoginPage } from "@/pages/LoginPage";

// Pages most users never open are loaded on demand
const RequestsPage = lazy(() => import("@/pages/RequestsPage"));
const AdminPage = lazy(() => import("@/pages/admin/AdminPage"));

function Splash() {
  return (
    <div className="flex h-dvh items-center justify-center">
      <Spinner className="h-8 w-8" />
    </div>
  );
}

// Visitors see the landing page once per browser tab, then the login page
const LANDING_SEEN_KEY = "landing-seen";

function landingSeen() {
  try {
    return sessionStorage.getItem(LANDING_SEEN_KEY) === "1";
  } catch {
    return false;
  }
}

export default function App() {
  const { user, ready, isStaff, isGuest } = useAuth();
  const [entered, setEntered] = useState(landingSeen);
  // The organization's name and texts, for the landing and login pages too
  useUiSettings();

  function enter(value: boolean) {
    setEntered(value);
    try {
      if (value) sessionStorage.setItem(LANDING_SEEN_KEY, "1");
      else sessionStorage.removeItem(LANDING_SEEN_KEY);
    } catch {
      // The landing page then shows again after a reload
    }
  }

  if (!ready) return <Splash />;
  if (!user) return entered ? <LoginPage onAbout={() => enter(false)} /> : <LandingPage onStart={() => enter(true)} />;
  if (user.must_change_password) return <ChangePasswordPage />;

  return (
    <Suspense fallback={<Splash />}>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<ChatPage />} />
          {!isGuest && <Route path="requests" element={<RequestsPage />} />}
          {isStaff && <Route path="admin/*" element={<AdminPage />} />}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
