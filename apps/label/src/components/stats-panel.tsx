/**
 * Stats panel component
 *
 * Displays gentle stats without pressure — inform, don't instruct.
 */

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
}

function StatCard({
  value,
  label,
  sublabel,
}: {
  value: number;
  label: string;
  sublabel?: string;
}) {
  return (
    <div className="rounded-lg border border-neutral-800 bg-neutral-900/50 p-4 text-center">
      <div className="text-2xl font-light text-neutral-100">{value}</div>
      <div className="mt-1 text-sm text-neutral-500">{label}</div>
      {sublabel && (
        <div className="mt-0.5 text-xs text-neutral-600">{sublabel}</div>
      )}
    </div>
  );
}

export function StatsPanel({ labels, queue, noise }: StatsProps) {
  return (
    <div className="grid grid-cols-4 gap-3">
      <StatCard
        value={queue.pending}
        label="to label"
        sublabel={queue.pending > 0 ? "in queue" : undefined}
      />
      <StatCard
        value={labels.total}
        label="labeled"
        sublabel={labels.rich > 0 ? `${labels.rich} rich` : undefined}
      />
      <StatCard
        value={noise.deterministic}
        label="noise"
        sublabel="flagged"
      />
      <StatCard
        value={noise.uncertain}
        label="uncertain"
        sublabel={
          noise.uncertainQueued > 0
            ? `${noise.uncertainQueued} queued`
            : "ML predictions"
        }
      />
    </div>
  );
}
