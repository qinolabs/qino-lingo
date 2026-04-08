"""
Sync calibration data between local corpus.db and remote qino-label D1 database.

Push: local → D1 (sends rounds + items for labeling on phone)
Pull: D1 → local (retrieves labels submitted remotely)

Usage:
    python -m python.qino_lingo.sync push --round 1
    python -m python.qino_lingo.sync pull

Environment:
    QINO_LABEL_API_URL  - Backend URL (e.g. https://qino-label-backend-dev.philhradecs.workers.dev)
    QINO_LABEL_SYNC_KEY - API key for sync endpoints

Status (2026-04-08): the calibration sync workflow is currently unused
and there is no plan to revive it within the persistence-layer
iteration. After Chunk 1 the LOCAL calibration_items table FKs on
filename instead of file_id; this module has been minimally edited to
compile against the new schema, but the wire format with the remote
qino-label backend was NOT renegotiated. Specifically: `fileId` in the
push/pull payloads now carries the filename STRING rather than an
INTEGER id. The remote D1 schema almost certainly expects an integer
and will need its own migration before this sync flow can run again.
Treat the whole module as quarantined until calibration is revived as
its own iteration.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

from .db import get_connection, add_label, DEFAULT_DB_PATH


def get_api_config():
    """Get API URL and sync key from environment."""
    api_url = os.environ.get("QINO_LABEL_API_URL")
    sync_key = os.environ.get("QINO_LABEL_SYNC_KEY")

    if not api_url:
        print("Error: QINO_LABEL_API_URL not set")
        print("  export QINO_LABEL_API_URL=https://qino-label-backend-dev.philhradecs.workers.dev")
        sys.exit(1)

    if not sync_key:
        print("Error: QINO_LABEL_SYNC_KEY not set")
        print("  export QINO_LABEL_SYNC_KEY=your-api-key-here")
        sys.exit(1)

    return api_url, sync_key


def trpc_call(api_url: str, sync_key: str, path: str, input_data=None, method="query"):
    """Make a tRPC call to the backend."""
    headers = {
        "Authorization": f"Bearer {sync_key}",
        "Content-Type": "application/json",
    }

    if method == "query":
        # tRPC queries use GET with input as query param
        params = {}
        if input_data is not None:
            params["input"] = json.dumps(input_data)
        resp = requests.get(f"{api_url}/trpc/{path}", headers=headers, params=params)
    else:
        # tRPC mutations use POST with input in body
        body = {}
        if input_data is not None:
            body = input_data
        resp = requests.post(f"{api_url}/trpc/{path}", headers=headers, json=body)

    if resp.status_code != 200:
        print(f"Error: {resp.status_code} - {resp.text}")
        sys.exit(1)

    data = resp.json()
    if "error" in data:
        print(f"tRPC error: {data['error']}")
        sys.exit(1)

    return data.get("result", {}).get("data", data)


def push_round(round_id: int, db_path: Path = DEFAULT_DB_PATH):
    """Push a calibration round from local corpus.db to the remote D1 database."""
    api_url, sync_key = get_api_config()

    with get_connection(db_path) as conn:
        # Fetch round
        round_row = conn.execute(
            "SELECT * FROM calibration_rounds WHERE id = ?", (round_id,)
        ).fetchone()

        if not round_row:
            print(f"Error: Round {round_id} not found in corpus.db")
            sys.exit(1)

        # Fetch items with file metadata
        items = conn.execute("""
            SELECT ci.*, f.user_word_count, f.substantive_user_turns
            FROM calibration_items ci
            JOIN files f ON ci.filename = f.filename
            WHERE ci.round_id = ?
            ORDER BY ci.position
        """, (round_id,)).fetchall()

    round_data = {
        "id": round_row["id"],
        "themeKey": round_row["theme_key"],
        "themeName": round_row["theme_name"],
        "themeDescription": round_row["theme_description"],
        "status": round_row["status"],
    }

    items_data_final = []
    for item in items:
        # After Chunk 1, calibration_items.filename IS the FK target —
        # no extra lookup needed. Kept the `fileId` field name in the
        # outbound payload for compatibility with the remote D1 schema
        # until that side is also migrated; the value is now the
        # filename string instead of an integer id.
        items_data_final.append({
            "position": item["position"],
            "fileId": item["filename"],
            "filename": item["filename"],
            "excerpt": item["excerpt"],
            "userWordCount": item["user_word_count"],
            "substantiveUserTurns": item["substantive_user_turns"],
        })

    payload = {"round": round_data, "items": items_data_final}

    print(f"Pushing round {round_id} ({round_data['themeName']}) with {len(items_data_final)} items...")
    result = trpc_call(api_url, sync_key, "calibration.sync.push", payload, method="mutation")
    print(f"Done. Round {round_id} pushed to remote.")


def pull_labels(db_path: Path = DEFAULT_DB_PATH):
    """Pull labeled items from remote D1 back to local corpus.db."""
    api_url, sync_key = get_api_config()

    print("Pulling labeled items from remote...")
    items = trpc_call(api_url, sync_key, "calibration.sync.pull")

    if not items:
        print("No labeled items found remotely.")
        return

    synced = 0
    skipped = 0

    with get_connection(db_path) as conn:
        for item in items:
            # Check if this item already has a label locally
            local_item = conn.execute("""
                SELECT ci.label_id FROM calibration_items ci
                WHERE ci.round_id = ? AND ci.position = ?
            """, (item["roundId"], item["position"])).fetchone()

            if local_item and local_item["label_id"]:
                skipped += 1
                continue

            # Parse tags: remote sends comma-separated string
            tags = None
            if item.get("tags"):
                tags = [t.strip() for t in item["tags"].split(",") if t.strip()]

            # Add label to local corpus.db. After Chunk 1, add_label
            # takes filename. The remote payload's fileId field is
            # expected to carry the filename string per the quarantine
            # note at the top of this module.
            label_id = add_label(
                filename=item["fileId"],
                rating=item["rating"],
                tags=tags,
                notes=item.get("notes", ""),
                db_path=db_path,
            )

            # Link label back to calibration item
            conn.execute("""
                UPDATE calibration_items SET label_id = ?
                WHERE round_id = ? AND position = ?
            """, (label_id, item["roundId"], item["position"]))

            synced += 1

        # Update round statuses
        rounds = conn.execute(
            "SELECT DISTINCT round_id FROM calibration_items WHERE label_id IS NOT NULL"
        ).fetchall()

        for round_row in rounds:
            rid = round_row["round_id"]
            total = conn.execute(
                "SELECT COUNT(*) as c FROM calibration_items WHERE round_id = ?", (rid,)
            ).fetchone()["c"]
            labeled = conn.execute(
                "SELECT COUNT(*) as c FROM calibration_items WHERE round_id = ? AND label_id IS NOT NULL",
                (rid,),
            ).fetchone()["c"]

            status = "complete" if labeled >= total else "labeling" if labeled > 0 else "open"
            conn.execute(
                "UPDATE calibration_rounds SET status = ? WHERE id = ?",
                (status, rid),
            )

    print(f"Done. Synced {synced} labels, skipped {skipped} (already labeled locally).")


def main():
    parser = argparse.ArgumentParser(description="Sync calibration data with qino-label")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    push_parser = subparsers.add_parser("push", help="Push round to remote D1")
    push_parser.add_argument("--round", type=int, required=True, help="Round ID to push")

    subparsers.add_parser("pull", help="Pull labels from remote D1")

    args = parser.parse_args()

    if args.command == "push":
        push_round(args.round)
    elif args.command == "pull":
        pull_labels()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
