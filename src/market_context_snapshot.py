"""Market context snapshot validation, storage, and loading helpers."""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MARKET_CONTEXT_REQUIRED_FIELDS = (
    "public_listing.title",
    "public_listing.price_display",
    "public_listing.rating",
    "public_listing.review_count",
    "public_listing.delivery_promise",
    "public_listing.fulfillment_method",
    "public_listing.coupon_present",
    "public_listing.deal_present",
    "rank.own_bsr_leaf_rank",
    "rank.own_bsr_leaf_category",
    "core_keywords",
    "market.selected_competitors",
)


class SnapshotValidationError(ValueError):
    """Raised when a market context snapshot is not complete enough to publish."""


def _encryption_key(secret: str) -> bytes:
    if not secret:
        raise SnapshotValidationError("MARKET_CONTEXT_SNAPSHOT_ENCRYPTION_KEY is required")
    return hashlib.sha256(secret.encode("utf-8")).digest()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode("ascii"))


def _parse_time(value: str) -> datetime:
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _get_path(data: Mapping[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
    return current


def _missing_required_fields(context: Mapping[str, Any], required_fields: Iterable[str]) -> list[str]:
    missing = []
    for field in required_fields:
        value = _get_path(context, field)
        if value in (None, "", [], {}):
            missing.append(field)
    return missing


def validate_market_context_snapshot(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    if snapshot.get("snapshot_status") != "complete":
        raise SnapshotValidationError("snapshot_status must be complete")
    captured_at = snapshot.get("captured_at")
    if not captured_at:
        raise SnapshotValidationError("captured_at is required")
    _parse_time(str(captured_at))
    context = snapshot.get("market_context")
    if not isinstance(context, Mapping):
        raise SnapshotValidationError("market_context mapping is required")
    missing = _missing_required_fields(context, MARKET_CONTEXT_REQUIRED_FIELDS)
    if missing:
        raise SnapshotValidationError("missing required fields: " + ", ".join(missing))
    keywords = context.get("core_keywords")
    if not isinstance(keywords, list) or len(keywords) < 3:
        raise SnapshotValidationError("core_keywords must contain at least 3 rows")
    return copy.deepcopy(dict(snapshot))


def encrypt_snapshot(snapshot: Mapping[str, Any], *, key: str) -> Dict[str, Any]:
    validated = validate_market_context_snapshot(snapshot)
    plaintext = json.dumps(validated, ensure_ascii=False, sort_keys=True).encode("utf-8")
    nonce = os.urandom(12)
    ciphertext = AESGCM(_encryption_key(key)).encrypt(nonce, plaintext, None)
    return {
        "schema_version": "1.0",
        "envelope_type": "market_context_snapshot",
        "algorithm": "AES-256-GCM",
        "nonce": _b64encode(nonce),
        "ciphertext": _b64encode(ciphertext),
        "created_at": validated["captured_at"],
    }


def decrypt_snapshot_envelope(envelope: Mapping[str, Any], *, key: str) -> Dict[str, Any]:
    if envelope.get("algorithm") != "AES-256-GCM":
        raise SnapshotValidationError("unsupported snapshot encryption algorithm")
    nonce = _b64decode(str(envelope.get("nonce") or ""))
    ciphertext = _b64decode(str(envelope.get("ciphertext") or ""))
    plaintext = AESGCM(_encryption_key(key)).decrypt(nonce, ciphertext, None)
    parsed = json.loads(plaintext.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise SnapshotValidationError("decrypted snapshot must be a JSON object")
    return validate_market_context_snapshot(parsed)


def snapshot_freshness(
    captured_at: str,
    *,
    now: Optional[datetime] = None,
    stale_minutes: int = 10,
    expired_minutes: int = 120,
) -> Dict[str, Any]:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    captured = _parse_time(captured_at)
    age_minutes = int(max((current - captured).total_seconds(), 0) // 60)
    if age_minutes <= stale_minutes:
        status = "fresh"
    elif age_minutes <= expired_minutes:
        status = "stale"
    else:
        status = "expired"
    return {
        "status": status,
        "age_minutes": age_minutes,
        "captured_at": captured_at,
    }


def apply_snapshot_to_dashboard(
    dashboard: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    *,
    now: Optional[datetime] = None,
    stale_minutes: int = 10,
    expired_minutes: int = 120,
) -> Dict[str, Any]:
    validated = validate_market_context_snapshot(snapshot)
    result = copy.deepcopy(dict(dashboard))
    context = result.setdefault("context", {})
    context.update(copy.deepcopy(validated["market_context"]))
    freshness = snapshot_freshness(
        str(validated["captured_at"]),
        now=now,
        stale_minutes=stale_minutes,
        expired_minutes=expired_minutes,
    )
    status = freshness["status"]
    message = f"Market context snapshot is {status}; captured {freshness['age_minutes']} minutes ago."
    if status == "expired":
        message = f"Market context snapshot is expired; captured {freshness['age_minutes']} minutes ago."
    context["public_context_status"] = {
        **dict(context.get("public_context_status") or {}),
        "status": status,
        "message": message,
        "source": "market_context_snapshot",
        "captured_at": validated["captured_at"],
        "snapshot_age_minutes": freshness["age_minutes"],
        "warnings": list(validated.get("warnings") or []),
    }
    return result


def load_snapshot_from_url(url: str, *, token: Optional[str] = None, timeout: int = 5) -> Dict[str, Any]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise SnapshotValidationError("snapshot response must be a JSON object")
    return validate_market_context_snapshot(parsed)


def load_encrypted_snapshot_from_url(url: str, *, key: str, timeout: int = 5) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise SnapshotValidationError("encrypted snapshot response must be a JSON object")
    return decrypt_snapshot_envelope(parsed, key=key)


def write_snapshot_atomically(
    snapshot: Mapping[str, Any],
    *,
    latest_path: Path,
    history_path: Optional[Path] = None,
) -> None:
    validated = validate_market_context_snapshot(snapshot)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = latest_path.with_name(latest_path.name + ".tmp")
    body = json.dumps(validated, ensure_ascii=False, indent=2, sort_keys=True)
    tmp_path.write_text(body + "\n", encoding="utf-8")
    os.replace(tmp_path, latest_path)
    if history_path:
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(body + "\n", encoding="utf-8")


def cleanup_history(history_dir: Path, *, now: Optional[datetime] = None, retention_hours: int = 24) -> None:
    if not history_dir.exists():
        return
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current.timestamp() - max(int(retention_hours), 1) * 3600
    for path in history_dir.rglob("*.json"):
        path_date_expired = False
        try:
            path_day = datetime.strptime(path.parent.name, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            path_date_expired = path_day.timestamp() < cutoff
        except ValueError:
            path_date_expired = False
        if path.stat().st_mtime < cutoff or path_date_expired:
            path.unlink()
    for directory in sorted([p for p in history_dir.rglob("*") if p.is_dir()], reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def history_path_for_snapshot(base_dir: Path, captured_at: str) -> Path:
    captured = _parse_time(captured_at)
    return base_dir / "history" / captured.strftime("%Y-%m-%d") / f"{captured.strftime('%H-%M-%S')}.json"


def copy_if_complete(snapshot: Mapping[str, Any], destination: Path) -> None:
    """Validate before writing a local artifact for scripts."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    validated = validate_market_context_snapshot(snapshot)
    destination.write_text(json.dumps(validated, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
