/**
 * Server function to get submitted labels
 */

import { createServerFn } from "@tanstack/react-start";
import { desc, eq, sql } from "drizzle-orm";
import { getDb, schema } from "./db";

export const getLabels = createServerFn({ method: "GET" }).handler(async () => {
  const db = getDb();

  const labels = await db
    .select({
      id: schema.labels.id,
      fileId: schema.labels.fileId,
      turnStart: schema.labels.turnStart,
      turnEnd: schema.labels.turnEnd,
      rating: schema.labels.rating,
      tags: schema.labels.tags,
      notes: schema.labels.notes,
      createdAt: schema.labels.createdAt,
      filename: schema.files.filename,
      totalTurns: sql<number>`${schema.files.userTurns} + ${schema.files.claudeTurns}`,
    })
    .from(schema.labels)
    .innerJoin(schema.files, eq(schema.labels.fileId, schema.files.id))
    .orderBy(desc(schema.labels.createdAt));

  return {
    items: labels.map((l) => ({
      id: l.id,
      fileId: l.fileId,
      filename: l.filename,
      turnStart: l.turnStart,
      turnEnd: l.turnEnd,
      rating: l.rating,
      tags: l.tags ? (JSON.parse(l.tags) as string[]) : [],
      notes: l.notes,
      createdAt: l.createdAt,
      totalTurns: l.totalTurns,
    })),
  };
});
