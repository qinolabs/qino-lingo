/**
 * Stats panel component - acts as navigation tabs
 *
 * Displays stats that double as clickable tabs for navigation.
 */

export type TabId = "queue" | "labeled" | "noise" | "uncertain";

interface StatsProps {
  labels: {
    total: number;
    rich: number;
    thin: number;
  };
  queue: {
    pending: number;
  };
  noise: {
    total: number;
    deterministic: number;
    ml: number;
    uncertain: number;
    uncertainQueued: number;
  };
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
}

function StatTab({
  value,
  label,
  sublabel,
  isActive,
  onClick,
}: {
  value: number;
  label: string;
  sublabel?: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg border p-4 text-center transition ${
        isActive
          ? "border-blue-500/50 bg-blue-500/10"
          : "border-neutral-800 bg-neutral-900/50 hover:border-neutral-700 hover:bg-neutral-800/50"
      }`}
    >
      <div
        className={`text-2xl font-light ${isActive ? "text-blue-400" : "text-neutral-100"}`}
      >
        {value}
      </div>
      <div
        className={`mt-1 text-sm ${isActive ? "text-blue-400/70" : "text-neutral-500"}`}
      >
        {label}
      </div>
      {sublabel && (
        <div
          className={`mt-0.5 text-xs ${isActive ? "text-blue-400/50" : "text-neutral-600"}`}
        >
          {sublabel}
        </div>
      )}
    </button>
  );
}

export function StatsPanel({
  labels,
  queue,
  noise,
  activeTab,
  onTabChange,
}: StatsProps) {
  return (
    <div className="grid grid-cols-4 gap-3">
      <StatTab
        value={queue.pending}
        label="to label"
        sublabel={queue.pending > 0 ? "in queue" : undefined}
        isActive={activeTab === "queue"}
        onClick={() => onTabChange("queue")}
      />
      <StatTab
        value={labels.total}
        label="labeled"
        sublabel={labels.rich > 0 ? `${labels.rich} rich` : undefined}
        isActive={activeTab === "labeled"}
        onClick={() => onTabChange("labeled")}
      />
      <StatTab
        value={noise.deterministic}
        label="noise"
        sublabel="flagged"
        isActive={activeTab === "noise"}
        onClick={() => onTabChange("noise")}
      />
      <StatTab
        value={noise.uncertain}
        label="uncertain"
        sublabel={
          noise.uncertainQueued > 0
            ? `${noise.uncertainQueued} queued`
            : "ML predictions"
        }
        isActive={activeTab === "uncertain"}
        onClick={() => onTabChange("uncertain")}
      />
    </div>
  );
}
