const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8001";
const TOKEN_KEY = "teampulse_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const response = await fetch(`${BASE_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
  });

  if (response.status === 401) {
    setToken(null);
    throw new ApiError("Your session expired. Sign in again.", 401);
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(body.detail ?? `Request failed (${response.status})`, response.status);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => request<T>(path, { method: "DELETE" }),
};

export interface User {
  id: string;
  org_id: string;
  email: string;
  name: string;
  role: string;
  timezone: string | null;
}

export interface TeamOverview {
  team_id: string;
  team_name: string;
  toil_score: number;
  toil_score_previous: number;
  trend: "up" | "down" | "flat";
  pages_total: number;
  after_hours_page_rate: number;
  change_failure_rate: number;
  deploy_frequency_per_week: number;
}

export interface OrgOverview {
  week_start: string;
  teams: TeamOverview[];
}

export interface TrendPoint {
  period_start: string;
  value: number;
}

export interface MetricSeries {
  metric_key: string;
  points: TrendPoint[];
}

export interface MemberLoad {
  user_id: string;
  name: string;
  email: string;
  pages_total: number;
  pages_after_hours: number;
  after_hours_page_rate: number;
  on_call_hours: number;
}

export interface TeamDetail {
  team_id: string;
  team_name: string;
  days: number;
  totals: Record<string, number>;
  series: MetricSeries[];
  members: MemberLoad[];
}

export interface PersonDetail {
  user_id: string;
  name: string;
  email: string;
  days: number;
  totals: Record<string, number>;
  series: MetricSeries[];
}

export interface Integration {
  id: string;
  provider: string;
  display_name: string;
  status: string;
  config: Record<string, unknown>;
  last_synced_at: string | null;
  last_error: string | null;
}

export interface Team {
  id: string;
  name: string;
  slug: string;
  timezone: string | null;
}
