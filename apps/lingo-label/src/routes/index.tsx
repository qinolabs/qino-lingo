import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useState } from "react";

import { StatsPanel } from "~/components/stats-panel";
import { getQueue } from "~/server/get-queue";
import { getStats } from "~/server/get-stats";
import { queueConversations } from "~/server/queue-actions";
import { seo } from "~/utils/seo";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      ...seo({
        title: "qino-label - Labeling Queue",
        description: "Keyboard-driven conversation labeling",
        keywords: "labeling, conversations, epistemic",
      }),
    ],
  }),
  loader: async () => {
    const [queue, stats] = await Promise.all([getQueue(), getStats()]);
    return { queue, stats };
  },
  component: QueuePage,
});

function QueuePage() {
  const { queue, stats } = Route.useLoaderData();
  const router = useRouter();
  const [isQueuing, setIsQueuing] = useState(false);

  async function handleQueue(action: "clean" | "noisy" | "random") {
    setIsQueuing(true);
    try {
      await queueConversations({ data: { action, limit: 10 } });
      router.invalidate();
    } finally {
      setIsQueuing(false);
    }
  }

  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="mb-8">
        <h1 className="text-2xl font-light tracking-tight text-neutral-100">
          qino-label
        </h1>
      </div>

      {/* Stats panel */}
      <div className="mb-8">
        <StatsPanel
          labels={stats.labels}
          queue={stats.queue}
          noise={stats.noise}
        />
      </div>

      {/* Queue header */}
      <div className="mb-4">
        <h2 className="text-lg font-medium text-neutral-300">Queue</h2>
      </div>

      <div className="space-y-2">
        {queue.items.length === 0 ? (
          <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center">
            <p className="text-neutral-500">No items in queue</p>
            <div className="mt-4 flex justify-center gap-3">
              <button
                onClick={() => handleQueue("clean")}
                disabled={isQueuing}
                className="rounded-md bg-emerald-900/30 px-4 py-2 text-sm text-emerald-400 transition hover:bg-emerald-900/50 disabled:opacity-50"
              >
                Queue clean
              </button>
              <button
                onClick={() => handleQueue("noisy")}
                disabled={isQueuing}
                className="rounded-md bg-amber-900/30 px-4 py-2 text-sm text-amber-400 transition hover:bg-amber-900/50 disabled:opacity-50"
              >
                Queue noisy
              </button>
              <button
                onClick={() => handleQueue("random")}
                disabled={isQueuing}
                className="rounded-md bg-neutral-800 px-4 py-2 text-sm text-neutral-400 transition hover:bg-neutral-700 disabled:opacity-50"
              >
                Queue random
              </button>
            </div>
            <p className="mt-3 text-xs text-neutral-600">
              or use <code className="text-neutral-500">/label</code> skill
            </p>
          </div>
        ) : (
          queue.items.map((item) => (
            <Link
              key={item.id}
              to="/label/$id"
              params={{ id: String(item.id) }}
              className="flex items-center justify-between rounded-lg border border-neutral-800 bg-neutral-900 p-4 transition hover:border-neutral-700 hover:bg-neutral-800/50"
            >
              <div>
                <p className="font-medium text-neutral-200">{item.filename}</p>
                <p className="text-sm text-neutral-500">
                  {item.turnCount} turns • {item.source}
                  {item.turnStart !== null &&
                    item.turnEnd !== null &&
                    ` • turns ${item.turnStart}-${item.turnEnd}`}
                </p>
              </div>
              <div className="text-sm text-neutral-600">Press Enter to label</div>
            </Link>
          ))
        )}
      </div>
    </div>
  );
}
