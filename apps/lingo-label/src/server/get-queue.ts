/**
 * Server function to get the labeling queue
 *
 * After Chunk 1, pending_labels.filename is the FK target, so the join
 * is on filename instead of file_id.
 */

import { createServerFn } from "@tanstack/react-start";
import { eq, desc, sql } from "drizzle-orm";
import { getDb, schema } from "./db";

export const getQueue = createServerFn({ method: "GET" }).handler(async () => {
  const db = getDb();

  const items = await db
    .select({
      id: schema.pendingLabels.id,
      filename: schema.pendingLabels.filename,
      turnStart: schema.pendingLabels.turnStart,
      turnEnd: schema.pendingLabels.turnEnd,
      source: schema.pendingLabels.source,
      context: schema.pendingLabels.context,
      createdAt: schema.pendingLabels.createdAt,
      turnCount: sql<number>`${schema.files.userTurns} + ${schema.files.claudeTurns}`.as("turn_count"),
    })
    .from(schema.pendingLabels)
    .innerJoin(
      schema.files,
      eq(schema.pendingLabels.filename, schema.files.filename)
    )
    .orderBy(desc(schema.pendingLabels.createdAt));

  return {
    items: items.map((row) => ({
      id: row.id,
      filename: row.filename,
      turnStart: row.turnStart,
      turnEnd: row.turnEnd,
      source: row.source as "skill" | "qino-model" | "manual" | "sampler",
      context: row.context,
      createdAt: row.createdAt,
      turnCount: row.turnCount,
    })),
  };
});
