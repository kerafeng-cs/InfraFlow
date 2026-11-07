import { readFileSync } from "node:fs";
import pg from "pg";

import type { Config } from "./config.ts";
import type { Boot, Note, Repository, Summary } from "./repository.ts";
import { SCHEMA_SQL, SQL } from "./sql.ts";

interface NoteRow { id: string; body: string; created_at: Date }
interface BootRow { id: string; hostname: string; started_at: Date }
interface SummaryRow { note_count: number; boot_count: number; first_boot_at: Date | null; server_version: string }

const toNote = (r: NoteRow): Note => ({ id: Number(r.id), body: r.body, createdAt: r.created_at });
const toBoot = (r: BootRow): Boot => ({ id: Number(r.id), hostname: r.hostname, startedAt: r.started_at });

function sslOptions(db: Config["db"]): pg.PoolConfig["ssl"] {
  if (db.sslMode === "disable") {
    return false;
  }
  if (db.sslMode === "require") {
    return { rejectUnauthorized: false };
  }
  return { rejectUnauthorized: true, ca: readFileSync(db.caFile as string, "utf8") };
}

export function createPgRepository(config: Config): Repository {
  const pool = new pg.Pool({
    host: config.db.host,
    port: config.db.port,
    database: config.db.database,
    user: config.db.user,
    password: config.db.password,
    ssl: sslOptions(config.db),
    max: 5,
    connectionTimeoutMillis: 3000,
    idleTimeoutMillis: 30000,
    statement_timeout: 5000,
  });
  // An idle client error (for example the database stopping) must not crash the process.
  pool.on("error", (err) => console.error(JSON.stringify({ level: "warn", msg: "idle database client error", err: err.message })));

  return {
    async migrate() {
      await pool.query(SCHEMA_SQL);
    },
    async recordBoot(hostname) {
      const r = await pool.query<BootRow>(SQL.insertBoot, [hostname]);
      return toBoot(r.rows[0] as BootRow);
    },
    async listNotes(limit) {
      const r = await pool.query<NoteRow>(SQL.listNotes, [limit]);
      return r.rows.map(toNote);
    },
    async addNote(body) {
      const r = await pool.query<NoteRow>(SQL.insertNote, [body]);
      return toNote(r.rows[0] as NoteRow);
    },
    async listBoots(limit) {
      const r = await pool.query<BootRow>(SQL.listBoots, [limit]);
      return r.rows.map(toBoot);
    },
    async summary() {
      const r = await pool.query<SummaryRow>(SQL.summary);
      const row = r.rows[0] as SummaryRow;
      return { noteCount: row.note_count, bootCount: row.boot_count, firstBootAt: row.first_boot_at, serverVersion: row.server_version };
    },
    async ping() {
      await pool.query(SQL.ping);
    },
    async close() {
      await pool.end();
    },
  };
}
