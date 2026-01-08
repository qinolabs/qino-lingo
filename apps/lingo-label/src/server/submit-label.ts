/**
 * Server function to submit a label
 *
 * Supports both:
 * - Queue mode: creates new label and removes from pending queue
 * - Edit mode: updates existing label
 */

import { createServerFn } from "@tanstack/react-start";
import { and, eq, isNull } from "drizzle-orm";
import { z } from "zod";
import { getDb, schema } from "./db";

const SubmitLabelSchema = z.object({
  id: z.string(),
  fileId: z.number(),
  rating: z.number().min(1).max(3), // 1=thin, 2=functional, 3=rich
  tags: z.array(z.string()), // Secondary tags
  notes: z.string(),
  turnStart: z.number(),
  turnEnd: z.number(),
  isEditMode: z.boolean(),
});

export const submitLabel = createServerFn({ method: "POST" })
  .inputValidator(SubmitLabelSchema)
  .handler(async ({ data }) => {
    const db = getDb();

    // Check if a label already exists for this file/segment (idempotent upsert)
    const existingLabelConditions =
      data.turnStart !== null && data.turnEnd !== null
        ? and(
            eq(schema.labels.fileId, data.fileId),
            eq(schema.labels.turnStart, data.turnStart),
            eq(schema.labels.turnEnd, data.turnEnd)
          )
        : and(
            eq(schema.labels.fileId, data.fileId),
            isNull(schema.labels.turnStart),
            isNull(schema.labels.turnEnd)
          );

    const [existingLabel] = await db
      .select({ id: schema.labels.id })
      .from(schema.labels)
      .where(existingLabelConditions);

    const tagsJson = data.tags.length > 0 ? JSON.stringify(data.tags) : null;

    if (existingLabel) {
      // Update existing label
      await db
        .update(schema.labels)
        .set({
          rating: data.rating,
          tags: tagsJson,
          notes: data.notes || null,
          createdAt: new Date().toISOString(),
        })
        .where(eq(schema.labels.id, existingLabel.id));
    } else {
      // Insert new label
      await db.insert(schema.labels).values({
        fileId: data.fileId,
        turnStart: data.turnStart,
        turnEnd: data.turnEnd,
        rating: data.rating,
        tags: tagsJson,
        notes: data.notes || null,
      });
    }

    // In queue mode, remove from pending queue and get next item
    let nextId: number | null = null;
    if (!data.isEditMode) {
      await db
        .delete(schema.pendingLabels)
        .where(eq(schema.pendingLabels.id, Number(data.id)));

      // Get next pending item
      const [next] = await db
        .select({ id: schema.pendingLabels.id })
        .from(schema.pendingLabels)
        .limit(1);

      nextId = next?.id ?? null;
    }

    return { success: true, nextId };
  });
