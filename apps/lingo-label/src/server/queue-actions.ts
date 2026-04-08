/**
 * Server functions for queue management actions
 *
 * After Chunk 1, the dependent tables FK on filename instead of file_id.
 * The raw SQL queries below select and insert filename strings throughout.
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

    let filenames: string[] = [];

    if (action === "clean") {
      // Conversations with NO noise predictions (cleanest signal)
      const results = await db.all<{ filename: string }>(sql`
        SELECT f.filename
        FROM files f
        WHERE f.status = 'active'
          AND f.filename NOT IN (SELECT DISTINCT filename FROM noise_predictions WHERE deterministic_is_noise = 1)
          AND f.filename NOT IN (SELECT filename FROM pending_labels)
          AND f.filename NOT IN (SELECT filename FROM labels)
        ORDER BY RANDOM()
        LIMIT ${limit}
      `);
      filenames = results.map((r) => r.filename);
    } else if (action === "noisy") {
      // Conversations WITH noise predictions (for review)
      const results = await db.all<{ filename: string }>(sql`
        SELECT DISTINCT np.filename as filename
        FROM noise_predictions np
        JOIN files f ON np.filename = f.filename
        WHERE f.status = 'active'
          AND np.deterministic_is_noise = 1
          ${noiseType ? sql`AND np.deterministic_reason = ${noiseType}` : sql``}
          AND np.filename NOT IN (SELECT filename FROM pending_labels)
          AND np.filename NOT IN (SELECT filename FROM labels)
        ORDER BY RANDOM()
        LIMIT ${limit}
      `);
      filenames = results.map((r) => r.filename);
    } else {
      // Random from all active files
      const results = await db.all<{ filename: string }>(sql`
        SELECT f.filename
        FROM files f
        WHERE f.status = 'active'
          AND f.filename NOT IN (SELECT filename FROM pending_labels)
          AND f.filename NOT IN (SELECT filename FROM labels)
        ORDER BY RANDOM()
        LIMIT ${limit}
      `);
      filenames = results.map((r) => r.filename);
    }

    if (filenames.length === 0) {
      return { queued: 0, message: "No eligible conversations found" };
    }

    // Insert into pending_labels
    const now = new Date().toISOString();
    for (const filename of filenames) {
      await db.insert(schema.pendingLabels).values({
        filename,
        source: "sampler",
        context: `${action}${noiseType ? `:${noiseType}` : ""}`,
        createdAt: now,
      });
    }

    return {
      queued: filenames.length,
      message: `Queued ${filenames.length} ${action} conversations`,
    };
  });

/**
 * Get noise type breakdown for UI
 */
export const getNoiseBreakdown = createServerFn({ method: "GET" }).handler(
  async () => {
    const db = getDb();

    const results = await db.all<{ reason: string; count: number }>(sql`
      SELECT deterministic_reason as reason, COUNT(DISTINCT filename) as count
      FROM noise_predictions
      WHERE deterministic_is_noise = 1
      GROUP BY deterministic_reason
      ORDER BY count DESC
    `);

    return { breakdown: results };
  }
);
