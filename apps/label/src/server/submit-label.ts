/**
 * Server function to submit a label
 */

import { createServerFn } from "@tanstack/react-start";
import { eq } from "drizzle-orm";
import { z } from "zod";
import { getDb, schema } from "./db";

const SubmitLabelSchema = z.object({
  id: z.string(),
  rating: z.number().min(1).max(5),
  notes: z.string(),
  markers: z.array(z.string()),
  turnStart: z.number().optional(),
  turnEnd: z.number().optional(),
});

export const submitLabel = createServerFn({ method: "POST" })
  .inputValidator(SubmitLabelSchema)
  .handler(async ({ data }) => {
    const db = getDb();

    // Get fileId from pending_labels
    const [pending] = await db
      .select({ fileId: schema.pendingLabels.fileId })
      .from(schema.pendingLabels)
      .where(eq(schema.pendingLabels.id, Number(data.id)));

    if (!pending) {
      throw new Error(`Pending label ${data.id} not found`);
    }

    // Determine richness based on rating (4-5 = rich)
    const isRich = data.rating >= 4;

    // Insert label with optional turn range
    await db.insert(schema.labels).values({
      fileId: pending.fileId,
      turnStart: data.turnStart ?? null,
      turnEnd: data.turnEnd ?? null,
      isRich,
      notes: data.notes || null,
    });

    // TODO: Handle markers - insert into examples if specified

    // Remove from pending queue
    await db
      .delete(schema.pendingLabels)
      .where(eq(schema.pendingLabels.id, Number(data.id)));

    return { success: true };
  });
