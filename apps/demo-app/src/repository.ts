/** Persistence boundary of the application. The HTTP layer depends only on this interface. */

export interface Note {
  id: number;
  body: string;
  createdAt: Date;
}

export interface Boot {
  id: number;
  hostname: string;
  startedAt: Date;
}

export interface Summary {
  noteCount: number;
  bootCount: number;
  firstBootAt: Date | null;
  serverVersion: string;
}

export interface Repository {
  /** Creates the schema if it does not exist. Idempotent. */
  migrate(): Promise<void>;
  /** Records one process start; the boot history shows the application surviving Sleep and Wake. */
  recordBoot(hostname: string): Promise<Boot>;
  listNotes(limit: number): Promise<Note[]>;
  addNote(body: string): Promise<Note>;
  listBoots(limit: number): Promise<Boot[]>;
  summary(): Promise<Summary>;
  /** Round trip to the database, used by the health check. */
  ping(): Promise<void>;
  close(): Promise<void>;
}

export const MAX_NOTE_LENGTH = 500;
