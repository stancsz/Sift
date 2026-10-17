import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmarks"))

import analyze_longbench_v2_minimax_hybrid_stage2_corrected as analyzer  # noqa: E402


def test_comparison_outcomes_use_valid_plural_keys():
    assert analyzer._comparison_key("win") == "wins"
    assert analyzer._comparison_key("loss") == "losses"
    assert analyzer._comparison_key("tie") == "ties"


def test_route_pricing_accepts_frozen_normalized_snapshot(tmp_path):
    path = tmp_path / "route.json"
    path.write_text(json.dumps({
        "requested_model": "minimax/minimax-m3",
        "provider": "Minimax",
        "endpoint_model_id": "minimax/minimax-m3",
        "pricing_usd_per_token": {
            "prompt": "0.0000003", "completion": "0.0000012",
            "input_cache_read": "0.00000006",
        },
    }), encoding="utf-8")

    assert analyzer._route_pricing(path) == (0.3, 1.2, 0.06)


def test_route_pricing_accepts_raw_endpoint_snapshot(tmp_path):
    path = tmp_path / "route.json"
    path.write_text(json.dumps({"data": {"endpoints": [{
        "model_id": "minimax/minimax-m3", "provider_name": "Minimax",
        "pricing": {
            "prompt": "0.0000003", "completion": "0.0000012",
            "input_cache_read": "0.00000006",
        },
    }]} }), encoding="utf-8")

    assert analyzer._route_pricing(path) == (0.3, 1.2, 0.06)


def test_read_json_accepts_gzip(tmp_path):
    path = tmp_path / "report.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump({"status": "complete"}, stream)

    assert analyzer._read_json(path) == {"status": "complete"}


def test_content_hash_for_gzip_matches_original_bytes(tmp_path):
    plain = tmp_path / "baseline.json"
    plain.write_bytes(b'{"manifest_sha256":"frozen"}\n')
    compressed = tmp_path / "baseline.json.gz"
    with plain.open("rb") as source, compressed.open("wb") as raw, gzip.GzipFile(
        filename="", mode="wb", fileobj=raw, mtime=0
    ) as stream:
        stream.write(source.read())

    assert analyzer._content_sha256(compressed) == analyzer._content_sha256(plain)
    assert analyzer.sha(compressed) != analyzer.sha(plain)
