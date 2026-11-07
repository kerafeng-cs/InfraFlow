import type { IncomingMessage, ServerResponse } from "node:http";

import type { Repository } from "./repository.ts";
import { MAX_NOTE_LENGTH } from "./repository.ts";
import { renderPage, renderUnavailable } from "./views.ts";

export interface AppContext {
  repo: Repository;
  environmentId: string;
  hostname: string;
  processStartedAt: Date;
  /** True once the schema has been applied; the health check fails until then. */
  isReady?: () => boolean;
  /** Upper bound for the database round trip in the health check. */
  healthTimeoutMs?: number;
  log?: (entry: Record<string, unknown>) => void;
}

export type Handler = (req: IncomingMessage, res: ServerResponse) => Promise<void>;

const MAX_BODY_BYTES = 16 * 1024;

class HttpError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function send(res: ServerResponse, status: number, contentType: string, body: string, extra: Record<string, string> = {}): void {
  res.writeHead(status, {
    "content-type": contentType,
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    ...extra,
  });
  res.end(body);
}

const sendJson = (res: ServerResponse, status: number, value: unknown): void =>
  send(res, status, "application/json; charset=utf-8", JSON.stringify(value));

const sendHtml = (res: ServerResponse, status: number, body: string): void =>
  send(res, status, "text/html; charset=utf-8", body, {
    "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
  });

async function readBody(req: IncomingMessage): Promise<string> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > MAX_BODY_BYTES) {
      throw new HttpError(413, "Request body too large");
    }
    chunks.push(chunk as Buffer);
  }
  return Buffer.concat(chunks).toString("utf8");
}

/** Validates and normalizes a note body; returns an error message when invalid. */
export function validateNote(input: unknown): { body: string } | { error: string } {
  if (typeof input !== "string") {
    return { error: "Note must be a string" };
  }
  const body = input.replace(/\s+/g, " ").trim();
  if (body.length === 0) {
    return { error: "Note must not be empty" };
  }
  if ([...body].length > MAX_NOTE_LENGTH) {
    return { error: `Note must be at most ${MAX_NOTE_LENGTH} characters` };
  }
  return { body };
}

function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: NodeJS.Timeout | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error(`timed out after ${ms} ms`)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

export function createHandler(ctx: AppContext): Handler {
  const log = ctx.log ?? ((entry) => console.log(JSON.stringify(entry)));
  const healthTimeoutMs = ctx.healthTimeoutMs ?? 2000;

  async function page(res: ServerResponse, status = 200, error?: string): Promise<void> {
    const [summary, notes, boots] = await Promise.all([ctx.repo.summary(), ctx.repo.listNotes(50), ctx.repo.listBoots(10)]);
    const model = { environmentId: ctx.environmentId, hostname: ctx.hostname, processStartedAt: ctx.processStartedAt, summary, notes, boots };
    sendHtml(res, status, renderPage(error === undefined ? model : { ...model, error }).value);
  }

  async function route(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? "/", "http://localhost");
    const method = req.method ?? "GET";
    const key = `${method} ${url.pathname}`;

    switch (key) {
      case "GET /healthz":
      case "HEAD /healthz": {
        if (ctx.isReady && !ctx.isReady()) {
          sendJson(res, 503, { status: "starting" });
          return;
        }
        try {
          await withTimeout(ctx.repo.ping(), healthTimeoutMs);
          sendJson(res, 200, { status: "ok" });
        } catch (err) {
          log({ level: "warn", msg: "health check failed", err: (err as Error).message });
          sendJson(res, 503, { status: "unavailable" });
        }
        return;
      }
      case "GET /":
        await page(res);
        return;
      case "POST /notes": {
        const form = new URLSearchParams(await readBody(req));
        const v = validateNote(form.get("body") ?? "");
        if ("error" in v) {
          await page(res, 400, v.error);
          return;
        }
        await ctx.repo.addNote(v.body);
        res.writeHead(303, { location: "/" });
        res.end();
        return;
      }
      case "GET /api/notes": {
        const notes = await ctx.repo.listNotes(100);
        sendJson(res, 200, { notes });
        return;
      }
      case "POST /api/notes": {
        let parsed: unknown;
        try {
          parsed = JSON.parse(await readBody(req));
        } catch (err) {
          if (err instanceof HttpError) {
            throw err;
          }
          throw new HttpError(400, "Body must be JSON");
        }
        const v = validateNote((parsed as { body?: unknown } | null)?.body);
        if ("error" in v) {
          throw new HttpError(400, v.error);
        }
        const note = await ctx.repo.addNote(v.body);
        sendJson(res, 201, { note });
        return;
      }
      case "GET /api/status": {
        const summary = await ctx.repo.summary();
        sendJson(res, 200, { environmentId: ctx.environmentId, hostname: ctx.hostname, processStartedAt: ctx.processStartedAt, ...summary });
        return;
      }
    }

    const knownPaths = new Set(["/", "/healthz", "/notes", "/api/notes", "/api/status"]);
    if (knownPaths.has(url.pathname)) {
      throw new HttpError(405, "Method not allowed");
    }
    throw new HttpError(404, "Not found");
  }

  return async (req, res) => {
    const started = process.hrtime.bigint();
    try {
      await route(req, res);
    } catch (err) {
      if (err instanceof HttpError) {
        sendJson(res, err.status, { error: err.message });
      } else {
        log({ level: "error", msg: "request failed", path: req.url, err: (err as Error).message });
        const wantsHtml = (req.headers.accept ?? "").includes("text/html");
        if (wantsHtml && !res.headersSent) {
          sendHtml(res, 503, renderUnavailable(ctx.environmentId).value);
        } else if (!res.headersSent) {
          sendJson(res, 503, { error: "Service unavailable" });
        } else {
          res.destroy();
        }
      }
    } finally {
      if (req.url !== "/healthz") {
        const ms = Number(process.hrtime.bigint() - started) / 1e6;
        log({ level: "info", msg: "request", method: req.method, path: req.url, status: res.statusCode, ms: Math.round(ms) });
      }
    }
  };
}
