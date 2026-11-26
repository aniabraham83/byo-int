import json
import os
from datetime import datetime, timezone

from bson import ObjectId

import all_connects


_WORKFLOW_EXECUTED = False
_LOCK_COLLECTION_DB = "byoint_core_config"
_LOCK_COLLECTION_NAME = "bootstrap_locks"
_LOCK_DOCUMENT_ID = "mongo_init_workflow"
_BOOTSTRAP_ADMIN_USERNAME = "admin"
_BOOTSTRAP_ADMIN_EMAIL = "admin@byoint.local"
_BOOTSTRAP_ADMIN_PASSWORD_ENV = "BYOINT_ADMIN_PASSWORD"
_WORKFLOW_FORCE_REAPPLY_ENV = "MONGO_INIT_FORCE_REAPPLY"


def _utc_now_iso():
	return datetime.now(timezone.utc).isoformat()


def _normalize_mode(raw_mode):
	mode = str(raw_mode or "").strip().lower()
	if mode in ("", "0", "off", "false", "none", "disabled"):
		return "none"
	if mode in ("init", "seed"):
		return "init"
	if mode in ("reset", "rebuild"):
		return "reset"
	return "invalid"


def _env_truthy(var_name):
	value = str(os.getenv(var_name) or "").strip().lower()
	return value in ("1", "true", "yes", "on")


def _resolve_init_file_path():
	explicit = str(os.getenv("MONGO_INIT_FILE") or "").strip()
	if explicit:
		if os.path.isabs(explicit):
			return explicit
		repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
		return os.path.join(repo_root, explicit)

	repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
	return os.path.join(repo_root, "mongo_init.json")


def _load_init_payload(file_path):
	with open(file_path, "r", encoding="utf-8") as fh:
		payload = json.load(fh)
	if not isinstance(payload, dict):
		raise ValueError("mongo init file must contain a JSON object")
	collections = payload.get("collections")
	if not isinstance(collections, dict):
		raise ValueError("mongo init file must contain a top-level 'collections' object")
	return payload


def _acquire_workflow_lock(mongo_client, mode, init_file_path):
	lock_collection = mongo_client[_LOCK_COLLECTION_DB][_LOCK_COLLECTION_NAME]
	lock_collection.create_index("expires_at")

	now = datetime.now(timezone.utc)
	expires_at = datetime.fromtimestamp(now.timestamp() + 600, tz=timezone.utc)

	# Ensure a lock document exists so acquisition can be performed with a non-upsert update.
	lock_collection.update_one(
		{"_id": _LOCK_DOCUMENT_ID},
		{"$setOnInsert": {"state": "idle", "created_at": now, "updated_at": now}},
		upsert=True
	)

	filter_doc = {
		"_id": _LOCK_DOCUMENT_ID,
		"$or": [
			{"state": {"$ne": "running"}},
			{"expires_at": {"$lt": now}},
		],
	}

	update_doc = {
		"$set": {
			"state": "running",
			"mode": mode,
			"init_file_path": init_file_path,
			"started_at": now,
			"updated_at": now,
			"expires_at": expires_at,
		},
		"$setOnInsert": {
			"created_at": now,
		},
	}

	result = lock_collection.update_one(filter_doc, update_doc, upsert=False)
	acquired = bool(result.matched_count > 0 or result.upserted_id is not None)
	return acquired


def _should_skip_init_reapply(mongo_client, mode):
	if mode != "init":
		return False
	if _env_truthy(_WORKFLOW_FORCE_REAPPLY_ENV):
		return False

	lock_collection = mongo_client[_LOCK_COLLECTION_DB][_LOCK_COLLECTION_NAME]
	lock_doc = lock_collection.find_one({"_id": _LOCK_DOCUMENT_ID}) or {}
	state = str(lock_doc.get("state") or "").strip().lower()
	last_mode = str(lock_doc.get("mode") or "").strip().lower()
	return state == "completed" and last_mode == "init"


def _mark_lock_status(mongo_client, state, error=None):
	lock_collection = mongo_client[_LOCK_COLLECTION_DB][_LOCK_COLLECTION_NAME]
	update_fields = {
		"state": state,
		"updated_at": datetime.now(timezone.utc),
		"finished_at": datetime.now(timezone.utc),
		"expires_at": datetime.fromtimestamp(0, tz=timezone.utc),
	}
	update_doc = {"$set": update_fields}
	if error:
		update_fields["error"] = str(error)
	else:
		# Clear any error left by a previous failed run so the status reflects this run.
		update_doc["$unset"] = {"error": ""}
	lock_collection.update_one({"_id": _LOCK_DOCUMENT_ID}, update_doc, upsert=True)


def _serialize_for_response(value):
	if isinstance(value, datetime):
		return value.isoformat()
	if isinstance(value, dict):
		return {k: _serialize_for_response(v) for k, v in value.items()}
	if isinstance(value, list):
		return [_serialize_for_response(v) for v in value]
	return value


def _apply_init_mode(mongo_client, collections_payload):
	for db_name, db_collections in collections_payload.items():
		if not isinstance(db_collections, dict):
			continue
		db = mongo_client[str(db_name)]
		for coll_name, docs in db_collections.items():
			if not isinstance(docs, list):
				continue
			coll = db[str(coll_name)]
			unique_keys = _unique_index_keys(coll)
			for doc in docs:
				if not isinstance(doc, dict):
					continue
				_upsert_seed_doc(coll, _restore_object_id(doc), unique_keys)


def _restore_object_id(doc):
	"""Seed exports serialize ObjectId as a 24-hex string; convert it back so it matches live records."""
	doc_id = doc.get("_id")
	if isinstance(doc_id, str) and ObjectId.is_valid(doc_id):
		return {**doc, "_id": ObjectId(doc_id)}
	return doc


def _unique_index_keys(coll):
	"""Return the field lists of the collection's unique indexes (excluding _id)."""
	keys = []
	for name, info in coll.index_information().items():
		if name == "_id_" or not info.get("unique"):
			continue
		keys.append([field for field, _direction in info.get("key", [])])
	return keys


def _upsert_seed_doc(coll, doc, unique_keys):
	"""Upsert a seed document by _id, or by a unique key when a record with that key already exists.

	Matching on unique keys avoids E11000 errors when the app has already created the record
	(for example a built-in enrichment) under a different _id. The existing _id is kept so
	references to it stay valid.
	"""
	existing = None
	if "_id" in doc:
		existing = coll.find_one({"_id": doc["_id"]}, {"_id": 1})
	if existing is None:
		for fields in unique_keys:
			if all(field in doc for field in fields):
				existing = coll.find_one({field: doc[field] for field in fields}, {"_id": 1})
				if existing is not None:
					break

	if existing is not None:
		body = {key: value for key, value in doc.items() if key != "_id"}
		coll.replace_one({"_id": existing["_id"]}, body)
	elif "_id" in doc:
		coll.replace_one({"_id": doc["_id"]}, doc, upsert=True)
	else:
		coll.insert_one(doc)


def _apply_reset_mode(mongo_client, collections_payload):
	for db_name, db_collections in collections_payload.items():
		if not isinstance(db_collections, dict):
			continue
		db = mongo_client[str(db_name)]

		for coll_name, docs in db_collections.items():
			if not isinstance(docs, list):
				continue
			coll = db[str(coll_name)]
			coll.delete_many({})
			docs = [_restore_object_id(doc) for doc in docs if isinstance(doc, dict)]
			if docs:
				coll.insert_many(docs)


def _ensure_admin_user_if_missing(mongo_client):
	users_col = mongo_client["byoint_core_data"]["users"]
	users_col.create_index("username", unique=True)

	if users_col.count_documents({}, limit=1) > 0:
		return {"created": False, "reason": "users_already_exist"}

	admin_password = str(os.getenv(_BOOTSTRAP_ADMIN_PASSWORD_ENV) or "").strip()
	if not admin_password:
		raise RuntimeError(
			f"Missing required environment variable: {_BOOTSTRAP_ADMIN_PASSWORD_ENV}. "
			"Refusing to create bootstrap admin user without an explicit password."
		)

	# Import lazily to avoid circular import side effects at module import time.
	import auth

	success = auth.create_or_update_user(
		_BOOTSTRAP_ADMIN_USERNAME,
		admin_password,
		email=_BOOTSTRAP_ADMIN_EMAIL,
	)
	if not success:
		raise RuntimeError("Failed to create bootstrap admin user")

	return {
		"created": True,
		"username": _BOOTSTRAP_ADMIN_USERNAME,
		"password_source": _BOOTSTRAP_ADMIN_PASSWORD_ENV,
	}


def _run_workflow(mode, init_file_path):
	if not os.path.exists(init_file_path):
		raise FileNotFoundError(f"Mongo init file not found: {init_file_path}")

	init_payload = _load_init_payload(init_file_path)
	collections_payload = init_payload.get("collections", {})

	mongo_client = None
	try:
		mongo_client, _ = all_connects.connect_mongodb()
		if not mongo_client:
			raise RuntimeError("Failed to connect to MongoDB for init/reset workflow")

		if _should_skip_init_reapply(mongo_client, mode):
			return {
				"status": "skipped",
				"reason": "init_already_completed",
				"mode": mode,
			}

		acquired = _acquire_workflow_lock(mongo_client, mode=mode, init_file_path=init_file_path)
		if not acquired:
			return {"status": "skipped", "reason": "lock_not_acquired", "mode": mode}

		if mode == "init":
			_apply_init_mode(mongo_client, collections_payload)
		elif mode == "reset":
			_apply_reset_mode(mongo_client, collections_payload)

		admin_seed_result = _ensure_admin_user_if_missing(mongo_client)

		_mark_lock_status(mongo_client, state="completed")
		return {
			"status": "completed",
			"mode": mode,
			"init_file_path": init_file_path,
			"admin_seed": admin_seed_result,
			"applied_at": _utc_now_iso(),
		}
	except Exception as e:
		if mongo_client:
			try:
				_mark_lock_status(mongo_client, state="failed", error=e)
			except Exception:
				pass
		raise
	finally:
		if mongo_client:
			mongo_client.close()


def get_mongo_init_workflow_status():
	mongo_client = None
	try:
		mongo_client, _ = all_connects.connect_mongodb()
		if not mongo_client:
			return {"status": "error", "message": "MongoDB connection unavailable"}

		lock_collection = mongo_client[_LOCK_COLLECTION_DB][_LOCK_COLLECTION_NAME]
		lock_doc = lock_collection.find_one({"_id": _LOCK_DOCUMENT_ID}) or {}
		status_text = str(lock_doc.get("state") or "never_run").strip().lower()
		return {
			"status": status_text,
			"lock": _serialize_for_response(lock_doc),
		}
	finally:
		if mongo_client:
			mongo_client.close()


def trigger_mongo_init_workflow(mode, init_file_path=None):
	normalized_mode = _normalize_mode(mode)
	if normalized_mode not in ("init", "reset"):
		raise ValueError("Invalid mode. Use one of: init, reset")

	resolved_file = str(init_file_path or "").strip()
	if resolved_file:
		if not os.path.isabs(resolved_file):
			repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
			resolved_file = os.path.join(repo_root, resolved_file)
	else:
		resolved_file = _resolve_init_file_path()

	return _run_workflow(normalized_mode, resolved_file)


def apply_env_mongo_init_workflow():
	"""Apply Mongo initialization workflow from mongo_init.json based on env switch.

	Environment variables:
	- MONGO_INIT_WORKFLOW: none|init|reset (default: none)
	- MONGO_INIT_FILE: optional path to init JSON (default: ../mongo_init.json)
	"""
	global _WORKFLOW_EXECUTED
	if _WORKFLOW_EXECUTED:
		return {"status": "skipped", "reason": "already_executed_in_process"}

	mode = _normalize_mode(os.getenv("MONGO_INIT_WORKFLOW", "none"))
	if mode == "none":
		return {"status": "skipped", "reason": "workflow_disabled"}
	if mode == "invalid":
		raise ValueError("Invalid MONGO_INIT_WORKFLOW value. Use one of: none, init, reset")

	result = _run_workflow(mode, _resolve_init_file_path())
	if str(result.get("status") or "").lower() == "completed":
		os.environ["MONGO_INIT_WORKFLOW"] = "none"
		result["workflow_auto_disabled"] = True
		_WORKFLOW_EXECUTED = True
	return result
