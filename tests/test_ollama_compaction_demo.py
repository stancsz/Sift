from contextlib import redirect_stdout
from io import StringIO
import json
import sys
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from examples import ollama_compaction_demo as demo


def test_demo_requires_approved_and_previous_probe_values_with_reason():
    answer = (
        "The operator approved initialDelaySeconds=25 after the readiness probe "
        "was configured with initialDelaySeconds=5."
    )

    assert demo.answers_buried_setting(answer)


def test_demo_rejects_a_partial_answer_even_if_it_names_approved_value():
    assert not demo.answers_buried_setting("initialDelaySeconds=25")


def test_demo_main_rejects_uncompacted_or_incorrect_responses():
    valid_result = {"choices": [{"message": {"content":
        "The readiness probe changed from initialDelaySeconds=5 to initialDelaySeconds=25."}}]}
    for compacted, result in (
        ("false", valid_result),
        ("true", {"choices": [{"message": {"content": "initialDelaySeconds=5"}}]}),
    ):
        response = MagicMock()
        response.headers = {"x-sift-compacted": compacted}
        response.read.return_value = json.dumps(result).encode("utf-8")
        response.__enter__.return_value = response
        with patch.object(sys, "argv", ["ollama_compaction_demo"]), \
                patch.object(demo, "urlopen", return_value=response), \
                redirect_stdout(StringIO()):
            assert demo.main() == 1


def test_demo_main_returns_failure_when_sift_is_unreachable():
    with patch.object(sys, "argv", ["ollama_compaction_demo"]), \
            patch.object(demo, "urlopen", side_effect=URLError("connection refused")), \
            redirect_stdout(StringIO()):
        assert demo.main() == 1
