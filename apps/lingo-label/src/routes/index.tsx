import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useState } from "react";

import { StatsPanel, type TabId } from "~/components/stats-panel";
import { getLabels } from "~/server/get-labels";
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
    const [queue, stats, labels] = await Promise.all([
      getQueue(),
      getStats(),
      getLabels(),
    ]);
    return { queue, stats, labels };
  },
  component: QueuePage,
});

function QueuePage() {
  const { queue, stats, labels } = Route.useLoaderData();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<TabId>("queue");
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

      {/* Stats panel as tabs */}
      <div className="mb-8">
        <StatsPanel
          labels={stats.labels}
          queue={stats.queue}
          noise={stats.noise}
          activeTab={activeTab}
          onTabChange={setActiveTab}
        />
      </div>

      {/* Tab content */}
      {activeTab === "queue" && (
        <QueueTab
          items={queue.items}
          isQueuing={isQueuing}
          onQueue={handleQueue}
        />
      )}

      {activeTab === "labeled" && <LabeledTab items={labels.items} />}

      {activeTab === "noise" && (
        <PlaceholderTab
          title="Noise"
          description="Browse conversations flagged as noise by deterministic filters."
        />
      )}

      {activeTab === "uncertain" && (
        <PlaceholderTab
          title="Uncertain"
          description="Review ML predictions with low confidence for human verification."
        />
      )}
    </div>
  );
}

function QueueTab({
  items,
  isQueuing,
  onQueue,
}: {
  items: Array<{
    id: number;
    filename: string;
    turnCount: number;
    source: string;
    turnStart: number | null;
    turnEnd: number | null;
  }>;
  isQueuing: boolean;
  onQueue: (action: "clean" | "noisy" | "random") => void;
}) {
  return (
    <div className="space-y-2">
      {items.length === 0 ? (
        <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center">
          <p className="text-neutral-500">No items in queue</p>
          <div className="mt-4 flex justify-center gap-3">
            <button
              onClick={() => onQueue("clean")}
              disabled={isQueuing}
              className="rounded-md bg-emerald-900/30 px-4 py-2 text-sm text-emerald-400 transition hover:bg-emerald-900/50 disabled:opacity-50"
            >
              Queue clean
            </button>
            <button
              onClick={() => onQueue("noisy")}
              disabled={isQueuing}
              className="rounded-md bg-amber-900/30 px-4 py-2 text-sm text-amber-400 transition hover:bg-amber-900/50 disabled:opacity-50"
            >
              Queue noisy
            </button>
            <button
              onClick={() => onQueue("random")}
              disabled={isQueuing}
              className="rounded-md bg-neutral-800 px-4 py-2 text-sm text-neutral-400 transition hover:bg-neutral-700 disabled:opacity-50"
            >
              Queue random
            </button>
          </div>
        </div>
      ) : (
        items.map((item) => (
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
  );
}

// Rating display helpers
const RATING_LABELS: { [K in 1 | 2 | 3]: { label: string; color: string } } = {
  1: { label: "thin", color: "bg-neutral-800 text-neutral-400" },
  2: { label: "functional", color: "bg-amber-900/30 text-amber-400" },
  3: { label: "rich", color: "bg-emerald-900/30 text-emerald-400" },
};

function LabeledTab({
  items,
}: {
  items: Array<{
    id: number;
    fileId: number;
    filename: string;
    turnStart: number | null;
    turnEnd: number | null;
    rating: number;
    tags: string[];
    notes: string | null;
    createdAt: string | null;
    totalTurns: number;
  }>;
}) {
  if (items.length === 0) {
    return (
      <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center">
        <p className="text-neutral-500">No labels yet</p>
        <p className="mt-2 text-sm text-neutral-600">
          Label some conversations to see them here
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {items.map((item) => {
        const turnRange =
          item.turnStart !== null && item.turnEnd !== null
            ? `turns ${item.turnStart + 1}-${item.turnEnd + 1}`
            : "whole conversation";

        const ratingInfo = RATING_LABELS[item.rating as 1 | 2 | 3];

        return (
          <Link
            key={item.id}
            to="/label/$id"
            params={{ id: String(item.fileId) }}
            search={{ labelId: item.id }}
            className="flex items-center justify-between rounded-lg border border-neutral-800 bg-neutral-900 p-4 transition hover:border-neutral-700 hover:bg-neutral-800/50"
          >
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <p className="font-medium text-neutral-200">{item.filename}</p>
                <span
                  className={`rounded-full px-2 py-0.5 text-xs ${ratingInfo.color}`}
                >
                  {ratingInfo.label}
                </span>
              </div>
              <p className="text-sm text-neutral-500">
                {turnRange} • {item.totalTurns} total turns
              </p>
              {item.tags.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {item.tags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full bg-purple-900/20 px-2 py-0.5 text-xs text-purple-400"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              {item.notes && (
                <p className="mt-1 truncate text-sm text-neutral-600">
                  {item.notes}
                </p>
              )}
            </div>
            <div className="text-sm text-neutral-600">Click to edit</div>
          </Link>
        );
      })}
    </div>
  );
}

function PlaceholderTab({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900 p-8 text-center">
      <p className="text-neutral-400">{title}</p>
      <p className="mt-2 text-sm text-neutral-600">{description}</p>
      <p className="mt-4 text-xs text-neutral-700">Coming soon</p>
    </div>
  );
}
