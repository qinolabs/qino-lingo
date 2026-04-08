"""
Shared types for validation experiments.
"""

from dataclasses import dataclass, field
from typing import Any
from datetime import datetime


@dataclass
class ValidationResult:
    """Result of a single validation test case."""
    name: str
    passed: bool
    output: str | None = None  # Human-readable output
    error: str | None = None
    duration_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationSummary:
    """Summary statistics for a validation run."""
    total: int
    passed: int
    failed: int

    @property
    def all_passed(self) -> bool:
        return self.failed == 0


@dataclass
class ValidationReport:
    """Complete report from a validation run."""
    validation_id: str
    timestamp: str
    results: list[ValidationResult]
    summary: ValidationSummary

    @classmethod
    def create(cls, validation_id: str, results: list[ValidationResult]) -> "ValidationReport":
        """Create report with computed summary."""
        return cls(
            validation_id=validation_id,
            timestamp=datetime.now().isoformat(),
            results=results,
            summary=ValidationSummary(
                total=len(results),
                passed=sum(1 for r in results if r.passed),
                failed=sum(1 for r in results if not r.passed),
            ),
        )

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "validation_id": self.validation_id,
            "timestamp": self.timestamp,
            "results": [
                {
                    "name": r.name,
                    "passed": r.passed,
                    "output": r.output,
                    "error": r.error,
                    "duration_ms": r.duration_ms,
                    "metadata": r.metadata,
                }
                for r in self.results
            ],
            "summary": {
                "total": self.summary.total,
                "passed": self.summary.passed,
                "failed": self.summary.failed,
            },
        }


@dataclass
class LabeledTurn:
    """A labeled conversation turn."""
    filename: str
    turn_index: int
    role: str  # "human" or "assistant"
    content: str
    rating: int  # 1=thin, 2=functional, 3=rich
    tags: list[str]
    notes: str | None = None
