import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { z } from "zod";

import { ConversationTurn } from "~/components/conversation-turn";
import { getConversation } from "~/server/get-conversation";
import { submitLabel } from "~/server/submit-label";

const searchSchema = z.object({
  labelId: z.number().optional(),
});

export const Route = createFileRoute("/label/$id")({
  validateSearch: searchSchema,
  loaderDeps: ({ search }) => ({ labelId: search.labelId }),
  loader: async ({ params, deps }) => {
    const conversation = await getConversation({
      data: { id: params.id, labelId: deps.labelId },
    });
    return { conversation };
  },
  component: LabelPage,
});

// 3-tier rating system
const RATING_TIERS = [
  { value: 1, label: "Thin", shortcut: "1", color: "neutral" },
  { value: 2, label: "Functional", shortcut: "2", color: "amber" },
  { value: 3, label: "Rich", shortcut: "3", color: "emerald" },
] as const;

// Secondary tags for capturing "why"
const SECONDARY_TAGS = [
  { id: "abductive", label: "Abductive leap" },
  { id: "synthesis", label: "Synthesis" },
  { id: "meta", label: "Meta-reflection" },
  { id: "example", label: "Concrete example" },
  { id: "scaffold", label: "Scaffolding" },
] as const;

// Selection state: anchor is where selection started, focus is current position
interface Selection {
  anchor: number;
  focus: number;
}

// Local label data for a turn range
interface LocalLabel {
  rating: number;
  tags: string[];
  notes: string;
}

function getSelectionRange(selection: Selection): { start: number; end: number } {
  return {
    start: Math.min(selection.anchor, selection.focus),
    end: Math.max(selection.anchor, selection.focus),
  };
}

function rangeKey(start: number, end: number): string {
  return `${start}-${end}`;
}

function LabelPage() {
  const { conversation } = Route.useLoaderData();
  const search = Route.useSearch();
  const navigate = useNavigate();
  const isEditMode = search.labelId !== undefined;

  // Initialize selection from editing label's turn range
  const editingLabel = conversation.editingLabel;
  const initialSelection =
    editingLabel !== null &&
    editingLabel.turnStart !== null &&
    editingLabel.turnEnd !== null
      ? {
          anchor: editingLabel.turnStart,
          focus: editingLabel.turnEnd,
        }
      : { anchor: 0, focus: 0 };

  const [selection, setSelection] = useState<Selection>(initialSelection);

  // Initialize local labels from existing DB labels
  const [localLabels, setLocalLabels] = useState<Map<string, LocalLabel>>(() => {
    const map = new Map<string, LocalLabel>();
    for (const label of conversation.existingLabels) {
      const key = rangeKey(label.turnStart ?? 0, label.turnEnd ?? 0);
      map.set(key, {
        rating: label.rating,
        tags: label.tags ? JSON.parse(label.tags) : [],
        notes: label.notes ?? "",
      });
    }
    // Also add editing label if present
    if (
      editingLabel !== null &&
      editingLabel.turnStart !== null &&
      editingLabel.turnEnd !== null
    ) {
      const key = rangeKey(editingLabel.turnStart, editingLabel.turnEnd);
      if (!map.has(key)) {
        map.set(key, {
          rating: editingLabel.rating ?? 1,
          tags: editingLabel.tags ? JSON.parse(editingLabel.tags) : [],
          notes: editingLabel.notes ?? "",
        });
      }
    }
    return map;
  });

  // Current sidebar state
  const [rating, setRating] = useState<number | null>(editingLabel?.rating ?? null);
  const [selectedTags, setSelectedTags] = useState<string[]>(
    editingLabel?.tags ? JSON.parse(editingLabel.tags) : []
  );
  const [notes, setNotes] = useState(editingLabel?.notes ?? "");

  const [expandedTurns, setExpandedTurns] = useState<Set<number>>(new Set());
  const turnRefs = useRef<(HTMLDivElement | null)[]>([]);

  const { start: selectionStart, end: selectionEnd } = getSelectionRange(selection);
  const currentKey = rangeKey(selectionStart, selectionEnd);

  // Sync sidebar when selection changes - load existing label if any
  useEffect(() => {
    const existingLabel = localLabels.get(currentKey);
    if (existingLabel) {
      setRating(existingLabel.rating);
      setSelectedTags(existingLabel.tags);
      setNotes(existingLabel.notes);
    } else {
      // Reset to defaults for unlabeled range
      setRating(null);
      setSelectedTags([]);
      setNotes("");
    }
  }, [currentKey, localLabels]);

  // Update local labels when rating changes
  function handleRatingChange(newRating: number) {
    setRating(newRating);
    setLocalLabels((prev) => {
      const next = new Map(prev);
      const existing = next.get(currentKey);
      next.set(currentKey, {
        rating: newRating,
        tags: existing?.tags ?? selectedTags,
        notes: existing?.notes ?? notes,
      });
      return next;
    });
  }

  // Update local labels when tags change
  function handleTagToggle(tagId: string) {
    const newTags = selectedTags.includes(tagId)
      ? selectedTags.filter((t) => t !== tagId)
      : [...selectedTags, tagId];
    setSelectedTags(newTags);
    if (rating !== null) {
      setLocalLabels((prev) => {
        const next = new Map(prev);
        next.set(currentKey, {
          rating,
          tags: newTags,
          notes,
        });
        return next;
      });
    }
  }

  // Update local labels when notes change
  function handleNotesChange(newNotes: string) {
    setNotes(newNotes);
    if (rating !== null) {
      setLocalLabels((prev) => {
        const next = new Map(prev);
        next.set(currentKey, {
          rating,
          tags: selectedTags,
          notes: newNotes,
        });
        return next;
      });
    }
  }

  // Find label info for a turn (for visual indicators)
  function getLabelForTurn(turnIdx: number): { rating: number; tagCount: number } | null {
    for (const [key, label] of localLabels) {
      const parts = key.split("-");
      const start = Number(parts[0]);
      const end = Number(parts[1]);
      if (!isNaN(start) && !isNaN(end) && turnIdx >= start && turnIdx <= end) {
        return { rating: label.rating, tagCount: label.tags.length };
      }
    }
    return null;
  }

  function toggleExpanded(index: number) {
    setExpandedTurns((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  const selectionCount = selectionEnd - selectionStart + 1;

  // Scroll focus turn into view - use "nearest" to avoid jumping for long messages
  useEffect(() => {
    const focusTurnEl = turnRefs.current[selection.focus];
    if (focusTurnEl) {
      focusTurnEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [selection.focus]);

  // Handle click with optional shift for range selection
  function handleTurnClick(index: number, shiftKey: boolean) {
    if (shiftKey) {
      setSelection((prev) => ({ ...prev, focus: index }));
    } else {
      setSelection({ anchor: index, focus: index });
    }
  }

  // Keyboard navigation
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.target instanceof HTMLTextAreaElement) return;

      switch (e.key) {
        case "j":
        case "J":
          if (e.shiftKey) {
            setSelection((prev) => ({
              ...prev,
              focus: Math.min(prev.focus + 1, conversation.turns.length - 1),
            }));
          } else {
            setSelection((prev) => {
              const next = Math.min(prev.focus + 1, conversation.turns.length - 1);
              return { anchor: next, focus: next };
            });
          }
          break;
        case "k":
        case "K":
          if (e.shiftKey) {
            setSelection((prev) => ({
              ...prev,
              focus: Math.max(prev.focus - 1, 0),
            }));
          } else {
            setSelection((prev) => {
              const next = Math.max(prev.focus - 1, 0);
              return { anchor: next, focus: next };
            });
          }
          break;
        case "1":
          handleRatingChange(1);
          break;
        case "2":
          handleRatingChange(2);
          break;
        case "3":
          handleRatingChange(3);
          break;
        case "n":
        case "N":
          handleMarkAsNoise();
          break;
        case "Enter":
          if (rating !== null) {
            handleSubmit();
          }
          break;
        case "Escape":
          if (selectionStart !== selectionEnd) {
            setSelection({ anchor: selection.focus, focus: selection.focus });
          } else {
            navigate({ to: "/" });
          }
          break;
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [conversation.turns.length, rating, navigate, selection, selectionStart, selectionEnd]);

  async function handleSubmit() {
    if (rating === null) return;
    const result = await submitLabel({
      data: {
        id: conversation.id,
        fileId: conversation.fileId,
        rating,
        tags: selectedTags,
        notes,
        turnStart: selectionStart,
        turnEnd: selectionEnd,
        isEditMode,
      },
    });
    if (result.nextId !== null) {
      navigate({ to: "/label/$id", params: { id: String(result.nextId) } });
    } else {
      navigate({ to: "/" });
    }
  }

  async function handleMarkAsNoise() {
    const result = await submitLabel({
      data: {
        id: conversation.id,
        fileId: conversation.fileId,
        rating: 1,
        tags: ["noise"],
        notes: notes ? `[NOISE] ${notes}` : "[NOISE]",
        turnStart: selectionStart,
        turnEnd: selectionEnd,
        isEditMode,
      },
    });
    if (result.nextId !== null) {
      navigate({ to: "/label/$id", params: { id: String(result.nextId) } });
    } else {
      navigate({ to: "/" });
    }
  }

  return (
    <div className="flex h-full">
      {/* Conversation panel */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-2xl space-y-2">
          {conversation.turns.map((turn, idx) => {
            const labelInfo = getLabelForTurn(idx);
            return (
              <div
                key={idx}
                ref={(el) => {
                  turnRefs.current[idx] = el;
                }}
              >
                <ConversationTurn
                  turn={turn}
                  index={idx}
                  isInRange={idx >= selectionStart && idx <= selectionEnd}
                  isFocus={idx === selection.focus}
                  isExpanded={expandedTurns.has(idx)}
                  labelRating={labelInfo?.rating}
                  labelTagCount={labelInfo?.tagCount}
                  onToggleExpand={() => toggleExpanded(idx)}
                  onClick={(e) => handleTurnClick(idx, e.shiftKey)}
                />
              </div>
            );
          })}
        </div>
      </div>

      {/* Rating panel */}
      <div className="w-80 border-l border-neutral-800 bg-neutral-900/50 p-6">
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-lg font-medium text-neutral-100">
            {conversation.filename}
          </h2>
          {isEditMode && (
            <span className="rounded-full bg-amber-900/30 px-2 py-0.5 text-xs text-amber-400">
              editing
            </span>
          )}
        </div>

        {/* Selection indicator */}
        <p className="mb-4 text-sm text-neutral-500">
          {selectionCount === 1
            ? `Turn ${selectionStart + 1}`
            : `Turns ${selectionStart + 1}-${selectionEnd + 1} (${selectionCount} selected)`}
        </p>

        {/* Existing labels (show only in queue mode) */}
        {!isEditMode && conversation.existingLabels.length > 0 && (
          <div className="mb-6 rounded-lg border border-amber-900/50 bg-amber-900/10 p-3">
            <p className="text-xs text-amber-500">Previously labeled</p>
            <p className="text-sm text-amber-200">
              {conversation.existingLabels
                .map((l) =>
                  l.rating === 3 ? "rich" : l.rating === 2 ? "functional" : "thin"
                )
                .join(", ")}
            </p>
          </div>
        )}

        {/* 3-tier Rating */}
        <div className="mb-6">
          <label className="mb-2 block text-sm text-neutral-400">
            Signal Quality
          </label>
          <div className="flex gap-2">
            {RATING_TIERS.map((tier) => {
              const isSelected = rating === tier.value;
              const colorClasses = {
                neutral: isSelected
                  ? "border-neutral-500 bg-neutral-500/20 text-neutral-300"
                  : "border-neutral-700 bg-neutral-800 text-neutral-400 hover:border-neutral-600",
                amber: isSelected
                  ? "border-amber-500 bg-amber-500/20 text-amber-400"
                  : "border-neutral-700 bg-neutral-800 text-neutral-400 hover:border-neutral-600",
                emerald: isSelected
                  ? "border-emerald-500 bg-emerald-500/20 text-emerald-400"
                  : "border-neutral-700 bg-neutral-800 text-neutral-400 hover:border-neutral-600",
              };
              return (
                <button
                  key={tier.value}
                  onClick={() => handleRatingChange(tier.value)}
                  className={`flex flex-1 flex-col items-center justify-center rounded-lg border p-3 transition ${colorClasses[tier.color]}`}
                >
                  <span className="text-xs opacity-60">{tier.shortcut}</span>
                  <span className="text-sm font-medium">{tier.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Secondary Tags */}
        <div className="mb-6">
          <label className="mb-2 block text-sm text-neutral-400">
            Tags <span className="text-neutral-600">(optional)</span>
          </label>
          <div className="flex flex-wrap gap-2">
            {SECONDARY_TAGS.map((tag) => (
              <button
                key={tag.id}
                onClick={() => handleTagToggle(tag.id)}
                className={`rounded-full border px-3 py-1 text-xs transition ${
                  selectedTags.includes(tag.id)
                    ? "border-purple-500 bg-purple-500/20 text-purple-400"
                    : "border-neutral-700 text-neutral-500 hover:border-neutral-600 hover:text-neutral-400"
                }`}
              >
                {tag.label}
              </button>
            ))}
          </div>
        </div>

        {/* Notes */}
        <div className="mb-6">
          <label className="mb-2 block text-sm text-neutral-400">
            Notes <span className="text-neutral-600">(optional)</span>
          </label>
          <textarea
            value={notes}
            onChange={(e) => handleNotesChange(e.target.value)}
            placeholder="Why this rating?"
            className="h-20 w-full resize-none rounded-lg border border-neutral-700 bg-neutral-800 p-3 text-sm text-neutral-200 placeholder-neutral-600 focus:border-blue-500 focus:outline-none"
          />
        </div>

        {/* Submit */}
        <button
          onClick={handleSubmit}
          disabled={rating === null}
          className="w-full rounded-lg bg-blue-600 py-2 text-sm font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isEditMode ? "Update Label (Enter)" : "Submit Label (Enter)"}
        </button>

        {/* Mark as noise shortcut */}
        <button
          onClick={handleMarkAsNoise}
          className="mt-2 w-full rounded-lg border border-neutral-700 bg-neutral-800 py-2 text-sm font-medium text-neutral-400 transition hover:border-neutral-600 hover:text-neutral-300"
        >
          Mark as Noise (n)
        </button>

        {/* Keyboard hints */}
        <div className="mt-6 space-y-1 text-xs text-neutral-600">
          <p>j/k — navigate turns</p>
          <p>Shift+j/k — extend selection</p>
          <p>1 thin • 2 functional • 3 rich</p>
          <p>n — mark as noise</p>
          <p>Enter — submit</p>
          <p>Esc — collapse/back</p>
        </div>
      </div>
    </div>
  );
}
