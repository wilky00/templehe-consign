// ABOUTME: Fetches verification + password-reset emails from the local Mailpit instance.
// ABOUTME: Mailpit exposes an HTTP API on :8025; we query by recipient and parse the token from the link.
import { APIRequestContext, request } from "@playwright/test";
import { MAILPIT_URL } from "../../playwright.config";

interface MailpitMessage {
  ID: string;
  To: Array<{ Address: string }>;
  Subject: string;
}

interface MailpitSearchResponse {
  messages: MailpitMessage[];
}

interface MailpitMessageDetail {
  ID: string;
  HTML?: string;
  Text?: string;
}

async function ctx(): Promise<APIRequestContext> {
  return await request.newContext({ baseURL: MAILPIT_URL });
}

async function waitForMessage(
  toEmail: string,
  subjectContains: string,
  maxAttempts = 20,
  intervalMs = 500,
): Promise<MailpitMessage> {
  const api = await ctx();
  for (let i = 0; i < maxAttempts; i++) {
    const resp = await api.get(
      `/api/v1/search?query=to:${encodeURIComponent(toEmail)}`,
    );
    if (resp.ok()) {
      const body = (await resp.json()) as MailpitSearchResponse;
      const match = body.messages.find(
        (m) =>
          m.To.some((t) => t.Address.toLowerCase() === toEmail.toLowerCase()) &&
          m.Subject.toLowerCase().includes(subjectContains.toLowerCase()),
      );
      if (match) return match;
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  throw new Error(
    `Mailpit never saw an email to ${toEmail} matching "${subjectContains}"`,
  );
}

async function fetchBody(id: string): Promise<string> {
  const api = await ctx();
  const resp = await api.get(`/api/v1/message/${id}`);
  if (!resp.ok()) {
    throw new Error(`Mailpit message fetch failed: ${resp.status()}`);
  }
  const body = (await resp.json()) as MailpitMessageDetail;
  return body.HTML ?? body.Text ?? "";
}

function extractVerifyToken(body: string): string {
  // The verification email links to ${base}/auth/verify-email?token=...
  const match = body.match(/verify-email\?token=([A-Za-z0-9._\-~]+)/);
  if (!match) {
    throw new Error("Could not extract verify-email token from email body");
  }
  return match[1];
}

export async function fetchVerifyToken(toEmail: string): Promise<string> {
  const msg = await waitForMessage(toEmail, "verify");
  const body = await fetchBody(msg.ID);
  return extractVerifyToken(body);
}

/**
 * Wait for any message addressed to `toEmail` whose subject contains
 * `subjectContains` (case-insensitive). Returns the body so callers can
 * grep for content. Used by specs that verify durable notification
 * dispatches reach the SMTP outbox, not just the queue.
 */
export async function waitForEmailBody(
  toEmail: string,
  subjectContains: string,
  opts: { maxAttempts?: number; intervalMs?: number } = {},
): Promise<string> {
  const msg = await waitForMessage(
    toEmail,
    subjectContains,
    opts.maxAttempts ?? 40,
    opts.intervalMs ?? 500,
  );
  return await fetchBody(msg.ID);
}

export async function clearInbox(): Promise<void> {
  // Best-effort cleanup between tests that care about message counts.
  const api = await ctx();
  try {
    await api.delete("/api/v1/messages");
  } catch {
    // ignore — inbox cleanup isn't a correctness requirement
  }
}
