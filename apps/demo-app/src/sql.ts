/** SQL used by the PostgreSQL repository. Kept separate so it can be checked without a driver. */

export const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS notes (
  id          BIGSERIAL PRIMARY KEY,
  body        TEXT        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 500),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS boots (
  id          BIGSERIAL PRIMARY KEY,
  hostname    TEXT        NOT NULL,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
`;

export const SQL = {
  insertBoot: "INSERT INTO boots (hostname) VALUES ($1) RETURNING id, hostname, started_at",
  listNotes: "SELECT id, body, created_at FROM notes ORDER BY id DESC LIMIT $1",
  insertNote: "INSERT INTO notes (body) VALUES ($1) RETURNING id, body, created_at",
  listBoots: "SELECT id, hostname, started_at FROM boots ORDER BY id DESC LIMIT $1",
  summary: `SELECT (SELECT count(*) FROM notes)::int AS note_count,
                   (SELECT count(*) FROM boots)::int AS boot_count,
                   (SELECT min(started_at) FROM boots) AS first_boot_at,
                   current_setting('server_version') AS server_version`,
  ping: "SELECT 1",
} as const;
