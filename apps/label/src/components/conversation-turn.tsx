/**
 * Conversation turn component with markdown rendering
 *
 * Asymmetric styling with absolutely positioned avatars:
 * - Human messages: margin-left, avatar floats right
 * - Assistant messages: margin-right, avatar floats left
 */

import { User, Bot, ChevronDown, ChevronUp } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { Button } from "~/ui/components/button";

import type { ConversationTurn as TurnType } from "~/types";

// Collapse messages longer than this (characters)
const COLLAPSE_THRESHOLD = 600;
const COLLAPSED_HEIGHT = 150;

interface ConversationTurnProps {
  turn: TurnType;
  index: number;
  isInRange: boolean;
  isFocus: boolean;
  isExpanded: boolean;
  onToggleExpand: () => void;
  onClick?: (e: React.MouseEvent) => void;
}

export function ConversationTurn({
  turn,
  index,
  isInRange,
  isFocus,
  isExpanded,
  onToggleExpand,
  onClick,
}: ConversationTurnProps) {
  const isHuman = turn.role === "human";
  const isLong = turn.content.length > COLLAPSE_THRESHOLD;
  const shouldCollapse = isLong && !isExpanded;

  // Selection styling
  const selectionClasses = isInRange
    ? isFocus
      ? "bg-blue-950/10"
      : "bg-blue-950/5"
    : "";

  // Toggle link for long messages - shows at top when expanded for easy access
  function ExpandToggle({ position = "bottom" }: { position?: "top" | "bottom" }) {
    if (!isLong) return null;
    if (position === "top" && !isExpanded) return null;
    if (position === "bottom" && isExpanded) return null;

    return (
      <Button
        variant="link"
        size="sm"
        onClick={(e) => {
          e.stopPropagation();
          onToggleExpand();
        }}
        className={`h-auto p-0 text-neutral-500 ${position === "top" ? "mb-3" : "mt-2"}`}
      >
        {isExpanded ? (
          <>
            <ChevronUp className="size-3" />
            collapse
          </>
        ) : (
          <>
            <ChevronDown className="size-3" />
            full message
          </>
        )}
      </Button>
    );
  }

  // Human messages: pushed right, avatar on right
  if (isHuman) {
    return (
      <div className="group relative ml-12 mr-6">
        {/* Avatar - absolute right */}
        <div className="absolute -right-11 top-3 flex h-8 w-8 items-center justify-center rounded-full bg-amber-500/10">
          <User className="h-4 w-4 text-amber-500/70" />
        </div>

        <div
          onClick={onClick}
          className={`
            relative cursor-pointer rounded-lg py-3 px-5 transition-colors
            ${selectionClasses}
            ${isInRange ? "hover:bg-blue-950/15" : "hover:bg-neutral-800/5"}
          `}
        >
          {/* Selection accent */}
          {isInRange && (
            <div
              className={`
                absolute left-0 top-2 bottom-2 w-0.5 rounded-full
                ${isFocus ? "bg-blue-500/40" : "bg-blue-500/20"}
              `}
            />
          )}

          <div className="flex items-start gap-3">
            <span
              className={`
                text-xs font-medium tabular-nums pt-0.5
                ${isInRange ? "text-blue-400/70" : "text-neutral-600"}
              `}
            >
              {index + 1}
            </span>

            <div className="flex-1 text-[15px] leading-relaxed text-neutral-300 [&_hr]:hidden">
              <ExpandToggle position="top" />
              <div
                className={`relative ${shouldCollapse ? "overflow-hidden" : ""}`}
                style={shouldCollapse ? { maxHeight: COLLAPSED_HEIGHT } : undefined}
              >
                <Markdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ children }) => <p className="my-1">{children}</p>,
                  }}
                >
                  {turn.content}
                </Markdown>
                {shouldCollapse && (
                  <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-black/60 to-transparent" />
                )}
              </div>
              <ExpandToggle position="bottom" />
            </div>
          </div>
        </div>
      </div>
    );
  }

  // Assistant messages: stay left, avatar on left
  return (
    <div className="group relative ml-6 mr-12">
      {/* Avatar - absolute left */}
      <div className="absolute -left-11 top-5 flex h-8 w-8 items-center justify-center rounded-full bg-violet-500/10">
        <Bot className="h-4 w-4 text-violet-400/70" />
      </div>

      <div
        onClick={onClick}
        className={`
          noise-texture relative cursor-pointer transition-colors rounded-lg
          bg-neutral-900/40
          ${selectionClasses}
          ${isInRange ? "hover:bg-blue-950/15" : "hover:bg-neutral-800/10"}
        `}
      >
        {/* Selection accent */}
        {isInRange && (
          <div
            className={`
              absolute left-0 top-3 bottom-3 w-0.5 rounded-full
              ${isFocus ? "bg-blue-500/40" : "bg-blue-500/20"}
            `}
          />
        )}

        <div className="py-5 pl-5 pr-4">
          {/* Header row */}
          <div className="mb-3 flex items-center gap-2">
            <span
              className={`
                text-xs font-medium tabular-nums
                ${isInRange ? "text-blue-400/70" : "text-neutral-600"}
              `}
            >
              {index + 1}
            </span>
            <span className="text-[10px] font-medium uppercase tracking-wider text-violet-500/40">
              Assistant
            </span>

            {/* Noise indicator */}
            {turn.noise?.deterministic && (
              <span
                className="ml-auto rounded bg-amber-900/20 px-1.5 py-0.5 text-[10px] text-amber-500/60"
                title={`Flagged as noise: ${turn.noise.reason}`}
              >
                {turn.noise.reason}
              </span>
            )}
            {turn.noise &&
              typeof turn.noise.mlScore === "number" &&
              !turn.noise.deterministic && (
                <span
                  className={`ml-auto rounded px-1.5 py-0.5 text-[10px] ${
                    turn.noise.mlScore > 0.7
                      ? "bg-amber-900/20 text-amber-500/60"
                      : turn.noise.mlScore > 0.3
                        ? "bg-neutral-800/50 text-neutral-500"
                        : "bg-emerald-900/10 text-emerald-600/50"
                  }`}
                  title={`ML confidence: ${(turn.noise.mlScore * 100).toFixed(0)}% noise`}
                >
                  {turn.noise.mlScore > 0.7
                    ? "likely noise"
                    : turn.noise.mlScore > 0.3
                      ? "uncertain"
                      : "signal"}
                </span>
              )}
          </div>

          {/* Content */}
          <div
            className={`
              prose prose-lg prose-invert
              prose-p:text-neutral-400 prose-p:break-words
              prose-headings:text-neutral-300
              prose-strong:text-neutral-300
              prose-em:text-neutral-400
              prose-code:text-amber-400/80 prose-code:bg-neutral-800/50 prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded prose-code:text-sm prose-code:before:content-none prose-code:after:content-none
              prose-pre:bg-neutral-800/30 prose-pre:border prose-pre:border-neutral-700/20
              prose-li:text-neutral-400
              prose-th:text-neutral-400 prose-th:border-neutral-700/50
              prose-td:border-neutral-700/50
              prose-a:text-blue-400/80 prose-a:no-underline hover:prose-a:underline
              prose-blockquote:border-neutral-700 prose-blockquote:text-neutral-500
              [&_hr]:hidden
            `}
          >
            <ExpandToggle position="top" />
            <div
              className={`relative ${shouldCollapse ? "overflow-hidden" : ""}`}
              style={shouldCollapse ? { maxHeight: COLLAPSED_HEIGHT } : undefined}
            >
              <Markdown remarkPlugins={[remarkGfm]}>{turn.content}</Markdown>
              {shouldCollapse && (
                <div className="pointer-events-none absolute inset-x-0 bottom-0 h-12 bg-gradient-to-t from-black/60 to-transparent" />
              )}
            </div>
            <ExpandToggle position="bottom" />
          </div>
        </div>
      </div>
    </div>
  );
}
