export type ClerkTicketConsumeResult = {
  ok?: boolean;
  status?: string | null;
  emailAddress?: string | null;
  code?: string;
  message?: string;
};

export type ClerkTicketRetryEvent = {
  attempt: number;
  code: string;
  message: string;
};

type ConsumeTicket = (ticket: string) => Promise<ClerkTicketConsumeResult>;

function sleep(ms: number): Promise<void> {
  if (ms <= 0) return Promise.resolve();
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function consumeTicketWithRetry(
  consumeTicket: ConsumeTicket,
  ticket: string,
  opts: {
    maxAttempts?: number;
    initialDelayMs?: number;
    onRetry?: (event: ClerkTicketRetryEvent) => void;
  } = {},
): Promise<ClerkTicketConsumeResult> {
  const maxAttempts = Math.max(1, opts.maxAttempts || 3);
  const initialDelayMs = Math.max(0, opts.initialDelayMs ?? 500);
  let last: ClerkTicketConsumeResult = { ok: false, code: "unknown", message: "" };

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    last = await consumeTicket(ticket);
    if (!last || last.ok) return last;
    if (last.code !== "sdk_not_ready") return last;
    if (attempt >= maxAttempts) return last;

    opts.onRetry?.({
      attempt,
      code: last.code || "unknown",
      message: (last.message || "").slice(0, 200),
    });
    await sleep(initialDelayMs * Math.pow(2, attempt - 1));
  }

  return last;
}
