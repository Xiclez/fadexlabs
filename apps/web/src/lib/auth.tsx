"use client";

import { createContext, type ReactNode, use, useCallback, useEffect, useMemo, useState } from "react";

import { api, refreshAccess, setAccessToken, type User } from "@/lib/api";

type AuthState = {
  user: User | null;
  status: "loading" | "authenticated" | "anonymous";
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
};

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [status, setStatus] = useState<AuthState["status"]>("loading");

  const loadMe = useCallback(async () => {
    try {
      setUser(await api<User>("/auth/me"));
      setStatus("authenticated");
    } catch {
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  // Al cargar: si hay cookie de refresh válida, recupera la sesión sin pedir login.
  useEffect(() => {
    refreshAccess().then((token) => {
      if (token) loadMe();
      else setStatus("anonymous");
    });
  }, [loadMe]);

  // Renueva el access token antes de que venza (10 min) mientras la pestaña esté abierta.
  useEffect(() => {
    if (status !== "authenticated") return;
    const id = setInterval(() => {
      refreshAccess().then((t) => {
        if (!t) {
          setUser(null);
          setStatus("anonymous");
        }
      });
    }, 8 * 60 * 1000);
    return () => clearInterval(id);
  }, [status]);

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await api<{ access_token: string }>("/auth/login", {
      method: "POST",
      json: { email, password },
    });
    setAccessToken(access_token);
    await loadMe();
  }, [loadMe]);

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      setAccessToken(null);
      setUser(null);
      setStatus("anonymous");
    }
  }, []);

  const value = useMemo(() => ({ user, status, login, logout, reload: loadMe }),
    [user, status, login, logout, loadMe]);
  return <AuthContext value={value}>{children}</AuthContext>;
}

export function useAuth(): AuthState {
  const ctx = use(AuthContext);
  if (!ctx) throw new Error("useAuth debe usarse dentro de <AuthProvider>");
  return ctx;
}
