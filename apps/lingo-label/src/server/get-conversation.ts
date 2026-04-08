/**
 * Server function to get conversation details
 *
 * Supports two modes:
 * - Queue mode: id is pending_labels.id (no labelId)
 * - Edit mode: id is files.id, labelId is labels.id
 *
 * After Chunk 1 (filename-as-FK), every dependent-table query joins
 * via filename instead of files.id. files.id still exists as the
 * autoincrement primary key, so the route param stays an integer in
 * edit mode — but the moment we have the file row, downstream lookups
 * (labels, noise predictions) all key off filename.
 */

import { createServerFn } from "@tanstack/react-start";
import { eq } from "drizzle-orm";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { z } from "zod";
import { getDb, getCorpusDir, schema } from "./db";
import type { ConversationTurn } from "~/types";

/**
 * Parse a conversation markdown file into turns
 */
function parseConversation(content: string): ConversationTurn[] {
  const turns: ConversationTurn[] = [];
  const lines = content.split("\n");

  let currentRole: "human" | "assistant" | null = null;
  let currentContent: string[] = [];

  for (const line of lines) {
    // Check for role headers (supports multiple formats)
    // "## Human", "## User", "## 👤 User"
    if (
      line.startsWith("## Human") ||
      line.startsWith("## User") ||
      line.startsWith("## 👤")
    ) {
      // Save previous turn
      if (currentRole && currentContent.length > 0) {
        turns.push({
          role: currentRole,
          content: currentContent.join("\n").trim(),
        });
      }
      currentRole = "human";
      currentContent = [];
    } else if (
      line.startsWith("## Assistant") ||
      line.startsWith("## Claude") ||
      line.startsWith("## 🤖")
    ) {
      // Save previous turn
      if (currentRole && currentContent.length > 0) {
        turns.push({
          role: currentRole,
          content: currentContent.join("\n").trim(),
        });
      }
      currentRole = "assistant";
      currentContent = [];
    } else if (currentRole) {
      currentContent.push(line);
    }
  }

  // Save last turn
  if (currentRole && currentContent.length > 0) {
    turns.push({
      role: currentRole,
      content: currentContent.join("\n").trim(),
    });
  }

  return turns;
}

/**
 * Find the conversation file in the corpus.
 *
 * Note: after Chunk 2 (collapse `_noise/`) all conversations live at the
 * top level of the corpus dir. The legacy `_noise/` fallback below
 * exists for the in-between window where some files still live there;
 * once Chunk 2 lands and `_noise/` is gone, the fallback can be removed.
 */
function findConversationFile(corpusDir: string, filename: string): string {
  const filePath = join(corpusDir, filename);
  if (existsSync(filePath)) {
    return filePath;
  }

  const noisePath = join(corpusDir, "_noise", filename);
  if (existsSync(noisePath)) {
    return noisePath;
  }

  throw new Error(`Conversation file not found: ${filePath}`);
}

const ConversationIdSchema = z.object({
  id: z.string(),
  labelId: z.number().optional(), // If present, edit mode
});

export const getConversation = createServerFn({ method: "GET" })
  .inputValidator(ConversationIdSchema)
  .handler(async ({ data }) => {
    const db = getDb();
    const corpusDir = getCorpusDir();

    let filename: string;
    let turnStart: number | null = null;
    let turnEnd: number | null = null;
    let editingLabel: {
      id: number;
      rating: number | null;
      tags: string | null;
      notes: string | null;
      turnStart: number | null;
      turnEnd: number | null;
    } | null = null;

    if (data.labelId !== undefined) {
      // Edit mode: id is files.id (autoincrement PK still exists),
      // labelId is labels.id. Show FULL conversation (don't filter by
      // turn range).
      const fileId = Number(data.id);

      const [file] = await db
        .select({ filename: schema.files.filename })
        .from(schema.files)
        .where(eq(schema.files.id, fileId));

      if (!file) {
        throw new Error(`File ${fileId} not found`);
      }
      filename = file.filename;

      // Get the label being edited (for pre-filling form, not for filtering)
      const [label] = await db
        .select()
        .from(schema.labels)
        .where(eq(schema.labels.id, data.labelId));

      if (label) {
        editingLabel = {
          id: label.id,
          rating: label.rating,
          tags: label.tags,
          notes: label.notes,
          turnStart: label.turnStart,
          turnEnd: label.turnEnd,
        };
        // Don't set turnStart/turnEnd here - we want full conversation in edit mode
      }
    } else {
      // Queue mode: id is pending_labels.id
      const [pending] = await db
        .select({
          filename: schema.pendingLabels.filename,
          turnStart: schema.pendingLabels.turnStart,
          turnEnd: schema.pendingLabels.turnEnd,
        })
        .from(schema.pendingLabels)
        .where(eq(schema.pendingLabels.id, Number(data.id)));

      if (!pending) {
        throw new Error(`Pending label ${data.id} not found`);
      }

      filename = pending.filename;
      turnStart = pending.turnStart;
      turnEnd = pending.turnEnd;
    }

    // Read conversation file
    const filePath = findConversationFile(corpusDir, filename);
    const content = readFileSync(filePath, "utf-8");
    let turns = parseConversation(content);

    // Filter to specific turn range if specified
    if (turnStart !== null && turnEnd !== null) {
      turns = turns.slice(turnStart, turnEnd + 1);
    }

    // Get existing labels for this file (joined by filename, the new FK target)
    const existingLabels = await db
      .select()
      .from(schema.labels)
      .where(eq(schema.labels.filename, filename));

    // Get available markers
    const availableMarkers = await db.select().from(schema.markers);

    // Get noise predictions for this file
    const noisePredictions = await db
      .select({
        turnIdx: schema.noisePredictions.turnIdx,
        deterministicIsNoise: schema.noisePredictions.deterministicIsNoise,
        deterministicReason: schema.noisePredictions.deterministicReason,
        mlScore: schema.noisePredictions.mlScore,
        mlIsNoise: schema.noisePredictions.mlIsNoise,
      })
      .from(schema.noisePredictions)
      .where(eq(schema.noisePredictions.filename, filename));

    // Create a map for quick lookup
    const noiseByTurn = new Map(noisePredictions.map((p) => [p.turnIdx, p]));

    // Attach noise info to turns
    const turnsWithNoise = turns.map((turn, idx) => {
      const noise = noiseByTurn.get(idx);
      return {
        ...turn,
        noise: noise
          ? {
              deterministic: noise.deterministicIsNoise ?? false,
              reason: noise.deterministicReason,
              mlScore: noise.mlScore,
              mlIsNoise: noise.mlIsNoise,
            }
          : null,
      };
    });

    return {
      id: data.id,
      filename,
      turns: turnsWithNoise,
      existingLabels,
      availableMarkers,
      editingLabel, // Pre-fill values when editing
    };
  });
