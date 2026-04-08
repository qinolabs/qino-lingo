/**
 * Domain types for qino-label
 *
 * After Chunk 1 (filename-as-FK), the dependent-table types carry
 * `filename` instead of `fileId`. files.id is still the autoincrement
 * primary key but no longer participates in cross-table joins.
 */

// ============================================================================
// Database Types (matching corpus.db schema)
// ============================================================================

export interface FileRecord {
  id: number;
  filename: string;
  claudeSessionId: string | null;
  date: string | null;
  isAgent: boolean | null;
  fileSize: number | null;
  userTurns: number | null;
  claudeTurns: number | null;
  substantiveUserTurns: number | null;
  userWordCount: number | null;
  claudeWordCount: number | null;
  dialogueDensity: number | null;
  hasCommandExpansion: boolean | null;
  hasReflectiveLanguage: boolean | null;
  sourcePath: string | null;
  status: string | null;
  importedAt: string | null;
  createdAt: string | null;
}

export interface PendingLabel {
  id: number;
  filename: string;
  turnStart: number | null;
  turnEnd: number | null;
  source: "skill" | "qino-model" | "manual" | "sampler";
  context: string | null;
  createdAt: string | null;
}

export interface Label {
  id: number;
  filename: string;
  turnStart: number | null;
  turnEnd: number | null;
  rating: number;
  tags: string | null;
  notes: string | null;
  createdAt: string | null;
}

export interface Marker {
  id: number;
  name: string;
  description: string | null;
  createdAt: string | null;
}

export interface Example {
  id: number;
  markerId: number;
  filename: string;
  turnStart: number | null;
  turnEnd: number | null;
  excerpt: string | null;
  notes: string | null;
  createdAt: string | null;
}

// ============================================================================
// Application Types
// ============================================================================

export interface NoiseInfo {
  deterministic: boolean;
  reason: string | null;
  mlScore: number | null;
  mlIsNoise: boolean | null;
}

export interface ConversationTurn {
  role: "human" | "assistant";
  content: string;
  noise?: NoiseInfo | null;
}

export interface QueueItem extends PendingLabel {
  turnCount: number | null;
}

export interface ConversationDetail {
  id: string;
  filename: string;
  turns: ConversationTurn[];
  existingLabels: Label[];
  availableMarkers: Marker[];
}

// ============================================================================
// Model Feedback Types (Phase 2)
// ============================================================================

export interface ModelFeedback {
  id: number;
  prompt: string;
  modelResponse: string;
  rating: number | null;
  preferredResponse: string | null;
  notes: string | null;
  createdAt: string | null;
}
