/**
 * Server function to get the labeling queue
 */

import { createServerFn } from "@tanstack/react-start";
import { eq, desc, sql } from "drizzle-orm";
import { getDb, schema } from "./db";

export const getQueue = createServerFn({ method: "GET" }).handler(async () => {
  const db = getDb();

  const items = await db
    .select({
      id: schema.pendingLabels.id,
      fileId: schema.pendingLabels.fileId,
      turnStart: schema.pendingLabels.turnStart,
      turnEnd: schema.pendingLabels.turnEnd,
      source: schema.pendingLabels.source,
      context: schema.pendingLabels.context,
      createdAt: schema.pendingLabels.createdAt,
      filename: schema.files.filename,
      turnCount: sql<number>`${schema.files.userTurns} + ${schema.files.claudeTurns}`.as("turn_count"),
    })
    .from(schema.pendingLabels)
    .innerJoin(schema.files, eq(schema.pendingLabels.fileId, schema.files.id))
    .orderBy(desc(schema.pendingLabels.createdAt));

  return {
    items: items.map((row) => ({
      id: row.id,
      fileId: row.fileId,
      turnStart: row.turnStart,
      turnEnd: row.turnEnd,
      source: row.source as "skill" | "qino-model" | "manual" | "sampler",
      context: row.context,
      createdAt: row.createdAt,
      filename: row.filename,
      turnCount: row.turnCount,
    })),
  };
});
