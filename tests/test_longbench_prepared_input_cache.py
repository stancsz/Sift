import json

import pytest

from benchmarks.longbench_prepared_input_cache import (
    CACHE_SCHEMA_VERSION,
    PreparedInputCache,
    canonical_sha256,
    make_cache_key,
)


def _identity(**changes):
    values = {
        "manifest_sha256": "a" * 64,
        "source_hashes": {
            "dataset": "b" * 64,
            "renderer": "c" * 64,
            "sift_core": "d" * 64,
            "tokenizer": "e" * 64,
            "runner": "f" * 64,
        },
        "source_identities": {
            "dataset_revision": "fixture-revision",
            "model_id": "minimax/minimax-m3",
            "cache_implementation": "fixture-v1",
        },
        "case_id": "fixture-001",
        "dataset_index": 0,
        "arm": "sift",
        "protocol": {"max_tokens": 64, "temperature": 0.1, "seed": 9},
        "sift_parameters": {"target": 32_640, "raw_limit": 1_000_000},
    }
    values.update(changes)
    return values


def _key(**changes):
    return make_cache_key(**_identity(**changes))


def test_cold_then_warm_cache_preserves_prepared_messages_and_metadata(tmp_path):
    cache = PreparedInputCache(tmp_path / "cache")
    key = _key()
    messages = [
        {"role": "system", "content": "Use the supplied evidence."},
        {"role": "user", "content": "fixture prompt"},
    ]
    metadata = {
        "prompt_sha256": "1" * 64,
        "body_sha256": "2" * 64,
        "local_prompt_tokens": 12,
        "eligibility": {"status": "eligible_by_local_token_estimate"},
        "audit": {"method": "query_aware_extract"},
    }

    assert cache.get(key) is None
    path = cache.put(key, messages=messages, metadata=metadata)
    assert path.is_file()
    restored = cache.get(key)
    assert restored == {"messages": messages, "metadata": metadata}
    assert list(restored["messages"][0]) == ["role", "content"]
    assert canonical_sha256(restored["messages"]) == canonical_sha256(messages)


@pytest.mark.parametrize(
    "change",
    [
        {"manifest_sha256": "0" * 64},
        {"source_hashes": {**_identity()["source_hashes"], "renderer": "0" * 64}},
        {"source_hashes": {**_identity()["source_hashes"], "tokenizer": "0" * 64}},
        {"source_hashes": {**_identity()["source_hashes"], "sift_core": "0" * 64}},
        {"source_identities": {**_identity()["source_identities"], "cache_implementation": "fixture-v2"}},
        {"case_id": "fixture-002"},
        {"dataset_index": 1},
        {"arm": "full"},
        {"protocol": {"max_tokens": 32, "temperature": 0.1, "seed": 9}},
        {"sift_parameters": {"target": 24_448, "raw_limit": 1_000_000}},
    ],
)
def test_identity_changes_invalidate_cache_key(tmp_path, change):
    cache = PreparedInputCache(tmp_path / "cache")
    key = _key()
    cache.put(key, messages=[{"role": "user", "content": "fixture"}], metadata={})

    changed_key = _key(**change)
    assert changed_key != key
    assert cache.get(changed_key) is None


def test_corrupt_entry_is_a_cache_miss(tmp_path):
    cache = PreparedInputCache(tmp_path / "cache")
    key = _key()
    path = cache.put(
        key,
        messages=[{"role": "user", "content": "fixture"}],
        metadata={"body_sha256": "2" * 64},
    )
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["messages"][0]["content"] = "tampered"
    path.write_text(json.dumps(entry), encoding="utf-8")
    assert cache.get(key) is None


def test_stale_schema_and_wrong_key_are_cache_misses(tmp_path):
    cache = PreparedInputCache(tmp_path / "cache")
    key = _key()
    path = cache.put(key, messages=[], metadata={})
    entry = json.loads(path.read_text(encoding="utf-8"))

    entry["schema_version"] = CACHE_SCHEMA_VERSION + 1
    path.write_text(json.dumps(entry), encoding="utf-8")
    assert cache.get(key) is None

    entry["schema_version"] = CACHE_SCHEMA_VERSION
    entry["cache_key"] = "0" * 64
    path.write_text(json.dumps(entry), encoding="utf-8")
    assert cache.get(key) is None


@pytest.mark.parametrize(
    "metadata",
    [
        {"scoring_keys": {"fixture-001": "A"}},
        {"answer_key": "A"},
        {"responses": [{"text": "A"}]},
        {"provider_usage": {"cost": 0.01}},
        {"api_key": "must-not-be-cached"},
    ],
)
def test_put_rejects_scores_responses_usage_and_credentials(tmp_path, metadata):
    cache = PreparedInputCache(tmp_path / "cache")
    with pytest.raises(ValueError, match="Forbidden prepared-cache field"):
        cache.put(_key(), messages=[], metadata=metadata)
    assert not list((tmp_path / "cache").rglob("*.json"))


def test_cache_entry_contains_only_prepared_messages_and_metadata(tmp_path):
    cache = PreparedInputCache(tmp_path / "cache")
    key = _key()
    path = cache.put(
        key,
        messages=[{"role": "user", "content": "fixture prompt"}],
        metadata={"prompt_sha256": "1" * 64, "body_sha256": "2" * 64},
    )
    entry = json.loads(path.read_text(encoding="utf-8"))
    assert set(entry) == {
        "schema_version", "cache_key", "payload_sha256", "messages", "metadata"
    }
    assert entry["schema_version"] == CACHE_SCHEMA_VERSION
    serialized = path.read_text(encoding="utf-8")
    assert "scoring_keys" not in serialized
    assert "answer_key" not in serialized
