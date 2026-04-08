/**
 * Drizzle schema for corpus.db
 *
 * Mirrors the canonical schema in qino-lingo/python/qino_lingo/migrations/.
 * Schema authority lives in db.py + the migration files; this file is a
 * hand-maintained mirror updated when migrations land. After Chunk 1
 * (filename-as-FK), every dependent table FKs on filename instead of
 * file_id, and files.session_id was renamed to claude_session_id.
 */

import { sqliteTable, text, integer, real } from "drizzle-orm/sqlite-core";

// ============================================================================
// Core Tables
// ============================================================================

export const files = sqliteTable("files", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  filename: text("filename").notNull().unique(),
  // Truncated id from claude-extract; collision-prone, see Stage B notes
  // in implementations/persistence-layer/01-holistic-refactor.md
  claudeSessionId: text("claude_session_id"),
  date: text("date"),
  isAgent: integer("is_agent", { mode: "boolean" }),
  fileSize: integer("file_size"),
  userTurns: integer("user_turns"),
  claudeTurns: integer("claude_turns"),
  substantiveUserTurns: integer("substantive_user_turns"),
  userWordCount: integer("user_word_count"),
  claudeWordCount: integer("claude_word_count"),
  dialogueDensity: real("dialogue_density"),
  hasCommandExpansion: integer("has_command_expansion", { mode: "boolean" }),
  hasReflectiveLanguage: integer("has_reflective_language", { mode: "boolean" }),
  sourcePath: text("source_path"),
  status: text("status").default("active"),
  importedAt: text("imported_at").default("CURRENT_TIMESTAMP"),
  createdAt: text("created_at").default("CURRENT_TIMESTAMP"),
});

export const labels = sqliteTable("labels", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  filename: text("filename")
    .notNull()
    .references(() => files.filename, { onUpdate: "cascade" }),
  turnStart: integer("turn_start"),
  turnEnd: integer("turn_end"),
  rating: integer("rating").notNull(), // 1=thin, 2=functional, 3=rich
  tags: text("tags"), // JSON array of secondary tags
  notes: text("notes"),
  createdAt: text("created_at").default("CURRENT_TIMESTAMP"),
});

export const markers = sqliteTable("markers", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  name: text("name").notNull().unique(),
  description: text("description"),
  createdAt: text("created_at").default("CURRENT_TIMESTAMP"),
});

export const examples = sqliteTable("examples", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  markerId: integer("marker_id")
    .notNull()
    .references(() => markers.id),
  filename: text("filename")
    .notNull()
    .references(() => files.filename, { onUpdate: "cascade" }),
  turnStart: integer("turn_start"),
  turnEnd: integer("turn_end"),
  excerpt: text("excerpt"),
  notes: text("notes"),
  createdAt: text("created_at").default("CURRENT_TIMESTAMP"),
});

// ============================================================================
// Tables for qino-label
// ============================================================================

export const pendingLabels = sqliteTable("pending_labels", {
  id: integer("id").primaryKey(),
  filename: text("filename")
    .notNull()
    .references(() => files.filename, { onUpdate: "cascade" }),
  turnStart: integer("turn_start"),
  turnEnd: integer("turn_end"),
  source: text("source").default("manual"),
  context: text("context"),
  createdAt: text("created_at").default("CURRENT_TIMESTAMP"),
});

export const modelFeedback = sqliteTable("model_feedback", {
  id: integer("id").primaryKey(),
  prompt: text("prompt").notNull(),
  modelResponse: text("model_response").notNull(),
  rating: integer("rating"),
  preferredResponse: text("preferred_response"),
  notes: text("notes"),
  createdAt: text("created_at").default("CURRENT_TIMESTAMP"),
});

// ============================================================================
// Noise Filter Tables
// ============================================================================

export const noisePredictions = sqliteTable("noise_predictions", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  filename: text("filename")
    .notNull()
    .references(() => files.filename, { onUpdate: "cascade" }),
  turnIdx: integer("turn_idx").notNull(),
  // Deterministic filter results
  deterministicIsNoise: integer("deterministic_is_noise", { mode: "boolean" }),
  deterministicReason: text("deterministic_reason"),
  // ML filter results
  mlScore: real("ml_score"), // 0.0 = signal, 1.0 = noise
  mlIsNoise: integer("ml_is_noise", { mode: "boolean" }),
  // Final classification (human label overrides predictions)
  humanLabel: integer("human_label", { mode: "boolean" }), // null = not labeled
  // Metadata
  createdAt: text("created_at").default("CURRENT_TIMESTAMP"),
  updatedAt: text("updated_at"),
});
