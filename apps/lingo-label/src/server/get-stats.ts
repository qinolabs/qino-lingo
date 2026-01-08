/**
 * Server function to get labeling stats
 */

import { createServerFn } from "@tanstack/react-start";
import { sql } from "drizzle-orm";
import { getDb, schema } from "./db";

export const getStats = createServerFn({ method: "GET" }).handler(async () => {
  const db = getDb();

  // Get label counts
  const [labelStats] = await db
    .select({
      total: sql<number>`COUNT(*)`,
      rich: sql<number>`SUM(CASE WHEN ${schema.labels.isRich} = 1 THEN 1 ELSE 0 END)`,
    })
    .from(schema.labels);

  // Get queue depth
  const [queueStats] = await db
    .select({
      pending: sql<number>`COUNT(*)`,
    })
    .from(schema.pendingLabels);

  // Get noise prediction counts
  const [noiseStats] = await db
    .select({
      total: sql<number>`COUNT(*)`,
      deterministicNoise: sql<number>`SUM(CASE WHEN deterministic_is_noise = 1 THEN 1 ELSE 0 END)`,
      mlNoise: sql<number>`SUM(CASE WHEN ml_is_noise = 1 THEN 1 ELSE 0 END)`,
      uncertain: sql<number>`SUM(CASE WHEN ml_is_noise IS NULL AND ml_score IS NOT NULL THEN 1 ELSE 0 END)`,
    })
    .from(schema.noisePredictions);

  // Get uncertain predictions queued for review
  const [uncertainQueued] = await db
    .select({
      count: sql<number>`COUNT(*)`,
    })
    .from(schema.pendingLabels)
    .where(sql`${schema.pendingLabels.source} = 'ml_uncertain'`);

  return {
    labels: {
      total: labelStats?.total ?? 0,
      rich: labelStats?.rich ?? 0,
      thin: (labelStats?.total ?? 0) - (labelStats?.rich ?? 0),
    },
    queue: {
      pending: queueStats?.pending ?? 0,
    },
    noise: {
      total: noiseStats?.total ?? 0,
      deterministic: noiseStats?.deterministicNoise ?? 0,
      ml: noiseStats?.mlNoise ?? 0,
      uncertain: noiseStats?.uncertain ?? 0,
      uncertainQueued: uncertainQueued?.count ?? 0,
    },
  };
});
