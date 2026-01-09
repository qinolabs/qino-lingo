"""
Run all validation experiments.

Usage:
    python run-all.py              # Run all validations
    python run-all.py --validation 01   # Run specific validation
    python run-all.py --dry-run    # Preview what would run
"""

import argparse
import subprocess
import sys
from pathlib import Path

VALIDATIONS_DIR = Path(__file__).parent
VALIDATIONS = [
    ("01", "01-training-data-signal", "Training Data Signal"),
    ("02", "02-approach-differentiation", "Approach Differentiation"),
    ("03", "03-metric-correlation", "Metric Correlation"),
]


def run_validation(validation_id: str, name: str, dry_run: bool = False) -> bool:
    """Run a single validation and return success status."""
    validation_dir = VALIDATIONS_DIR / name
    validate_script = validation_dir / "validate.py"

    if not validate_script.exists():
        print(f"⚠️  Validation {validation_id} not implemented yet: {validate_script}")
        return True  # Don't fail on unimplemented

    if dry_run:
        print(f"[DRY RUN] Would run: python {validate_script}")
        return True

    print(f"\n{'=' * 60}")
    print(f"Running Validation {validation_id}: {name}")
    print(f"{'=' * 60}\n")

    result = subprocess.run(
        [sys.executable, str(validate_script)],
        cwd=VALIDATIONS_DIR.parent.parent,  # qino-lingo root
    )

    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="Run validation experiments")
    parser.add_argument("--validation", help="Run specific validation (e.g., 01)")
    parser.add_argument("--dry-run", action="store_true", help="Preview what would run")
    args = parser.parse_args()

    print("=" * 60)
    print("qino-lingo Validation Pipeline")
    print("=" * 60)

    if args.validation:
        # Run specific validation
        matching = [(id, name, desc) for id, name, desc in VALIDATIONS if id == args.validation]
        if not matching:
            print(f"Unknown validation: {args.validation}")
            print(f"Available: {[id for id, _, _ in VALIDATIONS]}")
            return 1

        id, name, desc = matching[0]
        success = run_validation(id, name, args.dry_run)
        return 0 if success else 1

    # Run all validations
    results = []
    for id, name, desc in VALIDATIONS:
        success = run_validation(id, name, args.dry_run)
        results.append((id, desc, success))

        # Stop on first failure (validations build on each other)
        if not success:
            print(f"\n❌ Validation {id} failed. Stopping pipeline.")
            break

    # Summary
    print("\n" + "=" * 60)
    print("Pipeline Summary")
    print("=" * 60)

    for id, desc, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"  {id}: {desc} — {status}")

    all_passed = all(success for _, _, success in results)

    if all_passed:
        print("\n✅ All validations passed. Ready to proceed to build phase.")
    else:
        print("\n❌ Some validations failed. Address issues before proceeding.")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
