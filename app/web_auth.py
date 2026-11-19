"""Web authentication policy and sessions for the current application's runtime."""

import functools
import logging
import os
import secrets
import time
from collections.abc import Mapping

from cryptography.hazmat.primitives import hashes, hmac
from flask import current_app, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .runtime import current_runtime

log = logging.getLogger("docsis.web")
audit_log = logging.getLogger("docsis.audit")

_LOGIN_MAX_ATTEMPTS = 5
_LOGIN_WINDOW = 900  # 15 min
_LOGIN_LOCKOUT_BASE = 30  # seconds, doubles each excess attempt
_LOGIN_MAX_TRACKED_IPS = 2048
_LOGIN_CSRF_SESSION_KEY = "login_csrf_token"
_AUTH_MARKER_SESSION_KEY = "auth_marker"
_AUTH_MARKER_CONTEXT = b"docsight-admin-session-v1\0"
# v2: backups made before this version contain .session_key. Changing the
# context makes every existing installation rotate its signing key once on
# startup, so cookies can no longer be forged from such a backup.
_AUTH_STATE_CONTEXT = b"docsight-admin-auth-state-v2\0"
_SESSION_LIFETIME_DEFAULT_DAYS = 30
_SESSION_LIFETIME_MIN_DAYS = 1
_SESSION_LIFETIME_MAX_DAYS = 365
_SETUP_PASSWORD_MIN_LENGTH = 8
_SETUP_WINDOW_SECONDS = 900  # 15 min after start
_TOKEN_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _get_client_ip():
    """Get client IP from request.remote_addr.

    When REVERSE_PROXY is configured, Werkzeug's ProxyFix middleware
    rewrites remote_addr from trusted X-Forwarded-For headers before
    the request reaches Flask.  Without ProxyFix the raw TCP peer
    address is used, which prevents X-Forwarded-For spoofing.
    """
    return request.remote_addr or "unknown"


def confirmed_delete_all(data, delete_all, what):
    """Answer a bulk delete of everything, which must carry confirm="DELETE_ALL"."""
    if data.get("confirm") != "DELETE_ALL":
        return jsonify({"error": "Confirmation required: set confirm to 'DELETE_ALL'"}), 400
    deleted = delete_all()
    audit_log.info("All %s deleted: ip=%s count=%d", what, _get_client_ip(), deleted)
    return jsonify({"deleted": deleted})


def _get_login_csrf_token():
    """Return the session-bound token used by the login form."""
    token = session.get(_LOGIN_CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[_LOGIN_CSRF_SESSION_KEY] = token
    return token


def _valid_login_csrf_token(candidate):
    """Validate the submitted login CSRF token against the session token."""
    token = session.get(_LOGIN_CSRF_SESSION_KEY)
    return bool(
        token and candidate
        and secrets.compare_digest(token.encode("utf-8"), candidate.encode("utf-8"))
    )

def _rotate_session_key():
    """Persist and activate a new signing key, invalidating all old cookies."""
    key = current_runtime().auth_state.rotate_session_key()
    # In-memory activation assumes today's single-process waitress deployment;
    # a future multi-worker server must coordinate shared signing-key rotation.
    current_app.secret_key = key


def _session_lifetime_days(environ: Mapping[str, str] | None = None):
    """Return the safe, bounded operator-configured session lifetime."""
    env = os.environ if environ is None else environ
    configured = env.get("SESSION_LIFETIME_DAYS", "").strip()
    if not configured:
        return _SESSION_LIFETIME_DEFAULT_DAYS
    try:
        days = int(configured)
    except (TypeError, ValueError):
        log.warning(
            "Invalid SESSION_LIFETIME_DAYS; using %d days",
            _SESSION_LIFETIME_DEFAULT_DAYS,
        )
        return _SESSION_LIFETIME_DEFAULT_DAYS
    return max(_SESSION_LIFETIME_MIN_DAYS, min(_SESSION_LIFETIME_MAX_DAYS, days))

def _keyed_sha256_hexdigest(key: bytes, message: bytes) -> str:
    """Return the HMAC-SHA256 of message as lowercase hexadecimal."""
    mac = hmac.HMAC(key, hashes.SHA256())
    mac.update(message)
    return mac.finalize().hex()


def _secret_values_match(left, right):
    """Compare secret representations without timing-sensitive equality."""
    return secrets.compare_digest(
        str(left or "").encode(), str(right or "").encode()
    )


def _admin_password_matches(effective_password, candidate):
    """Safely check whether candidate represents the current admin password."""
    effective_password = str(effective_password or "")
    candidate = str(candidate or "")
    if effective_password.startswith(("scrypt:", "pbkdf2:")):
        try:
            return check_password_hash(effective_password, candidate)
        except (TypeError, ValueError):
            return False
    return _secret_values_match(effective_password, candidate)


def _get_admin_password():
    """Return the current application's effective admin-password representation."""
    return current_runtime().config_manager.get("admin_password", "")


def _auth_state_fingerprint(password_representation=None):
    """Return a keyed fingerprint of the effective admin-password state."""
    if password_representation is None:
        password_representation = _get_admin_password()
    key = current_app.secret_key.encode() if isinstance(current_app.secret_key, str) else current_app.secret_key
    value = _AUTH_STATE_CONTEXT + str(password_representation or "").encode("utf-8")
    return _keyed_sha256_hexdigest(key, value)


def _write_auth_state():
    fingerprint = _auth_state_fingerprint()
    current_runtime().auth_state.write_fingerprint(fingerprint)


def _init_auth_state():
    """Rotate the signing key unless auth state proves it is current.

    Missing, unreadable or outdated auth state means the key may come from an
    older version or a backup, so cookies signed with it must stop working.
    """
    stored = current_runtime().auth_state.read_fingerprint()
    if stored is None or not _secret_values_match(stored, _auth_state_fingerprint()):
        _rotate_session_key()
        _write_auth_state()


def bootstrap_auth_state(app, runtime):
    """Initialize durable authentication state for a newly created app."""
    if app.extensions.get("docsight") is not runtime:
        raise RuntimeError("DOCSight runtime is not attached to this application")
    with app.app_context():
        _init_auth_state()


def _sync_auth_state():
    """Observe runtime auth changes and durably invalidate existing cookies."""
    stored = current_runtime().auth_state.read_fingerprint()
    current = _auth_state_fingerprint()
    if stored is not None and _secret_values_match(stored, current):
        return
    _rotate_session_key()
    _write_auth_state()


def _admin_session_marker(password_representation=None):
    """Create a keyed, non-reversible marker for the effective password state."""
    if password_representation is None:
        password_representation = _get_admin_password()
    if not password_representation:
        return ""
    key = current_app.secret_key.encode() if isinstance(current_app.secret_key, str) else current_app.secret_key
    value = _AUTH_MARKER_CONTEXT + str(password_representation).encode("utf-8")
    return _keyed_sha256_hexdigest(key, value)


def _authenticated_session_is_valid():
    """Return True only for a password-bound authenticated browser session."""
    if not session.get("authenticated"):
        return False
    actual = session.get(_AUTH_MARKER_SESSION_KEY, "")
    expected = _admin_session_marker()
    if actual and expected and _secret_values_match(actual, expected):
        return True
    session.clear()
    return False


def _invalidate_admin_sessions():
    """Globally invalidate signed cookies and clear the current request session."""
    _rotate_session_key()
    _write_auth_state()
    # The request cookie was loaded with the prior key. Clearing after rotation
    # makes Flask write the logged-out session using the new key on this response.
    session.clear()


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def auth_disabled_requested(environ: Mapping[str, str]) -> bool:
    """Whether the operator deliberately runs DOCSight without an admin password."""
    return _truthy(environ.get("AUTH_DISABLED"))


def desktop_mode_requested(environ: Mapping[str, str]) -> bool:
    """The Windows desktop app listens only on this computer."""
    return environ.get("DOCSIGHT_DESKTOP_MODE") == "1"


def _open_without_password():
    if current_app.config.get("DOCSIGHT_AUTH_DISABLED") or current_app.config.get("DOCSIGHT_DESKTOP_MODE"):
        return True
    return current_runtime().config_manager.is_demo_mode()


def password_setup_pending():
    """True while nobody may use DOCSight until an admin password is set."""
    return not _get_admin_password() and not _open_without_password()


def password_setup_open():
    """The first admin password can only be set shortly after DOCSight starts."""
    return time.monotonic() < current_runtime().password_setup_deadline


def announce_password_setup(app):
    """Open the password setup window and tell the operator about it in the log."""
    with app.app_context():
        current_runtime().password_setup_deadline = time.monotonic() + _SETUP_WINDOW_SECONDS
        if password_setup_pending():
            log.warning(
                "DOCSight has no admin password yet. Open DOCSight in your browser within "
                "15 minutes to set one. After that, restart DOCSight to set it."
            )
        elif not _get_admin_password() and current_app.config.get("DOCSIGHT_AUTH_DISABLED"):
            log.warning(
                "AUTH_DISABLED is set: DOCSight runs without an admin password, so everyone "
                "who can reach it can see and change everything, including stored passwords."
            )


def _auth_required(*, session_only=False):
    """Check if auth is enabled and user is not logged in.

    Also checks for valid Bearer token in Authorization header.
    Returns True if authentication is required but not provided.
    """
    _storage = current_runtime().storage
    _sync_auth_state()
    if not _get_admin_password():
        return password_setup_pending()
    if _authenticated_session_is_valid():
        return False
    auth_header = request.headers.get("Authorization", "")
    # Tokens authenticate API calls only; pages such as Settings need a session.
    if not session_only and request.path.startswith("/api/") and auth_header.startswith("Bearer ") and _storage:
        token = auth_header[7:]
        token_info = _storage.validate_api_token(token)
        if token_info:
            request._api_token = token_info
            return False
    return True


def _refuse_token():
    audit_log.warning(
        "API token refused, session required: method=%s path=%s ip=%s",
        request.method, request.path, _get_client_ip(),
    )
    return jsonify({"error": "Session authentication required"}), 403


def require_auth(f=None, *, session_only=False, token_writes=False):
    """Decorator: redirect to /login or return 401 JSON for API paths.

    API tokens are meant for integrations. They may read, but a route accepts
    a write from a token only when it opts in with ``token_writes=True``; every
    other write needs a signed-in admin session. ``session_only=True`` refuses
    tokens entirely.
    """
    if f is None:
        return functools.partial(require_auth, session_only=session_only, token_writes=token_writes)

    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if _auth_required(session_only=session_only):
            if password_setup_pending():
                if request.path.startswith("/api/"):
                    return jsonify({"error": "Admin password not set", "setup_required": True}), 401
                return redirect(url_for("password_setup"))
            if session_only and (getattr(request, "_api_token", None) or request.headers.get("Authorization", "").startswith("Bearer ")):
                return _refuse_token()
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required"}), 401
            return redirect(url_for("login"))
        if getattr(request, "_api_token", None) and not token_writes and request.method not in _TOKEN_READ_METHODS:
            return _refuse_token()
        return f(*args, **kwargs)

    decorated.docsight_token_access = "none" if session_only else ("write" if token_writes else "read")
    return decorated


def _require_session_auth(f):
    """Decorator: only allow session-based login, no API tokens."""
    return require_auth(f, session_only=True)


def _authenticate_login():
    """Validate a login submission and establish its password-bound session."""
    _config_manager = current_runtime().config_manager
    ip = _get_client_ip()
    limiter = current_runtime().login_rate_limiter
    if not _valid_login_csrf_token(request.form.get("csrf_token", "")):
        limiter.record_failure(ip)
        audit_log.warning("Login rejected: invalid csrf token for ip=%s", ip)
        return "login_failed", 400
    wait = limiter.retry_after(ip)
    if wait > 0:
        audit_log.warning("Login rate-limited: ip=%s (retry in %ds)", ip, int(wait))
        return "login_rate_limited", 200
    pw = request.form.get("password", "")
    stored = _config_manager.get("admin_password", "")
    if stored.startswith(("scrypt:", "pbkdf2:")):
        success = check_password_hash(stored, pw)
    else:
        success = _secret_values_match(pw, stored)
        if success and not os.environ.get("ADMIN_PASSWORD"):
            # Auto-upgrade plaintext password to hash
            _config_manager.save({"admin_password": pw})
            stored = _config_manager.get("admin_password", "")
            # This is the same credential in a safer representation, so
            # preserve the signing key while rebinding durable auth state.
            _write_auth_state()
            audit_log.info("Auto-upgraded plaintext password to hash for ip=%s", ip)
    if success:
        limiter.reset(ip)
        session.permanent = True
        session["authenticated"] = True
        session[_AUTH_MARKER_SESSION_KEY] = _admin_session_marker(stored)
        session.pop(_LOGIN_CSRF_SESSION_KEY, None)
        audit_log.info("Login successful: ip=%s", ip)
        return None, 302
    limiter.record_failure(ip)
    audit_log.warning("Login failed: ip=%s", ip)
    return "login_failed", 200


def _set_first_admin_password():
    """Validate a setup submission and sign in with the new admin password."""
    _config_manager = current_runtime().config_manager
    ip = _get_client_ip()
    if not _valid_login_csrf_token(request.form.get("csrf_token", "")):
        audit_log.warning("Password setup rejected: invalid csrf token for ip=%s", ip)
        return "password_setup_failed", 400
    if not password_setup_open():
        audit_log.warning("Password setup rejected: setup window closed for ip=%s", ip)
        return "password_setup_expired", 403
    password = request.form.get("password", "")
    if len(password) < _SETUP_PASSWORD_MIN_LENGTH:
        return "password_setup_too_short", 200
    if not _secret_values_match(password, request.form.get("password_confirm", "")):
        return "password_setup_mismatch", 200
    with current_runtime().password_setup_lock:
        # Two visitors may submit at once; only the first may set the password.
        if _get_admin_password():
            return "password_setup_failed", 409
        # Hashed here: save() would keep a password that starts like a hash ("scrypt:...") as it is.
        _config_manager.save({"admin_password": generate_password_hash(password)})
    stored = _config_manager.get("admin_password", "")
    _invalidate_admin_sessions()
    session.permanent = True
    session["authenticated"] = True
    session[_AUTH_MARKER_SESSION_KEY] = _admin_session_marker(stored)
    audit_log.info("First admin password set: ip=%s", ip)
    return None, 302
