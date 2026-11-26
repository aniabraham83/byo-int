from pymongo import MongoClient
import hashlib, os
import base64
import time
from datetime import datetime, timezone
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

try:
    import redis
except Exception:
    redis = None

mongo_username = os.environ.get("MONGO_USERNAME")
mongo_password = os.environ.get("MONGO_PASSWORD")
mongo_host = os.environ.get("MONGO_HOST")
mongo_port = os.environ.get("MONGO_PORT")

SESSION_IDLE_MINUTES = max(5, int(os.environ.get("SESSION_IDLE_MINUTES", "30")))
SESSION_ABSOLUTE_HOURS = max(1, int(os.environ.get("SESSION_ABSOLUTE_HOURS", "8")))
DATAPULL_SECRET_KEY_ENV = "DATAPULL_SECRET_MASTER_KEY"
_REDIS_CLIENTS = {}
_REDIS_INIT_ATTEMPTED = set()
_API_AUDIT_INDEX_READY = False


def _utc_now():
    return datetime.now(timezone.utc)


def _normalize_utc(dt_value):
    if not dt_value:
        return None
    if getattr(dt_value, "tzinfo", None) is None:
        return dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(timezone.utc)


def _hash_session_id(session_id):
    return hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()


def _b64_encode(raw_bytes):
    return base64.urlsafe_b64encode(raw_bytes).decode("utf-8")


def _b64_decode(raw_text):
    padded = str(raw_text) + "=" * (-len(str(raw_text)) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _get_datapull_secret_master_key():
    """Return a 32-byte key used for datapull secret encryption."""
    raw_key = os.environ.get(DATAPULL_SECRET_KEY_ENV) or os.environ.get("SECRET_MASTER_KEY")
    if not raw_key:
        raise ValueError(
            f"Missing encryption key. Set {DATAPULL_SECRET_KEY_ENV} (preferred) or SECRET_MASTER_KEY"
        )

    # Prefer urlsafe-base64 encoded 32-byte key, but accept raw 32-char fallback.
    try:
        decoded = _b64_decode(raw_key)
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass

    raw_bytes = str(raw_key).encode("utf-8")
    if len(raw_bytes) != 32:
        raise ValueError(
            f"Invalid master key length. {DATAPULL_SECRET_KEY_ENV} must decode to 32 bytes"
        )
    return raw_bytes


def _encrypt_datapull_secret_value(secret_value):
    key = _get_datapull_secret_master_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, str(secret_value).encode("utf-8"), None)
    return {
        "algorithm": "AES256-GCM",
        "nonce": _b64_encode(nonce),
        "ciphertext": _b64_encode(ciphertext)
    }


def _decrypt_datapull_secret_value(doc):
    key = _get_datapull_secret_master_key()
    aesgcm = AESGCM(key)
    nonce = _b64_decode(doc.get("nonce"))
    ciphertext = _b64_decode(doc.get("ciphertext"))
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")

def connect_mongodb():
    try:
        mongo_connect_string = f'mongodb://{mongo_username}:{mongo_password}@{mongo_host}:{mongo_port}'
        client = MongoClient(mongo_connect_string)
        return client,mongo_connect_string
    except Exception as e:
        print (e)


ALLOW_CUSTOM_SNIPPET_KEY = "allow_custom_snippet"
CUSTOM_SNIPPET_DISABLED_MESSAGE = (
    "Custom snippets are disabled. An admin can enable 'allow_custom_snippet' on the "
    "Configuration page (module 'core'). Snippets run as Python code inside the app and are not sandboxed."
)


_CUSTOM_SNIPPET_CACHE_TTL_SECONDS = 10
_custom_snippet_cache = {"value": False, "expires": 0.0}


def is_custom_snippet_allowed():
    """Return True only when the core config explicitly sets allow_custom_snippet to true.

    Fails closed: a missing value, a non-boolean value, or a database error all count as disabled.
    The result is cached briefly because enrichment snippets are checked once per indicator,
    so a change on the Configuration page takes effect within the cache TTL.
    """
    now = time.monotonic()
    if now < _custom_snippet_cache["expires"]:
        return _custom_snippet_cache["value"]

    client = None
    allowed = False
    try:
        client, _ = connect_mongodb()
        core_doc = client["byoint_core_config"]["basicconfigs"].find_one(
            {"module": "core"}, {ALLOW_CUSTOM_SNIPPET_KEY: 1}
        ) or {}
        allowed = core_doc.get(ALLOW_CUSTOM_SNIPPET_KEY) is True
    except Exception as e:
        print(f"Warning: failed to read {ALLOW_CUSTOM_SNIPPET_KEY}; treating custom snippets as disabled: {e}")
    finally:
        if client:
            client.close()

    _custom_snippet_cache["value"] = allowed
    _custom_snippet_cache["expires"] = now + _CUSTOM_SNIPPET_CACHE_TTL_SECONDS
    return allowed


def get_redis_client(socket_timeout=1, socket_connect_timeout=1, decode_responses=True):
    client_key = (
        float(socket_timeout),
        float(socket_connect_timeout),
        bool(decode_responses),
    )

    if client_key in _REDIS_CLIENTS:
        return _REDIS_CLIENTS[client_key]
    if client_key in _REDIS_INIT_ATTEMPTED:
        return None

    _REDIS_INIT_ATTEMPTED.add(client_key)
    if redis is None:
        return None

    try:
        redis_url = str(os.getenv("REDIS_URL") or "").strip()
        if redis_url:
            client = redis.from_url(
                redis_url,
                decode_responses=decode_responses,
                socket_timeout=float(socket_timeout),
                socket_connect_timeout=float(socket_connect_timeout),
            )
        else:
            redis_host = str(os.getenv("REDIS_HOST") or "").strip()
            if not redis_host:
                return None

            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            redis_db = int(os.getenv("REDIS_DB", "0"))
            redis_password = os.getenv("REDIS_PASSWORD")
            client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                decode_responses=decode_responses,
                socket_timeout=float(socket_timeout),
                socket_connect_timeout=float(socket_connect_timeout),
            )

        client.ping()
        _REDIS_CLIENTS[client_key] = client
        return client
    except Exception:
        return None


def write_api_audit_log(audit_doc):
    global _API_AUDIT_INDEX_READY

    mongo_client = None
    try:
        mongo_client, _ = connect_mongodb()
        if not mongo_client:
            return False

        db = mongo_client["byoint_core_data"]
        audit_logs = db["api_audit_logs"]
        if not _API_AUDIT_INDEX_READY:
            audit_logs.create_index([("created_at", -1), ("request_id", 1)])
            audit_logs.create_index([("path", 1), ("created_at", -1)])
            _API_AUDIT_INDEX_READY = True

        audit_logs.insert_one(audit_doc)
        return True
    except Exception as e:
        print(e)
        return False
    finally:
        if mongo_client:
            mongo_client.close()



