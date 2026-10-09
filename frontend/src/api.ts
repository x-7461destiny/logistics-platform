export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
export type LogEntry = { time: string; kind: string; message: string };
export async function request<T>(
  path: string,
  token: string,
  log: (kind: string, message: string) => void,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof URLSearchParams))
    headers.set("Content-Type", "application/json");
  try {
    const response = await fetch(`/api/v1${path}`, {
      ...init,
      headers,
      signal: init.signal ?? AbortSignal.timeout(15000),
    });
    const body = await response.text();
    let data: unknown;
    try {
      data = JSON.parse(body);
    } catch {
      data = body;
    }
    if (!response.ok) {
      const detail =
        typeof data === "object" && data !== null && "detail" in data
          ? data.detail
          : data;
      throw new ApiError(
        response.status,
        `${response.status} ${typeof detail === "string" ? detail : JSON.stringify(detail)}`,
      );
    }
    return data as T;
  } catch (error) {
    log(
      "HTTP 错误",
      `${init.method ?? "GET"} ${path} · ${error instanceof Error ? error.message : String(error)}`,
    );
    throw error;
  }
}
