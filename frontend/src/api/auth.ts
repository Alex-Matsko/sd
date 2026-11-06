import { apiRequest, getRefreshToken, setTokens } from "./client";
import type { TelegramLinkCode, TokenResponse, User } from "./types";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "/api").replace(/\/+$/, "");

export async function login(email: string, password: string) {
  const body = new URLSearchParams();
  body.set("username", email);
  body.set("password", password);

  const res = await fetch(`${API_BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: body.toString(),
  });

  if (!res.ok) {
    let message = "Неверный email или пароль";
    try {
      const data = await res.json();
      message = data.detail ?? message;
    } catch {
      // ignore body parse failure
    }
    throw new Error(message);
  }

  const data: TokenResponse = await res.json();
  setTokens(data.access_token, data.refresh_token);
  return data;
}

export async function logout() {
  const refreshToken = getRefreshToken();
  setTokens(null, null);
  if (refreshToken) {
    try {
      await fetch(`${API_BASE_URL}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch {
      // best-effort revoke; ignore network failures on logout
    }
  }
}

export async function fetchCurrentUser() {
  return apiRequest<User>("/auth/me");
}

export function requestTelegramLinkCode() {
  return apiRequest<TelegramLinkCode>("/auth/me/telegram-link-code", { method: "POST" });
}

export function unlinkTelegram() {
  return apiRequest<User>("/auth/me/telegram-unlink", { method: "POST" });
}

export function changeOwnPassword(currentPassword: string, newPassword: string) {
  return apiRequest<void>("/auth/me/password", {
    method: "POST",
    body: { current_password: currentPassword, new_password: newPassword },
  });
}
