"""Content-addressed cache for deterministic LongBench request preparation.

This module has no provider, credential, dataset, or Sift imports. Callers build
the cache key from already-validated evaluation provenance, then store only the
prepared messages and deterministic metadata. A cache hit is never a substitute
for rebuilding and checking the canonical request-body hash at the call site.
"""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


CACHE_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ARMS = frozenset({"full", "sift"})
_FORBIDDEN_KEYS = frozenset({
    "answer", "answers", "answerkey", "answerkeys", "correctanswer",
    "correctanswers", "scoringkey", "scoringkeys", "expected",
    "expectedanswer", "expectedanswers", "response", "responses",
    "modeloutput", "modeloutputs", "completion", "completions",
    "credential", "credentials", "apikey", "authorization",
    "accesstoken", "receipt", "receipts", "output", "outputs",
    "usage", "providerusage", "usagecost", "cost", "costs",
})


def canonical_json(value: Any) -> bytes:
    """Encode JSON deterministically, rejecting non-JSON numeric values."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    """Return the SHA-256 of :func:`canonical_json`."""
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _require_sha256(label: str, value: Any) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _normal_key(value: Any) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _reject_sensitive_fields(value: Any, path: str = "payload") -> None:
    """Reject fields that could smuggle labels, outputs, or account data in."""
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _normal_key(key)
            if normalized in _FORBIDDEN_KEYS:
                raise ValueError(f"Forbidden prepared-cache field: {path}.{key}")
            _reject_sensitive_fields(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_sensitive_fields(child, f"{path}[{index}]")


def make_cache_key(
    *,
    manifest_sha256: str,
    source_hashes: Mapping[str, str],
    source_identities: Mapping[str, Any],
    case_id: str,
    dataset_index: int,
    arm: str,
    protocol: Mapping[str, Any],
    sift_parameters: Mapping[str, Any],
) -> str:
    """Build a key bound to the frozen inputs and one case/arm.

    ``manifest_sha256`` must be the exact SHA-256 of the frozen manifest file
    bytes. ``source_hashes`` must include ``renderer``, ``tokenizer``, and
    ``sift_core`` digests, alongside all other source hashes used by the caller.
    ``source_identities`` can bind non-file provenance such as dataset revision,
    model/tokenizer IDs, runtime/library versions, and cache implementation ID.
    """
    manifest_digest = _require_sha256("manifest_sha256", manifest_sha256)
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        raise ValueError("source_hashes must be a nonempty mapping")
    normalized_hashes: dict[str, str] = {}
    for name, digest in sorted(source_hashes.items()):
        if not isinstance(name, str) or not name:
            raise ValueError("source hash names must be nonempty strings")
        normalized_hashes[name] = _require_sha256(f"source_hashes[{name!r}]", digest)
    required_hashes = {"renderer", "tokenizer", "sift_core"}
    if not required_hashes.issubset(normalized_hashes):
        missing = ", ".join(sorted(required_hashes - normalized_hashes.keys()))
        raise ValueError(f"source_hashes missing required identities: {missing}")
    if not isinstance(source_identities, Mapping):
        raise ValueError("source_identities must be a mapping")
    if not isinstance(case_id, str) or not case_id:
        raise ValueError("case_id must be a nonempty string")
    if type(dataset_index) is not int or dataset_index < 0:
        raise ValueError("dataset_index must be a nonnegative integer")
    if arm not in _ARMS:
        raise ValueError("arm must be 'full' or 'sift'")
    if not isinstance(protocol, Mapping) or not isinstance(sift_parameters, Mapping):
        raise ValueError("protocol and sift_parameters must be mappings")

    identity = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "manifest_sha256": manifest_digest,
        "source_hashes": normalized_hashes,
        "source_identities": dict(source_identities),
        "case_id": case_id,
        "dataset_index": dataset_index,
        "arm": arm,
        "protocol": dict(protocol),
        "sift_parameters": dict(sift_parameters),
    }
    # These values define identity and must not carry outcome or account data.
    _reject_sensitive_fields(identity, "identity")
    return canonical_sha256(identity)


class PreparedInputCache:
    """Atomic local JSON cache rooted at a caller-selected directory."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not _SHA256_RE.fullmatch(key):
            raise ValueError("cache key must be a lowercase SHA-256 hex digest")
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        """Return a validated entry, or ``None`` for any stale/corrupt entry."""
        path = self._path(key)
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(entry, dict):
                return None
            if (entry.get("schema_version") != CACHE_SCHEMA_VERSION
                    or entry.get("cache_key") != key):
                return None
            messages = entry.get("messages")
            metadata = entry.get("metadata")
            if (not isinstance(messages, list)
                    or any(not isinstance(message, dict) for message in messages)
                    or not isinstance(metadata, dict)):
                return None
            payload = {"messages": messages, "metadata": metadata}
            _reject_sensitive_fields(payload)
            if entry.get("payload_sha256") != canonical_sha256(payload):
                return None
            return payload
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def put(self, key: str, *, messages: list[dict[str, Any]],
            metadata: Mapping[str, Any]) -> Path:
        """Write a content-checked entry atomically and return its path."""
        path = self._path(key)
        if not isinstance(messages, list) or any(not isinstance(item, dict) for item in messages):
            raise ValueError("messages must be a list of message objects")
        if not isinstance(metadata, Mapping):
            raise ValueError("metadata must be a mapping")
        payload = {"messages": messages, "metadata": dict(metadata)}
        _reject_sensitive_fields(payload)
        # Check canonicalizability before making a directory or temporary file.
        payload_hash = canonical_sha256(payload)
        entry = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "cache_key": key,
            "payload_sha256": payload_hash,
            **payload,
        }
        # Preserve insertion order inside prepared messages. The frozen prompt
        # digest is computed from the request object's original JSON encoding,
        # so sorting nested message keys would make a valid warm entry fail its
        # prompt-hash recheck. Payload integrity still uses canonical JSON.
        encoded = json.dumps(
            entry,
            ensure_ascii=False,
            sort_keys=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") + b"\n"
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", prefix=f".{key}.", suffix=".tmp",
                dir=path.parent, delete=False,
            ) as temporary:
                temp_path = Path(temporary.name)
                temporary.write(encoded)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temp_path, path)
            temp_path = None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
        return path
