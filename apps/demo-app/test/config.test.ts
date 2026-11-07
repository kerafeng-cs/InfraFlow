import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { loadConfig } from "../src/config.ts";

const baseEnv = { DB_HOST: "db", DB_NAME: "app", DB_USER: "app", DB_PASSWORD: "secret", DB_CA_FILE: "/nonexistent/ca.pem" };

describe("loadConfig", () => {
  it("applies defaults", () => {
    const c = loadConfig(baseEnv);
    assert.equal(c.port, 8080);
    assert.equal(c.db.port, 5432);
    assert.equal(c.environmentId, "local");
    assert.equal(c.db.sslMode, "require");
  });

  it("reads explicit values", () => {
    const c = loadConfig({ ...baseEnv, PORT: "3000", DB_PORT: "6543", INFRAFLOW_ENV_ID: "env-1", DB_SSL_MODE: "disable" });
    assert.equal(c.port, 3000);
    assert.equal(c.db.port, 6543);
    assert.equal(c.environmentId, "env-1");
    assert.equal(c.db.sslMode, "disable");
  });

  it("rejects missing credentials", () => {
    const { DB_PASSWORD: _omit, ...env } = baseEnv;
    assert.throws(() => loadConfig(env), /DB_PASSWORD/);
  });

  it("rejects an invalid port", () => {
    assert.throws(() => loadConfig({ ...baseEnv, PORT: "80a" }), /PORT/);
  });

  it("refuses verify-full without a CA bundle", () => {
    assert.throws(() => loadConfig({ ...baseEnv, DB_SSL_MODE: "verify-full" }), /CA bundle/);
  });
});
