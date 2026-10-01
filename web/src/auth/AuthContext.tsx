import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, authHeaders, onAuthLost, refreshSession, setAccessToken } from "@/api/client";
import type { Role, TokenResponse, UserProfile } from "@/api/types";

interface AuthValue {
  user: UserProfile | null;
  /** False until the first session check (refresh cookie) is done */
  ready: boolean;
  guestEnabled: boolean;
  login: (username: string, password: string) => Promise<void>;
  startGuest: () => Promise<void>;
  logout: () => Promise<void>;
  changePassword: (current: string, next: string) => Promise<void>;
  isStaff: boolean;
  isAdmin: boolean;
  isGuest: boolean;
}

const AuthContext = createContext<AuthValue | null>(null);

async function loadProfile(tokens: TokenResponse): Promise<UserProfile> {
  setAccessToken(tokens.access_token);
  if (tokens.role === "guest") return { username: tokens.username, role: "guest", groups: [] };
  const profile = await api<UserProfile>("/api/v1/auth/me");
  return { ...profile, must_change_password: tokens.must_change_password ?? profile.must_change_password };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [ready, setReady] = useState(false);
  const [guestEnabled, setGuestEnabled] = useState(false);
  const queryClient = useQueryClient();

  // Cached answers belong to the user who loaded them: the next person in this tab must not see them
  const switchUser = useCallback(
    (next: UserProfile | null) => {
      queryClient.clear();
      setUser(next);
    },
    [queryClient],
  );

  useEffect(() => {
    onAuthLost(() => switchUser(null));
    (async () => {
      const tokens = await refreshSession();
      if (tokens) {
        try {
          setUser(await loadProfile(tokens));
        } catch {
          setAccessToken(null);
        }
      }
      try {
        const status = await api<{ enabled: boolean }>("/api/v1/auth/guest");
        setGuestEnabled(status.enabled);
      } catch {
        setGuestEnabled(false);
      }
      setReady(true);
    })();
    return () => onAuthLost(null);
  }, [switchUser]);

  const login = useCallback(async (username: string, password: string) => {
    const tokens = await api<TokenResponse>("/api/v1/auth/login", {
      json: { username, password },
      cookie: true,
    });
    switchUser(await loadProfile(tokens));
  }, [switchUser]);

  const startGuest = useCallback(async () => {
    const tokens = await api<TokenResponse>("/api/v1/auth/guest", { method: "POST" });
    switchUser(await loadProfile(tokens));
  }, [switchUser]);

  const logout = useCallback(async () => {
    try {
      await fetch("/api/v1/auth/logout", { method: "POST", headers: authHeaders, credentials: "same-origin" });
    } finally {
      setAccessToken(null);
      switchUser(null);
    }
  }, [switchUser]);

  const changePassword = useCallback(async (current: string, next: string) => {
    const tokens = await api<TokenResponse>("/api/v1/auth/change-password", {
      json: { current_password: current, new_password: next },
      cookie: true,
    });
    setUser(await loadProfile(tokens));
  }, []);

  const value = useMemo<AuthValue>(() => {
    const role: Role | undefined = user?.role;
    return {
      user,
      ready,
      guestEnabled,
      login,
      startGuest,
      logout,
      changePassword,
      isStaff: role === "admin" || role === "editor",
      isAdmin: role === "admin",
      isGuest: role === "guest",
    };
  }, [user, ready, guestEnabled, login, startGuest, logout, changePassword]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth outside AuthProvider");
  return value;
}
