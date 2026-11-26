"""
mongo_export.py — Interactive MongoDB collection export tool.

Usage:
    python scripts/mongo_export.py

Environment variables (same as the app):
    MONGO_USERNAME, MONGO_PASSWORD, MONGO_HOST, MONGO_PORT

You can also pass connection details as arguments:
    python scripts/mongo_export.py --host localhost --port 27017 --username admin --password pass

Options:
    --host       Mongo host (default: $MONGO_HOST or localhost)
    --port       Mongo port (default: $MONGO_PORT or 27017)
    --username   Mongo username (default: $MONGO_USERNAME)
    --password   Mongo password (default: $MONGO_PASSWORD)
    --auth-db    Authentication database (default: $MONGO_AUTH_DB or admin)
    --output     Output JSON file path (default: prompted interactively)
    --no-prompt  Non-interactive: export all listed collections with no filter (useful for scripting)
"""

import argparse
import json
import os
import sys
import getpass
from datetime import datetime, timezone

try:
    from pymongo import MongoClient
    from bson import ObjectId
except ImportError:
    print("pymongo is required. Run: pip install pymongo")
    sys.exit(1)


# --- Default export plan grouped by database ---
# Modes:
#   - "all": export all docs in collection
#   - "query": export docs that match the provided filter
#   - "empty": export an intentionally empty list for that collection
DEFAULT_EXPORT_PLAN = {
    "byoint_core_config": {
        "basicconfigs": {"mode": "all"},
        "datapull_templates": {"mode": "query", "query": {"template_type": "builtin"}},
        "data_types": {"mode": "query", "query": {"type": "builtin"}},
        "datapull_secrets": {"mode": "empty"},
        "data_enrichments": {"mode": "query", "query": {"data_enrichments": "builtin"}},
        "output_guardrails": {"mode": "query", "query": {"type": "builtin"}},
        "tags": {"mode": "query", "query": {"type": "builtin"}},
    },
    "byoint_core_data": {
        "datapull_workflows": {"mode": "empty"},
        "api_audit_logs": {"mode": "empty"},
        "apikeys": {"mode": "empty"},
        "browser_sessions": {"mode": "empty"},  
        "indicators": {"mode": "empty"},
        "outputs": {"mode": "empty"},
        "users": {"mode": "empty"},
    },
     "byoint_opslogs": {
        "datapull_executions": {"mode": "empty"},
        "datapull_jobs": {"mode": "empty"},
        "datapull_metrics": {"mode": "empty"},
        "indicator_activity_logs": {"mode": "empty"},
        "indicator_logs": {"mode": "empty"},
        "platform_change_logs": {"mode": "empty"},
        "scheduler_logs": {"mode": "empty"},
     },
}


class MongoJsonEncoder(json.JSONEncoder):
    """Serialize MongoDB-specific types to JSON-safe values."""

    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, bytes):
            import base64
            return base64.b64encode(obj).decode("utf-8")
        return super().default(obj)


def _is_auth_error(exc):
    msg = str(exc).lower()
    return (
        "requires authentication" in msg
        or "not authorized" in msg
        or "unauthorized" in msg
        or "authentication failed" in msg
    )


def _connect(host, port, username, password, auth_db):
    try:
        port = int(port)
        kwargs = dict(
            host=host,
            port=port,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            socketTimeoutMS=10000,
        )
        if username:
            kwargs["username"] = username
            kwargs["password"] = password
            kwargs["authSource"] = auth_db

        client = MongoClient(**kwargs)
        client.admin.command("ping")
        return client
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)


def _list_databases(client):
    try:
        return sorted(client.list_database_names())
    except Exception as e:
        print(f"Could not list databases: {e}")
        return []


def _list_collections(client, db_name):
    try:
        return sorted(client[db_name].list_collection_names())
    except Exception as e:
        print(f"Could not list collections for {db_name}: {e}")
        return []


def _prompt_choice(label, options, allow_all=True, allow_none=False):
    """Display a numbered menu and return the selected indices."""
    print(f"\n{label}")
    for i, opt in enumerate(options, 1):
        print(f"  [{i:>2}] {opt}")

    extras = []
    if allow_all:
        extras.append("  [ A] All")
    if allow_none:
        extras.append("  [ N] None / skip")
    if extras:
        print("\n".join(extras))

    while True:
        raw = input("  Select (comma-separated numbers, A, or N): ").strip()
        if allow_all and raw.upper() == "A":
            return list(range(len(options)))
        if allow_none and raw.upper() == "N":
            return []
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        indices = []
        valid = True
        for part in parts:
            try:
                idx = int(part) - 1
                if idx < 0 or idx >= len(options):
                    raise ValueError
                indices.append(idx)
            except ValueError:
                print(f"  Invalid choice: '{part}'. Enter numbers between 1 and {len(options)}, A, or N.")
                valid = False
                break
        if valid and indices:
            return indices


def _prompt_query(db_name, coll_name):
    """Ask for optional MongoDB filter. Empty = all, EMPTY = empty collection export."""
    print(f"\n  Filter for {db_name}.{coll_name}")
    print("  Enter a JSON query filter, press Enter to export ALL docs, or type EMPTY for empty export.")
    print("  Examples:  {}   {\"type\": \"builtin\"}   {\"module\": \"core\"}   EMPTY")

    while True:
        raw = input("  Query: ").strip()
        if not raw:
            return {"mode": "all", "query": {}}
        if raw.upper() == "EMPTY":
            return {"mode": "empty", "query": {}}
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("Query must be a JSON object")
            return {"mode": "query", "query": parsed}
        except (json.JSONDecodeError, ValueError) as e:
            print(f"  Invalid JSON: {e}. Try again.")


def _prompt_limit(db_name, coll_name, collection_obj, query):
    """Ask for an optional document limit."""
    try:
        total = collection_obj.count_documents(query)
    except Exception:
        total = "?"
    print(f"  Matched documents: {total}")
    raw = input(f"  Max documents to export (Enter = all): ").strip()
    if not raw:
        return None
    try:
        limit = int(raw)
        if limit <= 0:
            raise ValueError
        return limit
    except ValueError:
        print("  Invalid number, exporting all.")
        return None


def _export_collection(db, coll_name, query, limit):
    """Fetch and return documents as a list of dicts."""
    coll = db[coll_name]
    cursor = coll.find(query)
    if limit:
        cursor = cursor.limit(limit)
    return list(cursor)


def _validate_plan_access(client, plan):
    """Fail fast if credentials are missing/invalid for planned read operations."""
    for db_name, coll_plans in plan.items():
        db = client[db_name]
        for item in coll_plans:
            if item.get("mode", "all") == "empty":
                continue
            coll_name = item["collection"]
            query = item.get("query", {})
            try:
                db[coll_name].find_one(query)
                return
            except Exception as e:
                if _is_auth_error(e):
                    print("Authentication error while reading MongoDB data.")
                    print("Use valid credentials via env vars or flags:")
                    print("  --username <user> --password <pass> --auth-db <db>")
                    print("Or set MONGO_USERNAME, MONGO_PASSWORD, MONGO_AUTH_DB.")
                    print(f"Details: {e}")
                    sys.exit(1)
                # If this fails for a non-auth reason (missing collection, bad query),
                # let normal export flow handle/report it per collection.
                return


def _prompt_output_path(default_name):
    path = input(f"\nOutput file path [{default_name}]: ").strip()
    return path if path else default_name


def _interactive_mode(client):
    """Walk the user through selecting databases, collections, queries, and output path."""
    all_dbs = _list_databases(client)

    # Filter to known byoint databases by default, but let user pick any.
    # If listing DBs is not permitted, fall back to the configured default plan keys.
    if all_dbs:
        known = set(DEFAULT_EXPORT_PLAN.keys())
        byoint_dbs = [d for d in all_dbs if d in known]
        other_dbs = [d for d in all_dbs if d not in known and d not in ("admin", "local", "config")]
        candidate_dbs = byoint_dbs + other_dbs if other_dbs else byoint_dbs
    else:
        candidate_dbs = list(DEFAULT_EXPORT_PLAN.keys())

    if not candidate_dbs:
        print("No accessible databases found.")
        sys.exit(1)

    db_indices = _prompt_choice("Select databases to export from:", candidate_dbs, allow_all=True)
    selected_dbs = [candidate_dbs[i] for i in db_indices]

    plan = {}  # {db_name: [{coll, query, limit}]}

    for db_name in selected_dbs:
        all_colls = _list_collections(client, db_name)
        if not all_colls and db_name in DEFAULT_EXPORT_PLAN:
            all_colls = sorted(DEFAULT_EXPORT_PLAN[db_name].keys())
        if not all_colls:
            print(f"  No collections in {db_name}, skipping.")
            continue

        coll_indices = _prompt_choice(f"  Collections in '{db_name}':", all_colls, allow_all=True, allow_none=True)
        if not coll_indices:
            continue

        plan[db_name] = []
        for ci in coll_indices:
            coll_name = all_colls[ci]
            prompt_result = _prompt_query(db_name, coll_name)
            mode = prompt_result["mode"]
            query = prompt_result["query"]
            limit = None
            if mode != "empty":
                limit = _prompt_limit(db_name, coll_name, client[db_name][coll_name], query)
            plan[db_name].append({"collection": coll_name, "mode": mode, "query": query, "limit": limit})

    if not plan:
        print("Nothing selected. Exiting.")
        sys.exit(0)

    return plan


def _non_interactive_mode(client):
    """Export collections using DEFAULT_EXPORT_PLAN rules."""
    plan = {}
    for db_name, rules in DEFAULT_EXPORT_PLAN.items():
        coll_plans = []
        for coll_name, rule in rules.items():
            mode = rule.get("mode", "all")
            query = {}
            if mode == "query":
                query = rule.get("query", {})
            coll_plans.append(
                {
                    "collection": coll_name,
                    "mode": mode,
                    "query": query,
                    "limit": None,
                }
            )
        if coll_plans:
            plan[db_name] = coll_plans
    return plan


def run(args):
    host = args.host or os.getenv("MONGO_HOST") or "localhost"
    port = args.port or os.getenv("MONGO_PORT") or 27017
    username = args.username or os.getenv("MONGO_USERNAME") or ""
    password = args.password or os.getenv("MONGO_PASSWORD") or ""
    auth_db = args.auth_db or os.getenv("MONGO_AUTH_DB") or "admin"

    if username and not password:
        password = getpass.getpass("Mongo password: ")

    print(f"Connecting to MongoDB at {host}:{port} ...")
    client = _connect(host, port, username, password, auth_db)
    print("Connected.\n")

    if args.no_prompt:
        plan = _non_interactive_mode(client)
    else:
        plan = _interactive_mode(client)

    _validate_plan_access(client, plan)

    # Execute the plan
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_host": f"{host}:{port}",
        "collections": {},
    }

    total_docs = 0
    for db_name, coll_plans in plan.items():
        snapshot["collections"][db_name] = {}
        db = client[db_name]
        for item in coll_plans:
            coll_name = item["collection"]
            mode = item.get("mode", "all")
            query = item["query"]
            limit = item["limit"]

            print(f"  Exporting {db_name}.{coll_name} (mode={mode}, query={query}, limit={limit}) ...", end=" ")
            try:
                if mode == "empty":
                    docs = []
                else:
                    docs = _export_collection(db, coll_name, query, limit)
                snapshot["collections"][db_name][coll_name] = docs
                total_docs += len(docs)
                print(f"{len(docs)} docs")
            except Exception as e:
                if _is_auth_error(e):
                    print("AUTH ERROR")
                    print("  Hint: check --username/--password/--auth-db (or MONGO_* env vars).")
                    client.close()
                    sys.exit(1)
                print(f"ERROR: {e}")
                snapshot["collections"][db_name][coll_name] = []

    client.close()

    # Determine output path
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_name = f"mongo_export_{timestamp}.json"
    if args.output:
        output_path = args.output
    elif args.no_prompt:
        output_path = default_name
    else:
        output_path = _prompt_output_path(default_name)

    # Write output
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, cls=MongoJsonEncoder, indent=2, sort_keys=True)

    print(f"\nExported {total_docs} documents to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Export MongoDB collections to a JSON file.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--host", default=None, help="MongoDB host")
    parser.add_argument("--port", default=None, help="MongoDB port")
    parser.add_argument("--username", default=None, help="MongoDB username")
    parser.add_argument("--password", default=None, help="MongoDB password")
    parser.add_argument("--auth-db", default=None, help="Authentication database (default: admin)")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Non-interactive: export all default collections without prompts",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
