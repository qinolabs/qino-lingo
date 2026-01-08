/**
 * Database connection for corpus.db using Drizzle ORM
 *
 * Reads from the qino-lingo corpus.db file.
 * Path configured via CORPUS_DB_PATH environment variable.
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

  // Ensure pending_labels table exists
  sqliteDb.exec(`
    CREATE TABLE IF NOT EXISTS pending_labels (
      id INTEGER PRIMARY KEY,
      file_id INTEGER NOT NULL,
      turn_start INTEGER,
      turn_end INTEGER,
      source TEXT DEFAULT 'manual',
      context TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      FOREIGN KEY (file_id) REFERENCES files(id)
    )
  `);

  // Ensure model_feedback table exists (Phase 2)
  sqliteDb.exec(`
    CREATE TABLE IF NOT EXISTS model_feedback (
      id INTEGER PRIMARY KEY,
      prompt TEXT NOT NULL,
      model_response TEXT NOT NULL,
      rating INTEGER,
      preferred_response TEXT,
      notes TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
  `);

  // Ensure noise_predictions table exists (for hybrid noise filter)
  sqliteDb.exec(`
    CREATE TABLE IF NOT EXISTS noise_predictions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      file_id INTEGER NOT NULL,
      turn_idx INTEGER NOT NULL,
      deterministic_is_noise INTEGER,
      deterministic_reason TEXT,
      ml_score REAL,
      ml_is_noise INTEGER,
      human_label INTEGER,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT,
      FOREIGN KEY (file_id) REFERENCES files(id),
      UNIQUE(file_id, turn_idx)
    )
  `);

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
