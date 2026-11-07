import { existsSync } from "node:fs";

export type SslMode = "disable" | "require" | "verify-full";

export interface Config {
  port: number;
  environmentId: string;
  db: {
    host: string;
    port: number;
    database: string;
    user: string;
    password: string;
    sslMode: SslMode;
    caFile: string | null;
  };
}

const DEFAULT_CA_FILE = "/etc/ssl/certs/rds-global-bundle.pem";

function required(env: NodeJS.ProcessEnv, name: string): string {
  const value = env[name];
  if (value === undefined || value === "") {
    throw new Error(`Missing required environment variable ${name}`);
  }
  return value;
}

function parsePort(raw: string | undefined, fallback: number, name: string): number {
  if (raw === undefined || raw === "") {
    return fallback;
  }
  const value = Number(raw);
  if (!Number.isInteger(value) || value < 1 || value > 65535) {
    throw new Error(`${name} must be an integer in [1, 65535], got "${raw}"`);
  }
  return value;
}

/**
 * Reads configuration from the environment variables defined by the workload contract
 * (workload.container/v1): PORT and DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD.
 *
 * DB_SSL_MODE selects transport security:
 *   verify-full  TLS, certificate and host name verified against DB_CA_FILE (default when the file exists)
 *   require      TLS without certificate verification
 *   disable      plain TCP, for local development only
 */
export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const caFile = env.DB_CA_FILE ?? DEFAULT_CA_FILE;
  const caExists = existsSync(caFile);
  const sslMode = (env.DB_SSL_MODE ?? (caExists ? "verify-full" : "require")) as SslMode;
  if (!["disable", "require", "verify-full"].includes(sslMode)) {
    throw new Error(`DB_SSL_MODE must be disable, require or verify-full, got "${sslMode}"`);
  }
  if (sslMode === "verify-full" && !caExists) {
    throw new Error(`DB_SSL_MODE=verify-full requires a CA bundle at ${caFile}`);
  }
  return {
    port: parsePort(env.PORT, 8080, "PORT"),
    environmentId: env.INFRAFLOW_ENV_ID ?? "local",
    db: {
      host: required(env, "DB_HOST"),
      port: parsePort(env.DB_PORT, 5432, "DB_PORT"),
      database: required(env, "DB_NAME"),
      user: required(env, "DB_USER"),
      password: required(env, "DB_PASSWORD"),
      sslMode,
      caFile: sslMode === "verify-full" ? caFile : null,
    },
  };
}
