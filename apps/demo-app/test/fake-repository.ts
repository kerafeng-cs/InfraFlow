import type { Boot, Note, Repository, Summary } from "../src/repository.ts";

export class FakeRepository implements Repository {
  notes: Note[] = [];
  boots: Boot[] = [];
  failing = false;
  pingDelayMs = 0;

  private check(): void {
    if (this.failing) {
      throw new Error("connection refused");
    }
  }
  async migrate(): Promise<void> {
    this.check();
  }
  async recordBoot(hostname: string): Promise<Boot> {
    this.check();
    const boot = { id: this.boots.length + 1, hostname, startedAt: new Date() };
    this.boots.push(boot);
    return boot;
  }
  async listNotes(limit: number): Promise<Note[]> {
    this.check();
    return [...this.notes].reverse().slice(0, limit);
  }
  async addNote(body: string): Promise<Note> {
    this.check();
    const note = { id: this.notes.length + 1, body, createdAt: new Date() };
    this.notes.push(note);
    return note;
  }
  async listBoots(limit: number): Promise<Boot[]> {
    this.check();
    return [...this.boots].reverse().slice(0, limit);
  }
  async summary(): Promise<Summary> {
    this.check();
    return { noteCount: this.notes.length, bootCount: this.boots.length, firstBootAt: this.boots[0]?.startedAt ?? null, serverVersion: "16.0" };
  }
  async ping(): Promise<void> {
    if (this.pingDelayMs > 0) {
      await new Promise((r) => setTimeout(r, this.pingDelayMs));
    }
    this.check();
  }
  async close(): Promise<void> {}
}
