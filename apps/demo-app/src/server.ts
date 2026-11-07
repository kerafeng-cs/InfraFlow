import { createServer } from "node:http";
import { hostname } from "node:os";
import { setTimeout as sleep } from "node:timers/promises";

import { createHandler } from "./app.ts";
import { loadConfig } from "./config.ts";
import { createPgRepository } from "./pg-repository.ts";

const log = (entry: Record<string, unknown>): void => console.log(JSON.stringify({ time: new Date().toISOString(), ...entry }));

const config = loadConfig();
const repo = createPgRepository(config);
const host = hostname();
const processStartedAt = new Date();
let ready = false;

const server = createServer(createHandler({ repo, environmentId: config.environmentId, hostname: host, processStartedAt, log, isReady: () => ready }));
server.keepAliveTimeout = 65_000; // longer than the ALB idle timeout (60 s), so the load balancer closes first
server.headersTimeout = 66_000;

const controller = new AbortController();

/**
 * Applies the schema and records this boot. The database may still be starting when the
 * instance wakes, so this retries with capped backoff instead of failing the process.
 * Until it succeeds, /healthz reports 503 and the load balancer keeps the target out of service.
 */
async function initialize(): Promise<void> {
  for (let attempt = 1; !controller.signal.aborted; attempt++) {
    try {
      await repo.migrate();
      const boot = await repo.recordBoot(host);
      ready = true;
      log({ level: "info", msg: "database ready", attempt, bootId: boot.id });
      return;
    } catch (err) {
      const delay = Math.min(30_000, 1000 * 2 ** Math.min(attempt - 1, 5));
      log({ level: "warn", msg: "database not ready", attempt, retryInMs: delay, err: (err as Error).message });
      await sleep(delay, undefined, { signal: controller.signal }).catch(() => undefined);
    }
  }
}

server.listen(config.port, () => {
  log({ level: "info", msg: "listening", port: config.port, environmentId: config.environmentId, sslMode: config.db.sslMode });
  void initialize();
});

function shutdown(signal: string): void {
  log({ level: "info", msg: "shutting down", signal });
  controller.abort();
  server.close(() => {
    repo.close().finally(() => process.exit(0));
  });
  server.closeIdleConnections();
  setTimeout(() => process.exit(1), 10_000).unref();
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
