/**
 * Drizzle schema for corpus.db
 *
 * Matches the existing schema in qino-lingo/corpus.db
 */

import { sqliteTable, text, integer, real } from "drizzle-orm/sqlite-core";

// ============================================================================
// Core Tables (existing in corpus.db)
// ============================================================================

export const files = sqliteTable("files", {
  id: integer("id").primaryKey({ autoIncrement: true }),
  filename: text("filename").notNull().unique(),
  sessionId: text("session_id"),
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
  fileId: integer("file_id")
    .notNull()
    .references(() => files.id),
  turnStart: integer("turn_start"),
  turnEnd: integer("turn_end"),
  isRich: integer("is_rich", { mode: "boolean" }).notNull(),
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
  fileId: integer("file_id")
    .notNull()
    .references(() => files.id),
  turnStart: integer("turn_start"),
  turnEnd: integer("turn_end"),
  excerpt: text("excerpt"),
  notes: text("notes"),
  createdAt: text("created_at").default("CURRENT_TIMESTAMP"),
});

// ============================================================================
// Tables for qino-label (already exist in corpus.db)
// ============================================================================

export const pendingLabels = sqliteTable("pending_labels", {
  id: integer("id").primaryKey(),
  fileId: integer("file_id")
    .notNull()
    .references(() => files.id),
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
  fileId: integer("file_id")
    .notNull()
    .references(() => files.id),
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
