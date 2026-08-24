// api/v1/_http.ts — the minimal request/response surface every v1
// handler needs.
//
// Vercel's Node runtime hands handlers Node's `IncomingMessage` /
// `ServerResponse` augmented with `query`, `body`, `status()` and
// `json()`. We type only the members we actually touch rather than
// depending on `@vercel/node` (not installed, and pulling it in for
// two interfaces would be a real dependency for a typing convenience).
//
// Structural typing means the hand-rolled `mockRes()` in tests/api/*
// satisfies `ApiResponse` without any test-side casting.

export interface ApiRequest {
  method?: string;
  url?: string;
  query?: Record<string, string | string[] | undefined>;
  headers: Record<string, string | string[] | undefined>;
  socket?: { remoteAddress?: string };
  body?: unknown;
}

export interface ApiResponse {
  status(code: number): ApiResponse;
  json(body: unknown): unknown;
  setHeader(name: string, value: string): unknown;
}

/** 405 with the `Allow` header the repo's other handlers all set. */
export function methodNotAllowed(res: ApiResponse, allow: string) {
  res.setHeader("Allow", allow);
  return res.status(405).json({ error: "method_not_allowed" });
}

/**
 * Structured one-line log, matching the `[api] <name> k=v` format every
 * other handler emits so existing log queries keep working.
 */
export function logApi(name: string, fields: Record<string, unknown>) {
  const parts = Object.entries(fields).map(([k, v]) => `${k}=${v}`);
  console.log(`[api] ${name} ${parts.join(" ")}`);
}
