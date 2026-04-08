/**
 * Database connection for corpus.db using Drizzle ORM
 *
 * Reads from the qino-lingo corpus.db file.
 * Path configured via CORPUS_DB_PATH environment variable.
 *
 * Schema authority lives in qino-lingo/python/qino_lingo/migrations/.
 * This file no longer contains defensive `CREATE TABLE IF NOT EXISTS`
 * blocks — those existed before there was a real migration runner and
 * created drift between three different sources of schema truth. After
 * Chunk 1, all schema work goes through `make migrate`.
 */

import Database from "better-sqlite3";
import { drizzle } from "drizzle-orm/better-sqlite3";
import { existsSync } from "node:fs";

import * as schema from "./schema";

let db: ReturnType<typeof drizzle<typeof schema>> | null = null;
let sqliteDb: Database.Database | null = null;

export function getDb() {
  if (db) return db;

  const dbPath = process.env.CORPUS_DB_PATH;
  if (!dbPath) {
    throw new Error(
      "CORPUS_DB_PATH environment variable not set. " +
        "Set it in .env.local to point to your corpus.db file."
    );
  }

  if (!existsSync(dbPath)) {
    throw new Error(`corpus.db not found at ${dbPath}`);
  }

  sqliteDb = new Database(dbPath);

  // Enforce foreign keys per-connection. SQLite ignores FK declarations
  // unless this is set on every connection. Without it, the FK rebuild
  // from Chunk 1 is documentation that lies.
  sqliteDb.pragma("foreign_keys = ON");

  db = drizzle(sqliteDb, { schema });
  return db;
}

export function getCorpusDir(): string {
  const corpusDir = process.env.CORPUS_DIR;
  if (!corpusDir) {
    throw new Error(
      "CORPUS_DIR environment variable not set. " +
        "Set it in .env.local to point to your corpus/ directory."
    );
  }
  return corpusDir;
}

// Export schema for use in queries
export { schema };
