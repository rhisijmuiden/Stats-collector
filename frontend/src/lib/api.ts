let csrfToken = "";

export function setCsrf(token: string) {
  csrfToken = token;
}

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  let payload: BodyInit | undefined;
  if (body instanceof FormData) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T,>(url: string) => request<T>("GET", url),
  post: <T,>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  put: <T,>(url: string, body: unknown) => request<T>("PUT", url, body),
  patch: <T,>(url: string, body: unknown) => request<T>("PATCH", url, body),
  del: <T,>(url: string) => request<T>("DELETE", url),
};

export type Role = "admin" | "editor_in_chief" | "editor" | "staff";

export interface User {
  id: number;
  email: string;
  display_name: string;
  role: Role;
  auth_provider: string;
  language: "en" | "nl";
  theme: "system" | "light" | "dark";
  is_active: boolean;
  totp_enabled: boolean;
  created_at: string | null;
  last_login_at: string | null;
}

export interface Job {
  id: number;
  kind: string;
  params: Record<string, unknown>;
  status: "queued" | "running" | "succeeded" | "failed" | "unknown";
  result: Record<string, unknown>;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  log?: string;
}

export type NoteSection = "added" | "changed" | "removed" | "fixed";

export interface Release {
  version: string;
  tag: string;
  channel: "production" | "test";
  name: string;
  published_at: string | null;
  url: string;
  notes: Record<string, Record<NoteSection, string[]>>;
  asset_url: string | null;
}
