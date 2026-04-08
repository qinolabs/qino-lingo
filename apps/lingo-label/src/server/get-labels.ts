/**
 * Server function to get submitted labels
 *
 * After Chunk 1, labels.filename is the FK target. The label row already
 * carries the filename so the join exists only to fetch turn-count
 * metadata from files.
 */

import { createServerFn } from "@tanstack/react-start";
import { desc, eq, sql } from "drizzle-orm";
import { getDb, schema } from "./db";

export const getLabels = createServerFn({ method: "GET" }).handler(async () => {
  const db = getDb();

  // Note: fileId here is files.id (integer PK), still required by the
  // edit-mode route which keys on files.id. After Chunk 1 the labels
  // table FKs on filename, but the autoincrement files.id still exists
  // and is a fine route key. The fields are pulled in the same select.
  const labels = await db
    .select({
      id: schema.labels.id,
      filename: schema.labels.filename,
      turnStart: schema.labels.turnStart,
      turnEnd: schema.labels.turnEnd,
      rating: schema.labels.rating,
      tags: schema.labels.tags,
      notes: schema.labels.notes,
      createdAt: schema.labels.createdAt,
      fileId: schema.files.id,
      totalTurns: sql<number>`${schema.files.userTurns} + ${schema.files.claudeTurns}`,
    })
    .from(schema.labels)
    .innerJoin(schema.files, eq(schema.labels.filename, schema.files.filename))
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
