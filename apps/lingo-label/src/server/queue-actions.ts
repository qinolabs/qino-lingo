/**
 * Server functions for queue management actions
 */

import { createServerFn } from "@tanstack/react-start";
import { sql } from "drizzle-orm";
import { z } from "zod";
import { getDb, schema } from "./db";

const QueueActionSchema = z.object({
  action: z.enum(["clean", "noisy", "random"]),
  limit: z.number().min(1).max(50).default(10),
  noiseType: z.string().optional(), // e.g., "system_message"
});

export const queueConversations = createServerFn({ method: "POST" })
  .inputValidator(QueueActionSchema)
  .handler(async ({ data }) => {
    const db = getDb();
    const { action, limit, noiseType } = data;

    let fileIds: number[] = [];

    if (action === "clean") {
      // Conversations with NO noise predictions (cleanest signal)
      const results = await db.all<{ id: number }>(sql`
        SELECT f.id
        FROM files f
        WHERE f.status = 'active'
          AND f.id NOT IN (SELECT DISTINCT file_id FROM noise_predictions WHERE deterministic_is_noise = 1)
          AND f.id NOT IN (SELECT file_id FROM pending_labels)
          AND f.id NOT IN (SELECT file_id FROM labels)
        ORDER BY RANDOM()
        LIMIT ${limit}
      `);
      fileIds = results.map((r) => r.id);
    } else if (action === "noisy") {
      // Conversations WITH noise predictions (for review)
      const results = await db.all<{ id: number }>(sql`
        SELECT DISTINCT np.file_id as id
        FROM noise_predictions np
        JOIN files f ON np.file_id = f.id
        WHERE f.status = 'active'
          AND np.deterministic_is_noise = 1
          ${noiseType ? sql`AND np.deterministic_reason = ${noiseType}` : sql``}
          AND np.file_id NOT IN (SELECT file_id FROM pending_labels)
          AND np.file_id NOT IN (SELECT file_id FROM labels)
        ORDER BY RANDOM()
        LIMIT ${limit}
      `);
      fileIds = results.map((r) => r.id);
    } else {
      // Random from all active files
      const results = await db.all<{ id: number }>(sql`
        SELECT f.id
        FROM files f
        WHERE f.status = 'active'
          AND f.id NOT IN (SELECT file_id FROM pending_labels)
          AND f.id NOT IN (SELECT file_id FROM labels)
        ORDER BY RANDOM()
        LIMIT ${limit}
      `);
      fileIds = results.map((r) => r.id);
    }

    if (fileIds.length === 0) {
      return { queued: 0, message: "No eligible conversations found" };
    }

    // Insert into pending_labels
    const now = new Date().toISOString();
    for (const fileId of fileIds) {
      await db.insert(schema.pendingLabels).values({
        fileId,
        source: "sampler",
        context: `${action}${noiseType ? `:${noiseType}` : ""}`,
        createdAt: now,
      });
    }

    return {
      queued: fileIds.length,
      message: `Queued ${fileIds.length} ${action} conversations`,
    };
  });

/**
 * Get noise type breakdown for UI
 */
export const getNoiseBreakdown = createServerFn({ method: "GET" }).handler(
  async () => {
    const db = getDb();

    const results = await db.all<{ reason: string; count: number }>(sql`
      SELECT deterministic_reason as reason, COUNT(DISTINCT file_id) as count
      FROM noise_predictions
      WHERE deterministic_is_noise = 1
      GROUP BY deterministic_reason
      ORDER BY count DESC
    `);

    return { breakdown: results };
  }
);
