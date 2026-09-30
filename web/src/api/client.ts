// HTTP client for the backend. The access token lives only in memory; the refresh token is an HttpOnly cookie
// the browser sends to /api/v1/auth (the API sets it because every auth call carries "X-Token-Transport: cookie"),
// so no script on the page can read either token from storage.

import type { QueryResult, StreamEvent, TokenResponse } from "./types";

const COOKIE_TRANSPORT = { "X-Token-Transport": "cookie" };

let accessToken: string | null = null;
let authLostHandler: (() => void) | null = null;
let refreshing: Promise<TokenResponse | null> | null = null;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function setAccessToken(token: string | null) {
  accessToken = token;
}

export function hasAccessToken() {
  return accessToken !== null;
}

/** Called when the session cannot be renewed (the UI goes back to the login page). */
export function onAuthLost(handler: (() => void) | null) {
  authLostHandler = handler;
}

async function detail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) return body.detail.map((e: { msg: string }) => e.msg).join("; ");
    return body.message ?? response.statusText;
  } catch {
    return response.statusText;
  }
}

/** New access token from the refresh cookie; concurrent callers share one request. */
export function refreshSession(): Promise<TokenResponse | null> {
  refreshing ??= (async () => {
    try {
      const response = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        headers: COOKIE_TRANSPORT,
        credentials: "same-origin",
      });
      if (!response.ok) return null;
      const tokens: TokenResponse = await response.json();
      accessToken = tokens.access_token;
      return tokens;
    } catch {
      return null;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  json?: unknown;
  form?: FormData;
  query?: Record<string, string | number | boolean | undefined>;
  /** Auth calls: the API sets or clears the refresh cookie */
  cookie?: boolean;
}

function url(path: string, query?: RequestOptions["query"]) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== "") params.set(key, String(value));
  }
  const search = params.toString();
  return search ? `${path}?${search}` : path;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = options.cookie ? { ...COOKIE_TRANSPORT } : {};
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  let body: BodyInit | undefined;
  if (options.form) body = options.form;
  else if (options.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.json);
  }
  return fetch(url(path, options.query), {
    method: options.method ?? (body ? "POST" : "GET"),
    headers,
    body,
    credentials: "same-origin",
  });
}

/** JSON request; renews the access token once on HTTP 401. Throws ApiError with the API's message. */
export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response = await send(path, options);
  if (response.status === 401 && accessToken && (await refreshSession())) {
    response = await send(path, options);
  }
  if (response.status === 401 && accessToken) {
    accessToken = null;
    authLostHandler?.();
  }
  if (!response.ok) throw new ApiError(response.status, await detail(response));
  return (await response.json()) as T;
}

export const authHeaders = COOKIE_TRANSPORT;

/**
 * Ask through /api/v1/query-stream: events (stages, the chosen agent) go to onEvent while the answer is prepared;
 * resolves with the final result. HTTP 503 means the assistant is busy (ApiError with status 503).
 */
export async function streamQuery(
  payload: { question: string; session_id?: string; agent?: string },
  onEvent: (event: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<QueryResult> {
  const post = () =>
    fetch("/api/v1/query-stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify(payload),
      credentials: "same-origin",
      signal,
    });
  let response = await post();
  if (response.status === 401 && (await refreshSession())) response = await post();
  if (response.status === 401) {
    accessToken = null;
    authLostHandler?.();
  }
  if (!response.ok || !response.body) throw new ApiError(response.status, await detail(response));

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : (lines.pop() ?? "");
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as StreamEvent;
      if (event.type === "done") return event;
      if (event.type === "error") throw new ApiError(500, event.message);
      onEvent(event);
    }
    if (done) break;
  }
  throw new ApiError(500, "no answer");
}
