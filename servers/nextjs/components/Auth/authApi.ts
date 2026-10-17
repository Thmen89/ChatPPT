import { getApiUrl } from "@/utils/api";
import { formatFastApiDetail } from "@/utils/authErrors";

export type AuthStatus = {
  configured: boolean;
  authenticated: boolean;
  username: string | null;
  is_admin?: boolean;
  auth_disabled?: boolean;
  oidc?: { enabled: boolean; label: string };
};

export type ApiToken = {
  id: number;
  user_id: number;
  username: string;
  name: string;
  prefix: string;
  created_at: number;
  last_used_at: number | null;
};

export type AccountUser = {
  id: number;
  username: string;
  is_admin: boolean;
  is_active: boolean;
  source: string;
  has_password: boolean;
  created_at: number;
  last_login_at: number | null;
};

/** JSON call to /api/v1/auth/*; throws an Error carrying FastAPI's `detail`. */
export async function authApi<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const response = await fetch(getApiUrl(`/api/v1/auth${path}`), {
    method: init.method ?? "GET",
    credentials: "include",
    cache: "no-store",
    headers: init.body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
  });
  if (response.status === 204) return undefined as T;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(formatFastApiDetail((payload as { detail?: unknown })?.detail) || `HTTP ${response.status}`);
  }
  return payload as T;
}

export function formatWhen(seconds: number | null): string {
  if (!seconds) return "never";
  return new Date(seconds * 1000).toLocaleString();
}
