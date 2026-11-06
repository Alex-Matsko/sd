import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { fetchCurrentUser, login as loginRequest, logout as logoutRequest } from "../api/auth";
import { useQueryClient } from "@tanstack/react-query";
import { getAccessToken } from "../api/client";
import type { User } from "../api/types";

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    if (!getAccessToken()) {
      setIsLoading(false);
      return;
    }
    fetchCurrentUser()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => {
    function endSession() {
      setUser(null);
      queryClient.clear();
    }
    window.addEventListener("sd:session-ended", endSession);
    return () => window.removeEventListener("sd:session-ended", endSession);
  }, [queryClient]);

  async function login(email: string, password: string) {
    await queryClient.cancelQueries();
    queryClient.clear();
    await loginRequest(email.trim(), password);
    const me = await fetchCurrentUser();
    setUser(me);
  }

  async function logout() {
    setUser(null);
    queryClient.clear();
    await logoutRequest();
  }

  return <AuthContext.Provider value={{ user, isLoading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
