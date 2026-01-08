/**
 * Server function to get conversation details
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

const ConversationIdSchema = z.object({
  id: z.string(),
});

export const getConversation = createServerFn({ method: "GET" })
  .inputValidator(ConversationIdSchema)
  .handler(async ({ data }) => {
    const db = getDb();
    const corpusDir = getCorpusDir();

    // Get pending label info with file data
    const [pending] = await db
      .select({
        fileId: schema.pendingLabels.fileId,
        turnStart: schema.pendingLabels.turnStart,
        turnEnd: schema.pendingLabels.turnEnd,
        filename: schema.files.filename,
      })
      .from(schema.pendingLabels)
      .innerJoin(schema.files, eq(schema.pendingLabels.fileId, schema.files.id))
      .where(eq(schema.pendingLabels.id, Number(data.id)));

    if (!pending) {
      throw new Error(`Pending label ${data.id} not found`);
    }

    // Read conversation file
    const filePath = join(corpusDir, pending.filename);
    if (!existsSync(filePath)) {
      throw new Error(`Conversation file not found: ${filePath}`);
    }

    const content = readFileSync(filePath, "utf-8");
    let turns = parseConversation(content);

    // Filter to specific turn range if specified
    if (pending.turnStart !== null && pending.turnEnd !== null) {
      turns = turns.slice(pending.turnStart, pending.turnEnd + 1);
    }

    // Get existing labels for this file
    const existingLabels = await db
      .select()
      .from(schema.labels)
      .where(eq(schema.labels.fileId, pending.fileId));

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
      .where(eq(schema.noisePredictions.fileId, pending.fileId));

    // Create a map for quick lookup
    const noiseByTurn = new Map(
      noisePredictions.map((p) => [p.turnIdx, p])
    );

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
      filename: pending.filename,
      turns: turnsWithNoise,
      existingLabels,
      availableMarkers,
    };
  });
