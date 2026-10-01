import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { useAuth } from "@/auth/AuthContext";
import { Layout } from "@/components/Layout";
import { Spinner } from "@/components/ui";
import { useUiSettings } from "@/lib/uiSettings";
import { ChangePasswordPage } from "@/pages/ChangePasswordPage";
import { ChatPage } from "@/pages/ChatPage";
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

export default function App() {
  const { user, ready, isStaff, isGuest } = useAuth();
  // The organization's name and texts, for the login page too
  useUiSettings();
  if (!ready) return <Splash />;
  if (!user) return <LoginPage />;
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
