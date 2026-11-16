import type { ApiToken, ApiTokenCreated } from "./types";

const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "/api/v1";

const API_TIMEOUT_MS = 30_000;
const UPLOAD_TIMEOUT_MS = 120_000;

interface ErrorPayload extends ApiErrorDetail {
  detail?: string | Array<{ msg?: string }> | ApiErrorDetail;
}

export interface ApiErrorDetail {
  code?: string;
  status?: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly detail?: ApiErrorDetail,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function readCookie(name: string): string | undefined {
  if (typeof document === "undefined") return undefined;
  const prefix = `${encodeURIComponent(name)}=`;
  const raw = document.cookie
    .split("; ")
    .find((value) => value.startsWith(prefix))
    ?.slice(prefix.length);
  if (!raw) return undefined;
  try {
    return decodeURIComponent(raw);
  } catch {
    return undefined;
  }
}

function errorMessage(payload: ErrorPayload, fallback: string): string {
  if (typeof payload.detail === "string") return payload.detail;
  if (Array.isArray(payload.detail)) {
    return payload.detail
      .map((item) => item.msg)
      .filter(Boolean)
      .join(", ");
  }
  return fallback;
}

interface TimedResponse {
  response: Response;
  cleanup: () => void;
  didTimeout: () => boolean;
}

async function startTimedFetch(
  input: RequestInfo | URL,
  init: RequestInit,
  timeoutMs: number,
): Promise<TimedResponse> {
  const controller = new AbortController();
  const sourceSignal = init.signal;
  let timedOut = false;
  let cleanedUp = false;
  const forwardAbort = () => controller.abort(sourceSignal?.reason);
  if (sourceSignal?.aborted) {
    forwardAbort();
  } else {
    sourceSignal?.addEventListener("abort", forwardAbort, { once: true });
  }
  const timeout = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const cleanup = () => {
    if (cleanedUp) return;
    cleanedUp = true;
    globalThis.clearTimeout(timeout);
    sourceSignal?.removeEventListener("abort", forwardAbort);
  };

  try {
    const response = await fetch(input, { ...init, signal: controller.signal });
    return {
      response,
      cleanup,
      didTimeout: () => timedOut,
    };
  } catch (error) {
    cleanup();
    if (timedOut) {
      throw new ApiError("Превышено время ожидания ответа сервера", 408);
    }
    throw error;
  }
}

let refreshPromise: Promise<boolean> | null = null;

const PUBLIC_AUTH_PATHS = [
  "/auth/login",
  "/auth/register",
  "/auth/forgot-password",
  "/auth/reset-password",
  "/auth/verify-email",
  "/auth/totp/complete-google",
];

function isPublicAuthPath(path: string): boolean {
  return PUBLIC_AUTH_PATHS.some(
    (publicPath) => path === publicPath || path.startsWith(`${publicPath}?`),
  );
}

async function performRefresh(): Promise<boolean> {
  const headers = new Headers();
  const csrf = readCookie("noki_csrf");
  if (csrf) headers.set("X-CSRF-Token", csrf);

  return startTimedFetch(
    `${API_URL}/auth/refresh`,
    {
      method: "POST",
      credentials: "include",
      headers,
    },
    API_TIMEOUT_MS,
  )
    .then(async ({ response, cleanup }) => {
      try {
        await response.arrayBuffer();
        return response.ok;
      } finally {
        cleanup();
      }
    })
    .catch(() => false);
}

async function performCoordinatedRefresh(): Promise<boolean> {
  const csrfBeforeWaiting = readCookie("noki_csrf");
  if (typeof navigator === "undefined" || !navigator.locks) {
    return performRefresh();
  }
  return navigator.locks.request("noki-auth-refresh", async () => {
    const csrfAfterWaiting = readCookie("noki_csrf");
    if (
      csrfBeforeWaiting &&
      csrfAfterWaiting &&
      csrfAfterWaiting !== csrfBeforeWaiting
    ) {
      // Another tab already rotated both auth cookies while this tab waited.
      return true;
    }
    return performRefresh();
  });
}

function refreshSession(): Promise<boolean> {
  if (refreshPromise) return refreshPromise;

  refreshPromise = performCoordinatedRefresh().finally(() => {
    refreshPromise = null;
  });

  return refreshPromise;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(init.headers);
  const isFormData =
    typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body && !isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const csrf = readCookie("noki_csrf");
  if (csrf && !headers.has("X-CSRF-Token")) {
    headers.set("X-CSRF-Token", csrf);
  }

  const timedResponse = await startTimedFetch(
    `${API_URL}${path}`,
    {
      ...init,
      headers,
      credentials: "include",
    },
    isFormData ? UPLOAD_TIMEOUT_MS : API_TIMEOUT_MS,
  );
  const { response } = timedResponse;

  try {
    if (
      response.status === 401 &&
      retry &&
      !isPublicAuthPath(path) &&
      !path.startsWith("/auth/refresh")
    ) {
      timedResponse.cleanup();
      void response.body?.cancel();
      if (await refreshSession()) return apiFetch<T>(path, init, false);
      throw new ApiError("Требуется повторный вход", 401);
    }

    if (!response.ok) {
      const payload = (await response.json().catch((error: unknown) => {
        if (timedResponse.didTimeout()) throw error;
        return {};
      })) as ErrorPayload;
      throw new ApiError(
        errorMessage(payload, `Request failed with status ${response.status}`),
        response.status,
        typeof payload.detail === "object" && !Array.isArray(payload.detail)
          ? payload.detail
          : payload.code
            ? payload
            : undefined,
      );
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } catch (error) {
    if (timedResponse.didTimeout()) {
      throw new ApiError("Превышено время ожидания ответа сервера", 408);
    }
    throw error;
  } finally {
    timedResponse.cleanup();
  }
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T>(path: string, body: unknown) =>
    apiFetch<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    apiFetch<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  delete: <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, {
      method: "DELETE",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  upload: <T>(path: string, formData: FormData) =>
    apiFetch<T>(path, { method: "POST", body: formData }),
};

export async function adminPatch<T>(path: string, body: unknown): Promise<T> {
  let token = sessionStorage.getItem("noki_admin_step_up");
  if (!token) {
    const password = window.prompt(
      "Для административного действия повторно введите пароль",
    );
    if (!password)
      throw new ApiError("Требуется повторная аутентификация", 403);
    const mfaCode = window.prompt("Введите код приложения аутентификации или резервный код");
    if (!mfaCode)
      throw new ApiError("Требуется второй фактор", 403);
    const result = await api.post<{ token: string }>("/admin/step-up", {
      password,
      mfa_code: mfaCode,
    });
    token = result.token;
    sessionStorage.setItem("noki_admin_step_up", token);
  }
  try {
    return await apiFetch<T>(path, {
      method: "PATCH",
      headers: { "X-Admin-Step-Up": token },
      body: JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof ApiError && error.status === 403) {
      sessionStorage.removeItem("noki_admin_step_up");
    }
    throw error;
  }
}

export async function getApiTokens(): Promise<ApiToken[]> {
  return api.get<ApiToken[]>("/api-tokens");
}

export async function createApiToken(body: {
  name: string;
  scopes: string[];
  expires_in_days?: number;
}): Promise<ApiTokenCreated> {
  return api.post<ApiTokenCreated>("/api-tokens", body);
}

export async function revokeApiToken(
  tokenId: string,
): Promise<{ message: string }> {
  return api.delete<{ message: string }>(
    `/api-tokens/${encodeURIComponent(tokenId)}`,
  );
}

export function googleLoginUrl(
  action?: "set_password",
  consent = false,
): string {
  const query = new URLSearchParams();
  if (action) query.set("action", action);
  if (consent) query.set("consent", "true");
  const suffix = query.size ? `?${query}` : "";
  return `${API_URL}/auth/google${suffix}`;
}
