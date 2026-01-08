import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { ConversationTurn } from "~/components/conversation-turn";
import { getConversation } from "~/server/get-conversation";
import { submitLabel } from "~/server/submit-label";

export const Route = createFileRoute("/label/$id")({
  loader: async ({ params }) => {
    const conversation = await getConversation({ data: { id: params.id } });
    return { conversation };
  },
  component: LabelPage,
});

// Selection state: anchor is where selection started, focus is current position
interface Selection {
  anchor: number;
  focus: number;
}

function getSelectionRange(selection: Selection): { start: number; end: number } {
  return {
    start: Math.min(selection.anchor, selection.focus),
    end: Math.max(selection.anchor, selection.focus),
  };
}

function LabelPage() {
  const { conversation } = Route.useLoaderData();
  const navigate = useNavigate();
  const [selection, setSelection] = useState<Selection>({ anchor: 0, focus: 0 });
  const [rating, setRating] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [selectedMarkers, setSelectedMarkers] = useState<string[]>([]);
  const [expandedTurns, setExpandedTurns] = useState<Set<number>>(new Set());
  const turnRefs = useRef<(HTMLDivElement | null)[]>([]);

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

  const { start: selectionStart, end: selectionEnd } = getSelectionRange(selection);
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
      // Extend selection from anchor to clicked index
      setSelection((prev) => ({ ...prev, focus: index }));
    } else {
      // New selection at clicked index
      setSelection({ anchor: index, focus: index });
    }
  }

  // Keyboard navigation
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      // Ignore if typing in textarea
      if (e.target instanceof HTMLTextAreaElement) return;

      switch (e.key) {
        case "j":
        case "J":
          if (e.shiftKey) {
            // Extend selection down
            setSelection((prev) => ({
              ...prev,
              focus: Math.min(prev.focus + 1, conversation.turns.length - 1),
            }));
          } else {
            // Move selection down
            setSelection((prev) => {
              const next = Math.min(prev.focus + 1, conversation.turns.length - 1);
              return { anchor: next, focus: next };
            });
          }
          break;
        case "k":
        case "K":
          if (e.shiftKey) {
            // Extend selection up
            setSelection((prev) => ({
              ...prev,
              focus: Math.max(prev.focus - 1, 0),
            }));
          } else {
            // Move selection up
            setSelection((prev) => {
              const next = Math.max(prev.focus - 1, 0);
              return { anchor: next, focus: next };
            });
          }
          break;
        case "1":
        case "2":
        case "3":
        case "4":
        case "5":
          setRating(parseInt(e.key));
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
          // If range selected, collapse to single. Otherwise go back.
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
    await submitLabel({
      data: {
        id: conversation.id,
        rating,
        notes,
        markers: selectedMarkers,
        turnStart: selectionStart,
        turnEnd: selectionEnd,
      },
    });
    navigate({ to: "/" });
  }

  async function handleMarkAsNoise() {
    await submitLabel({
      data: {
        id: conversation.id,
        rating: 1, // Lowest rating
        notes: `[NOISE] ${notes}`.trim(),
        markers: [],
        turnStart: selectionStart,
        turnEnd: selectionEnd,
      },
    });
    navigate({ to: "/" });
  }

  return (
    <div className="flex h-full">
      {/* Conversation panel */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="mx-auto max-w-2xl space-y-2">
          {conversation.turns.map((turn, idx) => (
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
                onToggleExpand={() => toggleExpanded(idx)}
                onClick={(e) => handleTurnClick(idx, e.shiftKey)}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Rating panel */}
      <div className="w-80 border-l border-neutral-800 bg-neutral-900/50 p-6">
        <h2 className="mb-2 text-lg font-medium text-neutral-100">
          {conversation.filename}
        </h2>

        {/* Selection indicator */}
        <p className="mb-4 text-sm text-neutral-500">
          {selectionCount === 1
            ? `Turn ${selectionStart + 1}`
            : `Turns ${selectionStart + 1}-${selectionEnd + 1} (${selectionCount} selected)`}
        </p>

        {/* Existing labels */}
        {conversation.existingLabels.length > 0 && (
          <div className="mb-6 rounded-lg border border-amber-900/50 bg-amber-900/10 p-3">
            <p className="text-xs text-amber-500">Previously labeled</p>
            <p className="text-sm text-amber-200">
              {conversation.existingLabels
                .map((l) => (l.isRich ? "rich" : "not rich"))
                .join(", ")}
            </p>
          </div>
        )}

        {/* Rating */}
        <div className="mb-6">
          <label className="mb-2 block text-sm text-neutral-400">
            Richness (1-5)
          </label>
          <div className="flex gap-2">
            {[1, 2, 3, 4, 5].map((n) => (
              <button
                key={n}
                onClick={() => setRating(n)}
                className={`flex h-10 w-10 items-center justify-center rounded-lg border transition ${
                  rating === n
                    ? "border-blue-500 bg-blue-500/20 text-blue-400"
                    : "border-neutral-700 bg-neutral-800 text-neutral-400 hover:border-neutral-600"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
          <p className="mt-2 text-xs text-neutral-600">
            1-2 thin • 3 moderate • 4-5 rich
          </p>
        </div>

        {/* Notes */}
        <div className="mb-6">
          <label className="mb-2 block text-sm text-neutral-400">Notes</label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="What makes this rich/not rich?"
            className="h-24 w-full resize-none rounded-lg border border-neutral-700 bg-neutral-800 p-3 text-sm text-neutral-200 placeholder-neutral-600 focus:border-blue-500 focus:outline-none"
          />
        </div>

        {/* Markers (if any defined) */}
        {conversation.availableMarkers.length > 0 && (
          <div className="mb-6">
            <label className="mb-2 block text-sm text-neutral-400">
              Markers
            </label>
            <div className="flex flex-wrap gap-2">
              {conversation.availableMarkers.map((marker) => (
                <button
                  key={marker.id}
                  onClick={() =>
                    setSelectedMarkers((prev) =>
                      prev.includes(marker.name)
                        ? prev.filter((m) => m !== marker.name)
                        : [...prev, marker.name]
                    )
                  }
                  className={`rounded-full border px-3 py-1 text-xs transition ${
                    selectedMarkers.includes(marker.name)
                      ? "border-purple-500 bg-purple-500/20 text-purple-400"
                      : "border-neutral-700 text-neutral-400 hover:border-neutral-600"
                  }`}
                >
                  {marker.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Submit */}
        <button
          onClick={handleSubmit}
          disabled={rating === null}
          className="w-full rounded-lg bg-blue-600 py-2 text-sm font-medium text-white transition hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Submit Label (Enter)
        </button>

        {/* Mark as noise - for command outputs, system messages, etc */}
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
          <p>Shift+click — select range</p>
          <p>1-5 — set rating</p>
          <p>n — mark as noise</p>
          <p>Enter — submit</p>
          <p>Esc — collapse/back</p>
        </div>
      </div>
    </div>
  );
}
