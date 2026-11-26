from datetime import datetime, timedelta, timezone
from fnmatch import fnmatch
from functools import wraps
from urllib.parse import urlencode
import secrets

from flask import request, jsonify, g, make_response, redirect, session
from werkzeug.security import generate_password_hash, check_password_hash

import all_connects
import endpoint_docs


_AUTH_SETTINGS = {}
_OAUTH_OIDC_CLIENT = None
_PUBLIC_API_RULES = []


def _normalize_username_values(raw_values):
    if raw_values is None:
        return []

    if isinstance(raw_values, str):
        candidates = [entry.strip() for entry in raw_values.split(',') if entry and str(entry).strip()]
    elif isinstance(raw_values, (list, tuple, set)):
        candidates = [str(entry).strip() for entry in raw_values if str(entry).strip()]
    else:
        candidates = [str(raw_values).strip()] if str(raw_values).strip() else []

    normalized = []
    seen = set()
    for username in candidates:
        normalized_username = str(username).strip().lower()
        if not normalized_username or normalized_username in seen:
            continue
        seen.add(normalized_username)
        normalized.append(normalized_username)
    return normalized


def _default_rbac_config_values():
    return {
        'known_roles': ['admin', 'user'],
        'default_role': 'user',
        'allow_unlisted_roles': False,
        # Map route path -> required role (admin or user).
        'restricted_pages': {
            '/users': 'admin',
            '/configuration': 'admin',
            '/audit-logs': 'admin',
            '/platform-change-logs': 'admin',
        },
    }


def _normalize_restricted_pages(raw_map):
    if not isinstance(raw_map, dict):
        return {}

    normalized = {}
    for raw_path, raw_role in raw_map.items():
        path = str(raw_path or '').strip()
        if not path:
            continue
        if not path.startswith('/'):
            path = f'/{path}'

        role = str(raw_role or '').strip().lower()
        if role not in ('admin', 'user'):
            continue

        normalized[path] = role
    return normalized


def _ensure_and_load_auth_rbac_config():
    mongo_client = None
    try:
        defaults = _default_rbac_config_values()

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        basicconfigs_col = db['basicconfigs']

        auth_doc = basicconfigs_col.find_one({'module': 'auth'})
        if not auth_doc:
            new_doc = {
                'module': 'auth',
                'rbac': defaults,
            }
            basicconfigs_col.insert_one(new_doc)
            return defaults

        rbac = auth_doc.get('rbac')
        if not isinstance(rbac, dict):
            rbac = {}

        known_roles = _normalize_roles(rbac.get('known_roles'))
        if not known_roles:
            known_roles = list(defaults.get('known_roles', []))

        default_role = str(rbac.get('default_role') or '').strip().lower()
        if not default_role:
            default_role = str(defaults.get('default_role') or 'user').strip().lower()
        if default_role not in known_roles:
            known_roles.append(default_role)

        allow_unlisted_roles = rbac.get('allow_unlisted_roles')
        if allow_unlisted_roles is None:
            allow_unlisted_roles = defaults.get('allow_unlisted_roles', False)
        allow_unlisted_roles = bool(allow_unlisted_roles)

        restricted_pages = _normalize_restricted_pages(rbac.get('restricted_pages'))
        if not restricted_pages:
            restricted_pages = _normalize_restricted_pages(defaults.get('restricted_pages'))

        normalized_rbac = {
            'known_roles': ['admin', 'user'],
            'default_role': 'user' if default_role not in ('admin', 'user') else default_role,
            'allow_unlisted_roles': False,
            'restricted_pages': restricted_pages,
        }

        if normalized_rbac != rbac:
            basicconfigs_col.update_one(
                {'_id': auth_doc['_id']},
                {'$set': {'rbac': normalized_rbac}}
            )

        return normalized_rbac
    except Exception as e:
        print(e)
        return _default_rbac_config_values()
    finally:
        if mongo_client:
            mongo_client.close()


def get_rbac_config():
    return _ensure_and_load_auth_rbac_config()


def update_rbac_config(raw_rbac):
    if not isinstance(raw_rbac, dict):
        return False, 'rbac must be a JSON object.', None

    defaults = _default_rbac_config_values()

    # Simplified model: only admin/user roles are supported.
    known_roles = ['admin', 'user']

    default_role = str(raw_rbac.get('default_role') or '').strip().lower()
    if default_role not in ('admin', 'user'):
        default_role = str(defaults.get('default_role', 'user')).strip().lower()
    if default_role not in ('admin', 'user'):
        default_role = 'user'

    restricted_pages = _normalize_restricted_pages(raw_rbac.get('restricted_pages'))
    if not restricted_pages:
        restricted_pages = _normalize_restricted_pages(defaults.get('restricted_pages'))

    normalized_rbac = {
        'known_roles': known_roles,
        'default_role': default_role,
        'allow_unlisted_roles': False,
        'restricted_pages': restricted_pages,
    }

    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client['byoint_core_config']
        basicconfigs_col = db['basicconfigs']

        update_result = basicconfigs_col.update_one(
            {'module': 'auth'},
            {'$set': {'module': 'auth', 'rbac': normalized_rbac}},
            upsert=True,
        )

        if not update_result.acknowledged:
            return False, 'Failed to persist RBAC configuration.', None

        return True, 'RBAC configuration updated successfully.', normalized_rbac
    except Exception as e:
        print(e)
        return False, f'Failed to update RBAC configuration: {e}', None
    finally:
        if mongo_client:
            mongo_client.close()


def _auth_setting(name, default=None):
    return _AUTH_SETTINGS.get(name, default)


def _normalize_public_api_endpoints(raw_rules):
    normalized = []

    if raw_rules is None:
        return normalized

    if isinstance(raw_rules, str):
        candidates = [entry.strip() for entry in raw_rules.split(',') if entry and str(entry).strip()]
    elif isinstance(raw_rules, (list, tuple, set)):
        candidates = [str(entry).strip() for entry in raw_rules if str(entry).strip()]
    else:
        candidates = [str(raw_rules).strip()] if str(raw_rules).strip() else []

    for entry in candidates:
        method = '*'
        path_pattern = entry

        if ' ' in entry:
            left, right = entry.split(None, 1)
            if left and right:
                method = str(left).strip().upper() or '*'
                path_pattern = str(right).strip()
        elif ':' in entry:
            left, right = entry.rsplit(':', 1)
            left = str(left).strip()
            right = str(right).strip()
            if right and right.isalpha() and len(right) <= 10:
                method = right.upper()
                path_pattern = left
            elif left and left.isalpha() and len(left) <= 10:
                method = left.upper()
                path_pattern = right

        path_pattern = str(path_pattern or '').strip()
        if not path_pattern:
            continue
        if not path_pattern.startswith('/'):
            path_pattern = f'/{path_pattern}'

        normalized.append((method if method else '*', path_pattern))

    return normalized


def _is_api_key_request_allowed(path, method):
    if not _PUBLIC_API_RULES:
        # Backward-compatible default: if list is not configured, do not restrict.
        return True

    req_method = str(method or '').strip().upper()
    req_path = str(path or '').strip()
    for allowed_method, allowed_path_pattern in _PUBLIC_API_RULES:
        method_match = allowed_method in ('*', req_method)
        path_match = fnmatch(req_path, allowed_path_pattern)
        if method_match and path_match:
            return True
    return False


def _serialize_user_doc(user_doc):
    if not user_doc:
        return None

    created_at = user_doc.get("created_at")
    updated_at = user_doc.get("updated_at")
    apikey_created_at = user_doc.get("apikey_created_at")
    if hasattr(created_at, "isoformat"):
        user_doc["created_at"] = created_at.isoformat()
    if hasattr(updated_at, "isoformat"):
        user_doc["updated_at"] = updated_at.isoformat()
    if hasattr(apikey_created_at, "isoformat"):
        user_doc["apikey_created_at"] = apikey_created_at.isoformat()
    roles = _normalize_roles(user_doc.get("roles"))
    if not roles:
        roles = _default_roles_for_username(user_doc.get("username"))
    user_doc["roles"] = roles
    return user_doc


def _normalize_roles(raw_roles):
    if raw_roles is None:
        return []

    if isinstance(raw_roles, str):
        candidates = [entry.strip() for entry in raw_roles.split(',') if entry and str(entry).strip()]
    elif isinstance(raw_roles, (list, tuple, set)):
        candidates = [str(entry).strip() for entry in raw_roles if str(entry).strip()]
    else:
        candidates = [str(raw_roles).strip()] if str(raw_roles).strip() else []

    normalized = []
    seen = set()
    for role in candidates:
        normalized_role = str(role).strip().lower()
        if not normalized_role or normalized_role in seen:
            continue
        seen.add(normalized_role)
        normalized.append(normalized_role)
    return normalized


def _default_roles_for_username(username):
    normalized_username = str(username or '').strip().lower()
    # Keep backward-compatible bootstrap behavior for the default admin account.
    if normalized_username == 'admin':
        return ['admin']

    rbac = _ensure_and_load_auth_rbac_config()
    default_role = str((rbac or {}).get('default_role') or 'user').strip().lower() or 'user'
    return [default_role]


def get_user_roles(username):
    mongo_client = None
    try:
        normalized_username = str(username or '').strip()
        if not normalized_username:
            return []

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]

        user_doc = users.find_one({"username": normalized_username}, {"roles": 1})
        roles = _normalize_roles((user_doc or {}).get('roles'))
        if roles:
            return roles
        return _default_roles_for_username(normalized_username)
    except Exception as e:
        print(e)
        return _default_roles_for_username(username)
    finally:
        if mongo_client:
            mongo_client.close()


def has_any_role(username, required_roles):
    required = set(_normalize_roles(required_roles))
    if not required:
        return True

    user_roles = set(get_user_roles(username))
    return bool(user_roles.intersection(required))


def require_roles(*required_roles):
    required = _normalize_roles(required_roles)

    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            current_user = getattr(g, 'current_user', None)
            if not current_user:
                return jsonify({"message": "Authenticated user not found."}), 401

            user_roles = getattr(g, 'current_user_roles', None)
            if not isinstance(user_roles, list):
                user_roles = get_user_roles(current_user)
            g.current_user_roles = user_roles

            if not set(user_roles).intersection(set(required)):
                return jsonify({
                    "message": "Insufficient permissions.",
                    "required_roles": required,
                    "user_roles": user_roles,
                }), 403

            return f(*args, **kwargs)

        return wrapped

    return decorator


def return_apikeys(user=None):
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]
        users.create_index("apikey", unique=True, sparse=True)
        apikey_list = []
        if not user:
            res_col = users.find({"apikey": {"$exists": True, "$ne": None}}, {"apikey": 1})
        else:
            res_col = users.find({"username": user, "apikey": {"$exists": True, "$ne": None}}, {"apikey": 1})
        for record in res_col:
            apikey_list.append(record.get("apikey"))
        return apikey_list
    except Exception as e:
        print(e)
        return []
    finally:
        if mongo_client:
            mongo_client.close()


def generate_update_apikey(user=None):
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]
        users.create_index("username", unique=True)
        users.create_index("apikey", unique=True, sparse=True)
        key_user = user or "root"

        existing_user = users.find_one({"username": key_user}, {"_id": 1})
        if not existing_user:
            print(f"User not found for API key generation: {key_user}")
            return None

        new_apikey = secrets.token_urlsafe(32)
        users.update_one(
            {"username": key_user},
            {
                "$set": {
                    "apikey": new_apikey,
                    "apikey_created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        return new_apikey
    except Exception as e:
        print(e)
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def verify_user_credentials(username, password):
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]
        user_doc = users.find_one({"username": username})
        if not user_doc:
            return None

        stored_hash = user_doc.get("password_hash")
        if stored_hash and check_password_hash(stored_hash, password):
            return username
        return None
    except Exception as e:
        print(e)
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def create_or_update_user(username, password, email=None):
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]
        users.create_index("username", unique=True)

        now = datetime.now(timezone.utc)
        users.update_one(
            {"username": username},
            {
                "$set": {
                    "username": username,
                    "password_hash": generate_password_hash(password, method="pbkdf2:sha256"),
                    "email": email,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "created_at": now,
                    "roles": _default_roles_for_username(username),
                },
            },
            upsert=True,
        )
        return True
    except Exception as e:
        print(e)
        return False
    finally:
        if mongo_client:
            mongo_client.close()


def list_users():
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]

        records = []
        for user_doc in users.find({}, {"_id": 0, "password_hash": 0, "apikey": 0}).sort("username", 1):
            records.append(_serialize_user_doc(user_doc))
        return records
    except Exception as e:
        print(e)
        return []
    finally:
        if mongo_client:
            mongo_client.close()


def get_user(username):
    mongo_client = None
    try:
        if not username:
            return None

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]
        user_doc = users.find_one({"username": username}, {"_id": 0, "password_hash": 0, "apikey": 0})
        return _serialize_user_doc(user_doc)
    except Exception as e:
        print(e)
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def create_user(username, password, email=None):
    mongo_client = None
    try:
        if not username or not password:
            return False, "Username and password are required."

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]
        users.create_index("username", unique=True)

        if users.find_one({"username": username}):
            return False, "User already exists."

        now = datetime.now(timezone.utc)
        users.insert_one({
            "username": username,
            "password_hash": generate_password_hash(password, method="pbkdf2:sha256"),
            "email": email,
            "roles": _default_roles_for_username(username),
            "created_at": now,
            "updated_at": now,
        })
        return True, "User created successfully."
    except Exception as e:
        print(e)
        return False, "Failed to create user."
    finally:
        if mongo_client:
            mongo_client.close()


def update_user(username, password=None, email=None):
    mongo_client = None
    try:
        if not username:
            return False, "Username is required."

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]

        if not users.find_one({"username": username}):
            return False, "User not found."

        update_fields = {"updated_at": datetime.now(timezone.utc)}
        if email is not None:
            update_fields["email"] = email
        if password:
            update_fields["password_hash"] = generate_password_hash(password, method="pbkdf2:sha256")

        if len(update_fields) == 1:
            return False, "No updates were provided."

        users.update_one({"username": username}, {"$set": update_fields})
        return True, "User updated successfully."
    except Exception as e:
        print(e)
        return False, "Failed to update user."
    finally:
        if mongo_client:
            mongo_client.close()


def _normalize_single_role(role):
    normalized = str(role or '').strip().lower()
    if not normalized:
        return None

    rbac = _ensure_and_load_auth_rbac_config()
    known_roles = set(_normalize_roles((rbac or {}).get('known_roles')))
    allow_unlisted_roles = bool((rbac or {}).get('allow_unlisted_roles', False))
    if not allow_unlisted_roles and normalized not in known_roles:
        return None

    return normalized


def grant_user_role(username, role, granted_by=None):
    mongo_client = None
    try:
        normalized_username = str(username or '').strip()
        normalized_role = _normalize_single_role(role)
        if not normalized_username:
            return False, "Username is required.", None
        if not normalized_role:
            return False, "Role is required.", None

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]

        now = datetime.now(timezone.utc)
        result = users.update_one(
            {"username": normalized_username},
            {
                "$addToSet": {"roles": normalized_role},
                "$set": {
                    "updated_at": now,
                    "roles_updated_at": now,
                    "roles_updated_by": granted_by,
                }
            }
        )
        if result.matched_count == 0:
            return False, "User not found.", None

        user_doc = get_user(normalized_username)
        if result.modified_count == 0:
            return True, "Role already assigned.", user_doc
        return True, "Role granted successfully.", user_doc
    except Exception as e:
        print(e)
        return False, "Failed to grant role.", None
    finally:
        if mongo_client:
            mongo_client.close()


def revoke_user_role(username, role, revoked_by=None):
    mongo_client = None
    try:
        normalized_username = str(username or '').strip()
        normalized_role = _normalize_single_role(role)
        if not normalized_username:
            return False, "Username is required.", None
        if not normalized_role:
            return False, "Role is required.", None

        # Guard against locking out the bootstrap default admin account.
        if normalized_username.lower() == 'admin' and normalized_role == 'admin':
            return False, "Cannot revoke admin role from default admin user.", None

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]

        now = datetime.now(timezone.utc)
        result = users.update_one(
            {"username": normalized_username},
            {
                "$pull": {"roles": normalized_role},
                "$set": {
                    "updated_at": now,
                    "roles_updated_at": now,
                    "roles_updated_by": revoked_by,
                }
            }
        )
        if result.matched_count == 0:
            return False, "User not found.", None

        user_doc = get_user(normalized_username)
        if result.modified_count == 0:
            return True, "Role was not assigned.", user_doc
        return True, "Role revoked successfully.", user_doc
    except Exception as e:
        print(e)
        return False, "Failed to revoke role.", None
    finally:
        if mongo_client:
            mongo_client.close()


def upsert_sso_user(username, email=None, provider=None, subject=None):
    mongo_client = None
    try:
        if not username:
            return None

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]
        users.create_index("username", unique=True)

        now = datetime.now(timezone.utc)
        update_fields = {
            "username": username,
            "updated_at": now,
            "auth_source": "sso"
        }
        if email is not None:
            update_fields["email"] = email
        if provider:
            update_fields["sso_provider"] = provider
        if subject:
            update_fields["sso_subject"] = subject

        users.update_one(
            {"username": username},
            {
                "$set": update_fields,
                "$setOnInsert": {
                    "created_at": now,
                    "password_hash": generate_password_hash(secrets.token_urlsafe(32), method="pbkdf2:sha256"),
                    "roles": _default_roles_for_username(username)
                }
            },
            upsert=True
        )
        return get_user(username)
    except Exception as e:
        print(e)
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def initialize_default_users():
    try:
        admin_password = str(os.getenv("BYOINT_ADMIN_PASSWORD") or "").strip()
        test_password = str(os.getenv("BYOINT_TEST_PASSWORD") or "").strip()

        if admin_password:
            create_or_update_user("admin", admin_password, email="admin@byoint.local")
        if test_password:
            create_or_update_user("test", test_password, email="test@byoint.local")

        if not admin_password and not test_password:
            print("Default user initialization skipped: no env passwords provided")
            return False

        print("Default users initialized successfully")
        return True
    except Exception as e:
        print(e)
        return False


def get_user_for_apikey(apikey):
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        users = db["users"]
        users.create_index("apikey", unique=True, sparse=True)
        rec = users.find_one({"apikey": apikey}, {"username": 1})
        return rec.get("username") if rec else None
    except Exception as e:
        print(e)
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def create_browser_session(user=None, user_agent=None):
    mongo_client = None
    try:
        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        sessions = db["browser_sessions"]
        sessions.create_index("session_id_hash", unique=True)
        sessions.create_index("expires_at", expireAfterSeconds=0)

        now = all_connects._utc_now()
        idle_delta = timedelta(minutes=all_connects.SESSION_IDLE_MINUTES)
        absolute_delta = timedelta(hours=all_connects.SESSION_ABSOLUTE_HOURS)
        session_id = secrets.token_urlsafe(48)

        sessions.insert_one({
            "session_id_hash": all_connects._hash_session_id(session_id),
            "user": user,
            "user_agent": user_agent,
            "created_at": now,
            "last_seen_at": now,
            "expires_at": now + idle_delta,
            "absolute_expires_at": now + absolute_delta,
        })
        return session_id
    except Exception as e:
        print(e)
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def validate_browser_session(session_id=None, user_agent=None):
    mongo_client = None
    try:
        if not session_id:
            return None

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        sessions = db["browser_sessions"]
        session_hash = all_connects._hash_session_id(session_id)
        now = all_connects._utc_now()
        rec = sessions.find_one({
            "session_id_hash": session_hash,
            "revoked_at": {"$exists": False}
        })
        if not rec:
            return None

        expires_at = all_connects._normalize_utc(rec.get("expires_at"))
        absolute_expires_at = all_connects._normalize_utc(rec.get("absolute_expires_at"))
        if not expires_at or not absolute_expires_at or expires_at <= now or absolute_expires_at <= now:
            sessions.update_one(
                {"_id": rec.get("_id")},
                {"$set": {"revoked_at": now, "revocation_reason": "expired"}}
            )
            return None

        idle_delta = timedelta(minutes=all_connects.SESSION_IDLE_MINUTES)
        next_expiry = min(now + idle_delta, absolute_expires_at)
        update_fields = {
            "last_seen_at": now,
            "expires_at": next_expiry
        }
        if user_agent and not rec.get("user_agent"):
            update_fields["user_agent"] = user_agent

        sessions.update_one({"_id": rec.get("_id")}, {"$set": update_fields})
        return rec.get("user")
    except Exception as e:
        print(e)
        return None
    finally:
        if mongo_client:
            mongo_client.close()


def revoke_browser_session(session_id=None):
    mongo_client = None
    try:
        if not session_id:
            return False

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_data"]
        sessions = db["browser_sessions"]
        result = sessions.update_one(
            {
                "session_id_hash": all_connects._hash_session_id(session_id),
                "revoked_at": {"$exists": False}
            },
            {
                "$set": {
                    "revoked_at": all_connects._utc_now(),
                    "revocation_reason": "logout"
                }
            }
        )
        return result.modified_count > 0
    except Exception as e:
        print(e)
        return False
    finally:
        if mongo_client:
            mongo_client.close()


def get_datapull_core_config():
    import datapull
    return datapull.get_datapull_core_config()


def create_datapull_secret(name, secret_value, created_by=None, description=None):
    mongo_client = None
    try:
        if not name or secret_value is None:
            return None, "name and secret_value are required"

        now = all_connects._utc_now()
        encrypted = all_connects._encrypt_datapull_secret_value(secret_value)
        secret_ref = f"sec_{secrets.token_urlsafe(12)}"

        mongo_client, _ = all_connects.connect_mongodb()
        db = mongo_client["byoint_core_config"]
        secrets_col = db["datapull_secrets"]
        secrets_col.create_index("secret_ref", unique=True)
        secrets_col.create_index("name", unique=True)

        if secrets_col.find_one({"name": str(name).strip()}):
            return None, "Secret name already exists"

        doc = {
            "secret_ref": secret_ref,
            "name": str(name).strip(),
            "description": description,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
            "active": True,
            "version": 1,
            "algorithm": encrypted.get("algorithm"),
            "nonce": encrypted.get("nonce"),
            "ciphertext": encrypted.get("ciphertext")
        }
        secrets_col.insert_one(doc)

        return {
            "secret_ref": doc.get("secret_ref"),
            "name": doc.get("name"),
            "description": doc.get("description"),
            "created_by": doc.get("created_by"),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
            "active": doc.get("active"),
            "version": doc.get("version")
        }, None
    except Exception as e:
        print(e)
        return None, str(e)
    finally:
        if mongo_client:
            mongo_client.close()


def _collect_payload_secret_refs(payload, refs_set):
    import datapull
    return datapull._collect_payload_secret_refs(payload, refs_set)


def list_datapull_secrets(include_usage=False):
    import datapull
    return datapull.list_datapull_secrets(include_usage=include_usage)


def get_datapull_secret_by_name(name):
    import datapull
    return datapull.get_datapull_secret_by_name(name)


def rotate_datapull_secret(secret_ref, new_secret_value, rotated_by=None):
    import datapull
    return datapull.rotate_datapull_secret(secret_ref, new_secret_value, rotated_by=rotated_by)


def _payload_contains_secret_ref(payload, secret_ref):
    import datapull
    return datapull._payload_contains_secret_ref(payload, secret_ref)


def deactivate_datapull_secret(secret_ref, deactivated_by=None):
    import datapull
    return datapull.deactivate_datapull_secret(secret_ref, deactivated_by=deactivated_by)


def resolve_datapull_secret_ref(secret_ref):
    import datapull
    return datapull.resolve_datapull_secret_ref(secret_ref)


def _extract_bearer_token():
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        return None, "Authorization header is missing."

    auth_parts = auth_header.split(" ", 1)
    if len(auth_parts) != 2 or auth_parts[0].lower() != "bearer" or not str(auth_parts[1]).strip():
        return None, "Authorization header is malformed."

    return str(auth_parts[1]).strip(), None


def _is_valid_api_token(token):
    if not token:
        return False

    api_keys = return_apikeys()
    if not api_keys:
        return False

    return str(token) in api_keys


def set_session_cookie(response, session_id):
    response.set_cookie(
        _auth_setting("session_cookie_name", "byoint_session"),
        session_id,
        max_age=_auth_setting("session_cookie_max_age", 1800),
        httponly=True,
        secure=_auth_setting("session_cookie_secure", False),
        samesite=_auth_setting("session_cookie_samesite", "Lax"),
        path="/"
    )
    return response


def clear_session_cookie(response):
    response.delete_cookie(
        _auth_setting("session_cookie_name", "byoint_session"),
        path="/",
        secure=_auth_setting("session_cookie_secure", False),
        httponly=True,
        samesite=_auth_setting("session_cookie_samesite", "Lax")
    )
    return response


def is_sso_ready():
    return bool(_auth_setting("sso_enabled", False) and _OAUTH_OIDC_CLIENT)


def build_frontend_url(path="/", query_params=None):
    normalized_path = path if path.startswith("/") else f"/{path}"
    configured_base = str(_auth_setting('frontend_base_url', '') or '').rstrip('/')
    host_base = str(request.host_url or '').rstrip('/')
    base_url = configured_base or host_base
    url = f"{base_url}{normalized_path}"
    if query_params:
        url = f"{url}?{urlencode(query_params)}"
    return url


def resolve_sso_redirect_uri():
    redirect_uri = _auth_setting("sso_redirect_uri")
    if redirect_uri:
        return redirect_uri
    return f"{request.host_url.rstrip('/')}/api/auth/sso/callback"


def build_sso_username(userinfo):
    return (
        (userinfo.get("preferred_username") if userinfo else None)
        or (userinfo.get("email") if userinfo else None)
        or (userinfo.get("upn") if userinfo else None)
        or (userinfo.get("sub") if userinfo else None)
    )


def build_unauthorized_response(message, clear_session=False):
    response = make_response(jsonify({"message": message}), 401)
    if clear_session:
        clear_session_cookie(response)
    return response


def authenticate_request():
    session_cookie_name = _auth_setting("session_cookie_name", "byoint_session")
    session_id = request.cookies.get(session_cookie_name)
    if session_id:
        session_user = validate_browser_session(
            session_id=session_id,
            user_agent=request.headers.get("User-Agent")
        )
        if session_user:
            return session_user, "session", None, session_id, False

    auth_header = request.headers.get("Authorization")
    if auth_header:
        token, token_error = _extract_bearer_token()
        if token_error:
            return None, None, token_error, None, False

        if not _is_valid_api_token(token):
            return None, None, "API key is invalid!", None, False

        return get_user_for_apikey(token), "api_key", None, None, False

    if session_id:
        return None, None, "Session is invalid or expired.", None, True

    return None, None, "Authentication required.", None, False


def register_routes(app, oauth_oidc_client=None, settings=None):
    global _AUTH_SETTINGS, _OAUTH_OIDC_CLIENT, _PUBLIC_API_RULES

    _AUTH_SETTINGS = dict(settings or {})
    _OAUTH_OIDC_CLIENT = oauth_oidc_client
    _PUBLIC_API_RULES = _normalize_public_api_endpoints(
        _auth_setting('public_api_endpoints', _auth_setting('PUBLIC_API_ENDPOINTS'))
    )
    _ensure_and_load_auth_rbac_config()

    def token_required(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            current_user, auth_type, auth_error, session_id, clear_cookie = authenticate_request()
            if auth_error:
                return build_unauthorized_response(auth_error, clear_session=clear_cookie)

            if auth_type == 'api_key' and not _is_api_key_request_allowed(request.path, request.method):
                return make_response(jsonify({
                    "message": "API key access denied for this endpoint.",
                    "path": request.path,
                    "method": request.method
                }), 403)

            g.current_user = current_user
            g.auth_type = auth_type
            g.session_id = session_id
            g.current_user_roles = get_user_roles(current_user)

            response = make_response(f(*args, **kwargs))
            if auth_type == "session" and session_id:
                set_session_cookie(response, session_id)
            return response

        return decorated

    @app.route("/api/auth", methods=["POST"])
    def auth_login():
        if not request.is_json:
            return jsonify({"message": "Request must be JSON."}), 400

        data = request.json
        username = data.get("user") or data.get("username") or data.get("email")
        password = data.get("password")

        if not username or not password:
            return jsonify({"message": "Missing username or password."}), 400

        verified_user = verify_user_credentials(username, password)
        if not verified_user:
            return jsonify({"message": "Invalid credentials."}), 401

        session_id = create_browser_session(
            user=verified_user,
            user_agent=request.headers.get("User-Agent")
        )
        if not session_id:
            return jsonify({"message": "Failed to create session."}), 500

        response = make_response(jsonify({"authenticated": True, "user": verified_user}), 200)
        set_session_cookie(response, session_id)
        return response

    @app.route("/api/auth/sso/config", methods=["GET"])
    def auth_sso_config():
        return jsonify({
            "enabled": is_sso_ready(),
            "provider_name": _auth_setting("sso_provider_name") if is_sso_ready() else None,
            "login_url": "/api/auth/sso/login" if is_sso_ready() else None
        }), 200

    @app.route("/api/auth/sso/login", methods=["GET"])
    def auth_sso_login():
        if not is_sso_ready():
            return jsonify({"message": "SSO is not configured."}), 404

        return _OAUTH_OIDC_CLIENT.authorize_redirect(resolve_sso_redirect_uri())

    @app.route("/api/auth/sso/callback", methods=["GET"])
    def auth_sso_callback():
        if not is_sso_ready():
            return redirect(build_frontend_url("/login", {"sso_error": "SSO is not configured."}))

        try:
            token = _OAUTH_OIDC_CLIENT.authorize_access_token()
            userinfo = token.get("userinfo") if isinstance(token, dict) else None
            if not userinfo:
                userinfo = _OAUTH_OIDC_CLIENT.userinfo()

            username = build_sso_username(userinfo)
            email = userinfo.get("email") if userinfo else None
            subject = userinfo.get("sub") if userinfo else None

            if not username:
                return redirect(build_frontend_url("/login", {"sso_error": "Unable to resolve SSO user identity."}))

            user_record = get_user(username)
            if not user_record and not _auth_setting("sso_auto_create_users", True):
                return redirect(build_frontend_url("/login", {"sso_error": "SSO user is not provisioned."}))

            if _auth_setting("sso_auto_create_users", True):
                user_record = upsert_sso_user(
                    username=username,
                    email=email,
                    provider=_auth_setting("sso_provider_name"),
                    subject=subject
                )

            if not user_record:
                return redirect(build_frontend_url("/login", {"sso_error": "Failed to provision SSO user."}))

            session_id = create_browser_session(
                user=username,
                user_agent=request.headers.get("User-Agent")
            )
            if not session_id:
                return redirect(build_frontend_url("/login", {"sso_error": "Failed to create session."}))

            response = redirect(build_frontend_url("/"))
            session.clear()
            set_session_cookie(response, session_id)
            return response
        except Exception as e:
            print(f"SSO callback error: {e}")
            return redirect(build_frontend_url("/login", {"sso_error": "SSO authentication failed."}))

    @app.route("/api/logout", methods=["POST"])
    def logout():
        session_id = request.cookies.get(_auth_setting("session_cookie_name", "byoint_session"))
        if session_id:
            revoke_browser_session(session_id=session_id)

        session.clear()
        response = make_response(jsonify({"message": "Logged out."}), 200)
        clear_session_cookie(response)
        return response

    @app.route("/api/whoami", methods=["GET"])
    @token_required
    def whoami():
        try:
            user = getattr(g, "current_user", None)
            if not user:
                return jsonify({"message": "Authenticated user not found."}), 404
            rbac = _ensure_and_load_auth_rbac_config()
            return jsonify({
                "user": user,
                "roles": getattr(g, "current_user_roles", []),
                "page_access_map": (rbac or {}).get('restricted_pages', {}),
            }), 200
        except Exception as e:
            return jsonify({"message": str(e)}), 500

    @app.route("/api/users", methods=["GET"])
    @token_required
    def list_users_route():
        try:
            return jsonify({"users": list_users()}), 200
        except Exception as e:
            return jsonify({"message": str(e)}), 500

    @app.route("/api/users/me/apikey", methods=["POST"])
    @token_required
    def rotate_my_apikey():
        try:
            current_user = getattr(g, "current_user", None)
            if not current_user:
                return jsonify({"message": "Authenticated user not found."}), 401

            new_apikey = generate_update_apikey(user=current_user)
            if not new_apikey:
                return jsonify({"message": "Failed to generate API key."}), 500

            return jsonify({
                "message": "API key generated successfully.",
                "apikey": new_apikey,
                "user": current_user
            }), 200
        except Exception as e:
            return jsonify({"message": str(e)}), 500

    @app.route("/api/users", methods=["POST"])
    @token_required
    def create_user_route():
        if not request.is_json:
            return jsonify({"message": "Request must be JSON."}), 400

        data = request.json or {}
        username = str(data.get("username") or "").strip()
        password = str(data.get("password") or "").strip()
        email = data.get("email")
        email = str(email).strip() if email is not None else None

        if not username or not password:
            return jsonify({"message": "Username and password are required."}), 400

        success, message = create_user(username=username, password=password, email=email)
        if not success:
            status = 409 if message == "User already exists." else 400
            return jsonify({"message": message}), status

        user_doc = get_user(username)
        return jsonify({"message": message, "user": user_doc}), 201

    @app.route("/api/users/<username>", methods=["PUT"])
    @token_required
    def update_user_route(username):
        if not request.is_json:
            return jsonify({"message": "Request must be JSON."}), 400

        data = request.json or {}
        normalized_username = str(username or "").strip()
        password = str(data.get("password") or "").strip() or None
        email = data.get("email")
        email = str(email).strip() if email is not None else None

        if not normalized_username:
            return jsonify({"message": "Username is required."}), 400
        if email is None and password is None:
            return jsonify({"message": "At least one field must be updated."}), 400

        success, message = update_user(
            username=normalized_username,
            password=password,
            email=email
        )
        if not success:
            status = 404 if message == "User not found." else 400
            return jsonify({"message": message}), status

        user_doc = get_user(normalized_username)
        return jsonify({"message": message, "user": user_doc}), 200

    @app.route("/api/users/<username>/roles/grant", methods=["POST"])
    @endpoint_docs.endpoint_doc(
        summary='Grant a role to a user',
        description='Admin-only endpoint to grant one role to a target user.',
        auth_types=['session', 'api_key'],
        required_roles=['admin'],
        tags=['Users', 'RBAC'],
        request_body={
            'required': True,
            'properties': {
                'role': {'type': 'string'}
            }
        },
        responses={
            200: {'description': 'Role granted or already present'},
            400: {'description': 'Invalid request'},
            403: {'description': 'Insufficient permissions'},
            404: {'description': 'User not found'},
            500: {'description': 'Server error'}
        }
    )
    @token_required
    @require_roles('admin')
    def grant_user_role_route(username):
        if not request.is_json:
            return jsonify({"message": "Request must be JSON."}), 400

        data = request.json or {}
        role = data.get('role')
        actor = getattr(g, 'current_user', None)

        success, message, user_doc = grant_user_role(username=username, role=role, granted_by=actor)
        if not success:
            status = 404 if message == "User not found." else 400
            return jsonify({"message": message}), status
        return jsonify({"message": message, "user": user_doc}), 200

    @app.route("/api/users/<username>/roles/revoke", methods=["POST"])
    @endpoint_docs.endpoint_doc(
        summary='Revoke a role from a user',
        description='Admin-only endpoint to revoke one role from a target user.',
        auth_types=['session', 'api_key'],
        required_roles=['admin'],
        tags=['Users', 'RBAC'],
        request_body={
            'required': True,
            'properties': {
                'role': {'type': 'string'}
            }
        },
        responses={
            200: {'description': 'Role revoked or not present'},
            400: {'description': 'Invalid request'},
            403: {'description': 'Insufficient permissions'},
            404: {'description': 'User not found'},
            500: {'description': 'Server error'}
        }
    )
    @token_required
    @require_roles('admin')
    def revoke_user_role_route(username):
        if not request.is_json:
            return jsonify({"message": "Request must be JSON."}), 400

        data = request.json or {}
        role = data.get('role')
        actor = getattr(g, 'current_user', None)

        success, message, user_doc = revoke_user_role(username=username, role=role, revoked_by=actor)
        if not success:
            status = 404 if message == "User not found." else 400
            return jsonify({"message": message}), status
        return jsonify({"message": message, "user": user_doc}), 200

    return token_required