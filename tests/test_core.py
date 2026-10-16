import copy
import csv
import json
from io import StringIO
import unittest

from sift import CompactionError, compact_messages


def estimate(messages):
    return (len(json.dumps(messages, ensure_ascii=False)) + 3) // 4


def message(role, content, **extra):
    return {"role": role, "content": content, **extra}


def topic_history():
    history = [message("system", "Keep recorded facts exact.")]
    for index in range(20):
        if index < 10:
            record = (f"PAYMENT invoice billing PAYMENT_FACT_{index:02d} "
                      f"settled at window 2026-10-{index + 1:02d}; ")
        else:
            record = (f"INCIDENT rollback alert INCIDENT_FACT_{index:02d} "
                      f"restored at window 2026-11-{index + 1:02d}; ")
        history.append(message("user", f"Record {index}: " + record * 18))
    return history


class CompactionTests(unittest.TestCase):
    def test_small_input_is_unchanged_and_audited(self):
        source = [message("system", "Follow project policy"), message("user", "hello")]
        result = compact_messages(source, estimate, target=200)
        self.assertEqual(result.messages, source)
        self.assertIsNot(result.messages, source)
        self.assertFalse(result.audit["compacted"])
        self.assertEqual(result.audit["input_tokens"], estimate(source))
        self.assertEqual(result.audit["forwarded_tokens"], estimate(source))

    def test_middle_relevant_evidence_beats_noise(self):
        lines = ["ordinary build progress line " + str(i) for i in range(400)]
        lines[201] = "MIDDLE_KEY: azure-73; this is the deployment setting"
        source = [message("system", "Be accurate"), message("user", "\n".join(lines)),
                  message("assistant", "Log received"),
                  message("user", "What was the MIDDLE_KEY deployment setting?")]
        result = compact_messages(source, estimate, target=500)
        self.assertTrue(result.audit["compacted"])
        self.assertLessEqual(result.audit["forwarded_tokens"], 500)
        self.assertEqual(result.messages[0], source[0])
        self.assertEqual(result.messages[-1], source[-1])
        summaries = "\n".join(
            item.get("content", "") for item in result.messages
            if item.get("role") == "user" and isinstance(item.get("content"), str)
        )
        self.assertIn("azure-73", summaries)
        self.assertIn("untrusted", summaries.lower())

    def test_selected_failure_keeps_neighboring_diagnostic(self):
        lines = [f"routine build output {i}" for i in range(1_000)]
        lines[500] = "FAILED test_invoice_total"
        lines[501] = "rounding_mode=HALF_EVEN; observed +0.01 versus Decimal expected"
        source = [message("user", "\n".join(lines)),
                  message("assistant", "Build log received"),
                  message("user", "What caused FAILED test_invoice_total?")]
        result = compact_messages(source, estimate, target=700)
        evidence = str(result.messages)
        self.assertIn("FAILED test_invoice_total", evidence)
        self.assertIn("rounding_mode=HALF_EVEN", evidence)
        self.assertLessEqual(result.audit["forwarded_tokens"], 700)

    def test_current_tool_chain_and_prior_complete_turn_survive(self):
        prior = [message("user", "Run tests"),
                 message("assistant", None, tool_calls=[{"id": "x", "function": {"name": "test", "arguments": "{}"}}]),
                 message("tool", "FAILED: test_gateway", tool_call_id="x"),
                 message("assistant", "Need repair")]
        current = [message("user", "Fix test_gateway"), message("assistant", "Checking")]
        source = [message("system", "Safety"), message("user", "noise " * 2500),
                  message("assistant", "old"), *prior, *current]
        saved = copy.deepcopy(source)
        result = compact_messages(source, estimate, target=700)
        self.assertEqual(source, saved)
        self.assertEqual(result.messages[-6:], prior + current)
        self.assertLessEqual(result.audit["forwarded_tokens"], 700)
        self.assertGreaterEqual(result.audit["preserved_recent_turns"], 1)

    def test_legacy_function_call_cycle_survives_compaction(self):
        task = message("user", "Find the current deployment setting.")
        cycles = []
        for index in range(12):
            cycles.extend([
                message("assistant", None, function_call={
                    "name": "read_file", "arguments": json.dumps({"path": f"config-{index}.py"}),
                }),
                message("function", f"config result {index}: " + "deployment setting evidence " * 42,
                        name="read_file"),
            ])
        current_answer = message("assistant", "The latest file is authoritative.")
        source = [message("user", "Historical configuration " * 1_500),
                  message("assistant", "Old search complete."), task, *cycles, current_answer]
        original = copy.deepcopy(source)

        result = compact_messages(source, estimate, target=1_800)

        self.assertTrue(result.audit["compacted"])
        self.assertLessEqual(result.audit["forwarded_tokens"], 1_800)
        self.assertGreaterEqual(result.audit["preserved_recent_tool_cycles"], 1)
        self.assertEqual(result.messages[-3:], [cycles[-2], cycles[-1], current_answer])
        self.assertEqual(source, original)

    def test_anthropic_tool_result_does_not_reanchor_current_turn(self):
        current = [message("user", "Fix the bug"),
                   message("assistant", [{"type": "tool_use", "id": "x", "name": "Read", "input": {}}]),
                   message("user", [{"type": "tool_result", "tool_use_id": "x", "content": "error here"}])]
        source = [message("user", "noise " * 2000), message("assistant", "old"), *current]
        result = compact_messages(source, estimate, target=500, protocol="anthropic")
        self.assertEqual(result.messages[-3:], current)

    def test_long_single_claude_tool_turn_compacts_older_cycles(self):
        task = message("user", "Fix the booking timezone tests and keep the original requirement.")
        cycles = []
        for index in range(24):
            cycles.extend([
                message("assistant", [{"type": "tool_use", "id": f"tool_{index}",
                                       "name": "PowerShell", "input": {"command": "python -m unittest"}}]),
                message("user", [{"type": "tool_result", "tool_use_id": f"tool_{index}",
                                  "content": f"test run {index}: " + "verbose output " * 70}]),
            ])
        cycles[-1]["content"][0]["content"] += "\nFAILED: test_dst_gap"
        source = [message("system", "Follow project rules"), task, *cycles]
        result = compact_messages(source, estimate, target=1_400, protocol="anthropic")
        self.assertLessEqual(result.audit["forwarded_tokens"], 1_400)
        self.assertEqual(result.messages[0], source[0])
        self.assertIn(task, result.messages)
        self.assertEqual(result.messages[-2:], cycles[-2:])
        self.assertIn("test_dst_gap", str(result.messages[-1]))
        self.assertTrue(result.audit["compacted"])

    def test_old_thinking_is_omitted_while_current_thinking_is_exact(self):
        source = [
            message("user", "Find the failure"),
            message("assistant", [
                {"type": "thinking", "thinking": "private prior reasoning", "signature": "sig-old"},
                {"type": "tool_use", "id": "old", "name": "Read", "input": {}},
            ]),
            message("user", [{"type": "tool_result", "tool_use_id": "old",
                              "content": "FAILED: test_policy " + "noise " * 1000}]),
            message("assistant", [
                {"type": "thinking", "thinking": "private current reasoning", "signature": "sig-new"},
                {"type": "tool_use", "id": "new", "name": "Read", "input": {}},
            ]),
            message("user", [{"type": "tool_result", "tool_use_id": "new",
                              "content": "Current file content"}]),
        ]
        result = compact_messages(source, estimate, target=600, protocol="anthropic")
        self.assertEqual(result.messages[-2:], source[-2:])
        self.assertNotIn("private prior reasoning", str(result.messages))
        self.assertIn("private current reasoning", str(result.messages))

    def test_long_openai_tool_loop_keeps_latest_call_and_result(self):
        task = message("user", "Finish the ledger reconciliation")
        cycles = []
        for index in range(18):
            cycles.extend([
                message("assistant", None, tool_calls=[{"id": f"call_{index}", "type": "function",
                    "function": {"name": "run", "arguments": "{}"}}]),
                message("tool", f"result {index}: " + "routine output " * 70,
                        tool_call_id=f"call_{index}"),
            ])
        source = [task, *cycles]
        result = compact_messages(source, estimate, target=1_200, protocol="openai")
        self.assertIn(task, result.messages)
        self.assertEqual(result.messages[-2:], cycles[-2:])
        self.assertLessEqual(result.audit["forwarded_tokens"], 1_200)

    def test_completed_early_tool_epoch_keeps_stable_excerpt_prefix(self):
        task = message("user", "Investigate invoice replay failure")
        cycles = []
        for index in range(15):
            cycles.extend([
                message("assistant", None, tool_calls=[{"id": f"call_{index}", "type": "function",
                    "function": {"name": "run", "arguments": "{}"}}]),
                message("tool", f"invoice replay diagnostic {index}: " + "log output " * 95,
                        tool_call_id=f"call_{index}"),
            ])
        first = compact_messages([task, *cycles[:-2]], estimate, target=4_000)
        second = compact_messages([task, *cycles], estimate, target=4_000)
        self.assertGreater(first.audit["stable_epoch_excerpts"], 0)
        self.assertEqual(first.audit["stable_epoch_excerpts"], second.audit["stable_epoch_excerpts"])
        def early_lines(result):
            return [line for line in result.messages[1]["content"].splitlines()
                    if line.startswith("[message ") and int(line.split()[1]) <= 12]
        self.assertEqual(early_lines(first), early_lines(second))
        self.assertLessEqual(second.audit["forwarded_tokens"], 4_000)

    def test_tool_cycles_append_without_rewriting_prefix_inside_barrier(self):
        task = message("user", "Find the newest failing test")
        cycles = []
        for index in range(20):
            cycles.extend([
                message("assistant", None, tool_calls=[{"id": f"x{index}", "type": "function",
                    "function": {"name": "Read", "arguments": "{}"}}]),
                message("tool", f"FAILED test_{index} " + "log output " * 80,
                        tool_call_id=f"x{index}"),
            ])
        results = [compact_messages([task, *cycles[:2 * count]], estimate, target=3_000)
                   for count in (18, 19, 20)]
        for earlier, later in zip(results, results[1:]):
            self.assertTrue(earlier.audit["compacted"])
            self.assertLessEqual(later.audit["forwarded_tokens"], 3_000)
            self.assertEqual(later.messages[:len(earlier.messages)], earlier.messages)
        self.assertEqual(results[-1].messages[-1], cycles[-1])

    def test_named_test_failures_survive_a_fixed_tool_epoch(self):
        task = message("user", "Implement the incremental build planner")
        cycles = []
        failures = tuple(f"ERROR: test_case_{index}" for index in range(10)) + (
            "FAIL: test_rejects_cycle", "FAILED tests/test_build.py::test_missing_input",
        )
        for index in range(20):
            log = "build planner routine output " * 20
            if index == 5:
                log = "\n".join(failures)
            cycles.extend([
                message("assistant", [{"type": "tool_use", "id": f"x{index}",
                                       "name": "PowerShell", "input": {"command": "test"}}]),
                message("user", [{"type": "tool_result", "tool_use_id": f"x{index}",
                                  "content": log}]),
            ])
        results = [compact_messages([task, *cycles[:2 * count]], estimate,
                                    target=3_000, protocol="anthropic")
                   for count in (18, 19, 20)]
        for result in results:
            self.assertTrue(all(failure in str(result.messages) for failure in failures))
            self.assertLessEqual(result.audit["forwarded_tokens"], 3_000)
        for earlier, later in zip(results, results[1:]):
            self.assertEqual(later.messages[:len(earlier.messages)], earlier.messages)

    def test_limits_and_unsupported_media_fail_closed(self):
        source = [message("user", "old " * 1000), message("assistant", "old"),
                  message("user", "new " * 1000)]
        with self.assertRaisesRegex(CompactionError, "raw_limit"):
            compact_messages(source, estimate, target=100, raw_limit=200)
        with self.assertRaisesRegex(CompactionError, "active"):
            compact_messages(source, estimate, target=100)
        media = [message("user", "old " * 1000), message("user", [{"type": "image", "data": "x"}])]
        with self.assertRaisesRegex(CompactionError, "content"):
            compact_messages(media, estimate, target=100)

    def test_precount_text_limit_rejects_before_calling_token_counter(self):
        called = False

        def counter(messages):
            nonlocal called
            called = True
            return 10

        with self.assertRaises(CompactionError) as caught:
            compact_messages(
                [message("user", "x" * 10_000)], counter, target=100,
                max_input_characters=1_000,
            )
        self.assertEqual(caught.exception.code, "input_size_limit")
        self.assertFalse(called)

    def test_precount_node_limit_rejects_repeated_short_messages_before_counting(self):
        called = False

        def counter(messages):
            nonlocal called
            called = True
            return 10

        with self.assertRaises(CompactionError) as caught:
            compact_messages(
                [message("user", "x") for _ in range(100)], counter,
                target=100, max_input_nodes=20,
            )
        self.assertEqual(caught.exception.code, "input_size_limit")
        self.assertFalse(called)

    def test_late_instruction_stays_anchored_and_tool_cycle_remains_whole(self):
        source = [message("system", "Initial instruction."),
                  message("user", "Historical MIDDLE_KEY evidence was recorded.")]
        for index in range(8):
            source.extend([
                message("assistant", None, tool_calls=[{"id": f"old_{index}", "type": "function",
                    "function": {"name": "read", "arguments": "{}"}}]),
                message("tool", f"old diagnostic {index}: " + "routine output " * 100,
                        tool_call_id=f"old_{index}"),
            ])
        source.extend([
            message("developer", "Late instruction: retain exact source order."),
            message("user", "What is the MIDDLE_KEY value?"),
            message("assistant", None, tool_calls=[{"id": "current", "type": "function",
                "function": {"name": "read", "arguments": "{}"}}]),
            message("tool", "Current file confirms the value.", tool_call_id="current"),
            message("assistant", "Ready to answer."),
        ])
        original = copy.deepcopy(source)
        result = compact_messages(source, estimate, target=900)

        self.assertEqual(source, original)
        self.assertTrue(result.audit["compacted"])
        self.assertEqual(result.audit["method"], "late_instruction_anchors")
        self.assertLessEqual(result.audit["forwarded_tokens"], 900)
        self.assertEqual(result.messages[0], source[0])
        self.assertIn("MIDDLE_KEY evidence", result.messages[1]["content"])
        anchor = next(index for index, item in enumerate(result.messages)
                      if item.get("role") == "developer")
        self.assertEqual(result.messages[anchor], source[2 + 2 * 8])
        self.assertEqual(result.messages[anchor + 1:], source[2 + 2 * 8 + 1:])
        calls = {call["id"] for item in result.messages for call in item.get("tool_calls", [])}
        outputs = {item["tool_call_id"] for item in result.messages if item.get("role") == "tool"}
        self.assertEqual(calls, outputs)

    def test_anthropic_late_instruction_stays_after_its_preceding_tool_exchange(self):
        source = [message("system", "Initial instruction."),
                  message("user", "Historical RETAINED_KEY evidence.")]
        for index in range(8):
            source.extend([
                message("assistant", [{"type": "tool_use", "id": f"old_{index}",
                    "name": "Read", "input": {"path": f"file-{index}"}}]),
                message("user", [{"type": "tool_result", "tool_use_id": f"old_{index}",
                    "content": f"historical result {index}: " + "routine output " * 100}]),
            ])
        source.extend([
            message("developer", "Late instruction: preserve this position."),
            message("user", "What is the RETAINED_KEY value?"),
            message("assistant", [{"type": "tool_use", "id": "current",
                "name": "Read", "input": {"path": "current-file"}}]),
            message("user", [{"type": "tool_result", "tool_use_id": "current",
                "content": "Current file confirms the value."}]),
        ])
        result = compact_messages(source, estimate, target=900, protocol="anthropic")

        self.assertLessEqual(result.audit["forwarded_tokens"], 900)
        self.assertEqual(result.messages[0], source[0])
        self.assertIn("RETAINED_KEY evidence", result.messages[1]["content"])
        anchor = next(index for index, item in enumerate(result.messages)
                      if item.get("role") == "developer")
        self.assertEqual(result.messages[anchor], source[2 + 2 * 8])
        self.assertEqual(result.messages[anchor + 1:], source[2 + 2 * 8 + 1:])
        calls = {block["id"] for item in result.messages if isinstance(item.get("content"), list)
                 for block in item["content"] if block.get("type") == "tool_use"}
        outputs = {block["tool_use_id"] for item in result.messages if isinstance(item.get("content"), list)
                   for block in item["content"] if block.get("type") == "tool_result"}
        self.assertEqual(calls, outputs)

    def test_late_instruction_after_active_user_keeps_request_and_open_tool_cycle_exact(self):
        current = [message("user", "What is the RETAINED_KEY value?"),
                   message("assistant", None, tool_calls=[{"id": "active", "type": "function",
                       "function": {"name": "read", "arguments": "{}"}}]),
                   message("developer", "Late instruction: keep this exact position."),
                   message("tool", "RETAINED_KEY=green", tool_call_id="active"),
                   message("assistant", "The source says green.")]
        source = [message("system", "Initial instruction."), message("user", "Old evidence " * 1_000),
                  message("assistant", "Old work."), *current]
        result = compact_messages(source, estimate, target=700)

        self.assertLessEqual(result.audit["forwarded_tokens"], 700)
        self.assertEqual(result.messages[-len(current):], current)
        self.assertEqual(result.messages[0], source[0])
        self.assertIn("Old evidence", result.messages[1]["content"])

    def test_oversized_late_instruction_anchor_fails_closed(self):
        source = [message("user", "Old evidence " * 1_000),
                  message("developer", "Pinned instruction " * 400),
                  message("user", "Continue the task.")]
        with self.assertRaisesRegex(CompactionError, "late instructions") as caught:
            compact_messages(source, estimate, target=300)
        self.assertEqual(caught.exception.code, "active_too_large")

    def test_multiple_late_instruction_anchors_keep_order_and_compact_each_span(self):
        source = [
            message("system", "Initial instruction."),
            message("user", "ALPHA_KEY=amber; " + "older evidence noise " * 180),
            message("developer", "First late instruction."),
            message("assistant", "Acknowledged."),
            message("user", "BETA_KEY=violet; " + "later evidence noise " * 180),
            message("system", "Second late instruction."),
            message("user", "Recover ALPHA_KEY and BETA_KEY."),
        ]
        result = compact_messages(source, estimate, target=900)

        self.assertLessEqual(result.audit["forwarded_tokens"], 900)
        self.assertTrue(result.audit["compacted"])
        self.assertEqual(result.messages[0], source[0])
        first = next(index for index, item in enumerate(result.messages)
                     if item.get("role") == "developer")
        second = next(index for index, item in enumerate(result.messages)
                      if item.get("role") == "system" and index > 0)
        self.assertEqual(result.messages[first], source[2])
        self.assertEqual(result.messages[second], source[5])
        self.assertLess(first, second)
        self.assertEqual(result.messages[-1], source[-1])
        summaries = [item["content"] for item in result.messages
                     if item.get("role") == "user" and "Earlier conversation" in item.get("content", "")]
        self.assertTrue(any("ALPHA_KEY=amber" in text for text in summaries))
        self.assertTrue(any("BETA_KEY=violet" in text for text in summaries))

    def test_too_many_late_instruction_anchors_fail_closed(self):
        source = [message("user", "Old evidence " * 400)]
        source.extend(message("developer", f"Pinned instruction {index}") for index in range(65))
        source.append(message("user", "Continue the task."))
        with self.assertRaisesRegex(CompactionError, "too many late instruction") as caught:
            compact_messages(source, estimate, target=500)
        self.assertEqual(caught.exception.code, "late_instruction_limit")

    def test_deterministic_selection_and_no_mutation(self):
        source = [message("user", "\n".join(f"item {i}: {i*i}" for i in range(600))),
                  message("assistant", "received"), message("user", "What is item 317?")]
        before = copy.deepcopy(source)
        a = compact_messages(source, estimate, target=400)
        b = compact_messages(source, estimate, target=400)
        self.assertEqual(a, b)
        self.assertEqual(source, before)
        self.assertIn("item 317", str(a.messages))

    def test_csv_rows_stay_atomic_and_keep_the_column_header(self):
        stream = StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["review_id", "text"])
        for index in range(40):
            writer.writerow([f"REV-{index}", "routine update " * 40])
        target_text = 'Customer reported "crate, not pallet".\nReference XQ-882 is missing.'
        writer.writerow(["REV-204", target_text])
        content = stream.getvalue()
        target_lines = content.splitlines(keepends=True)
        target_record = target_lines[-2] + target_lines[-1]
        messages = [
            message("user", content),
            message("assistant", "CSV received."),
            message("user", "What does review REV-204 say about reference XQ-882?"),
        ]

        result = compact_messages(messages, estimate, target=900)

        self.assertLessEqual(result.audit["forwarded_tokens"], 900)
        excerpts = [
            json.loads(line.split("] ", 1)[1])
            for item in result.messages
            if item.get("role") == "user" and isinstance(item.get("content"), str)
            for line in item["content"].splitlines()
            if line.startswith("[message ")
        ]
        joined = "\n".join(excerpts)
        self.assertIn("review_id,text\n", joined)
        self.assertEqual(joined.count("review_id,text\n"), 1)
        self.assertIn(target_record, joined)
        self.assertTrue(any("XQ-882" in excerpt for excerpt in excerpts))

    def test_quoted_csv_anchor_preserves_all_matching_distinct_rows_under_budget(self):
        stream = StringIO(newline="")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(["review_id", "text"])
        for index in range(600):
            writer.writerow([f"NOISE-{index}", f"routine service note {index} with no cuisine keyword"])
        unique_comments = [
            f"This mexican review has distinct evidence marker {index:02d}."
            for index in range(41)
        ]
        for index, comment in enumerate(unique_comments + unique_comments[:4]):
            writer.writerow([f"MATCH-{index}", comment])
        messages = [
            message("user", "<text>\n" + stream.getvalue() + "</text>"),
            message("assistant", "Dataset received."),
            message("user", 'How many different comments mention "mexican"? Count identical text once.'),
        ]

        result = compact_messages(messages, estimate, target=5_000)

        self.assertTrue(result.audit["compacted"])
        self.assertLessEqual(result.audit["forwarded_tokens"], 5_000)
        summary = "\n".join(
            json.loads(line.split("] ", 1)[1])
            for item in result.messages
            if item.get("role") == "user" and isinstance(item.get("content"), str)
            for line in item["content"].splitlines()
            if line.startswith("[message ")
        )
        self.assertTrue(all(comment in summary for comment in unique_comments))

    def test_non_csv_text_falls_back_to_bounded_pieces(self):
        from sift.core import _pieces

        text = "not a table\n" + "ordinary prose, with commas " * 40
        pieces = list(_pieces(text))

        self.assertTrue(pieces)
        self.assertFalse(any(piece.structured for piece in pieces))
        self.assertTrue(all(len(piece.text) <= 360 for piece in pieces))

    def test_inconsistent_csv_rows_fall_back_without_partial_table_mode(self):
        from sift.core import _pieces

        text = "id,text\n1,valid row\n2,too,many,columns\n"
        pieces = list(_pieces(text))

        self.assertTrue(pieces)
        self.assertFalse(any(piece.structured for piece in pieces))

    def test_csv_splitline_separators_obey_the_physical_line_bound(self):
        from sift.core import _pieces

        text = "id,text\n" + ("1,short\v" * 100_001)
        pieces = list(_pieces(text))

        self.assertTrue(pieces)
        self.assertFalse(any(piece.structured for piece in pieces))

    def test_topic_shift_keeps_query_independent_prefix_and_targeted_evidence(self):
        history = topic_history()
        questions = (
            "What payment invoice fact and billing window were recorded?",
            "What incident rollback fact and alert window were recorded?",
        )
        results = [compact_messages(
            history + [message("user", question)], estimate,
            target=2_000, raw_limit=50_000,
        ) for question in questions]
        payment, incident = results

        self.assertEqual(payment.audit["method"], "query_aware_extract")
        self.assertEqual(incident.audit["method"], "query_aware_extract")
        self.assertEqual(payment.audit["stable_prefix_excerpts"], 1)
        self.assertEqual(incident.audit["stable_prefix_excerpts"], 1)
        self.assertEqual(payment.messages[1], incident.messages[1])
        self.assertNotEqual(payment.messages[2], incident.messages[2])
        self.assertIn("PAYMENT_FACT_", payment.messages[2]["content"])
        self.assertIn("INCIDENT_FACT_", incident.messages[2]["content"])
        self.assertEqual(payment.messages[-1]["content"], questions[0])
        self.assertEqual(incident.messages[-1]["content"], questions[1])
        self.assertLessEqual(payment.audit["forwarded_tokens"], 2_000)
        self.assertLessEqual(incident.audit["forwarded_tokens"], 2_000)

    def test_tool_history_keeps_stable_anchor_before_query_ranked_history(self):
        history = topic_history()
        questions = (
            "What payment invoice fact and billing window were recorded?",
            "What incident rollback fact and alert window were recorded?",
        )
        results = []
        for question in questions:
            messages = history + [message(
                "user", question + " " + "Current task detail. " * 20)]
            for index in range(48):
                tool_id = f"read_{index}"
                messages.extend([
                    message("assistant", None, tool_calls=[{
                        "id": tool_id,
                        "type": "function",
                        "function": {"name": "Read", "arguments": "{}"},
                    }]),
                    message("tool", f"Routine output {index}. " * 35,
                            tool_call_id=tool_id),
                ])
            results.append(compact_messages(
                messages, estimate, target=6_000, raw_limit=100_000))

        payment, incident = results
        summaries = [
            [item["content"] for item in result.messages
             if item.get("role") == "user"
             and isinstance(item.get("content"), str)
             and item["content"].startswith("Earlier conversation")]
            for result in results
        ]
        self.assertEqual(payment.audit["method"], "epoch_extract")
        self.assertEqual(incident.audit["method"], "epoch_extract")
        self.assertEqual(payment.audit["stable_prefix_excerpts"], 1)
        self.assertEqual(incident.audit["stable_prefix_excerpts"], 1)
        self.assertEqual(summaries[0][0], summaries[1][0])
        self.assertNotEqual(summaries[0][1], summaries[1][1])
        self.assertIn("PAYMENT_FACT_", summaries[0][1])
        self.assertIn("INCIDENT_FACT_", summaries[1][1])
        self.assertEqual(len(summaries[0]), 3)
        self.assertEqual(len(summaries[1]), 3)
        self.assertLessEqual(payment.audit["forwarded_tokens"], 6_000)
        self.assertLessEqual(incident.audit["forwarded_tokens"], 6_000)


if __name__ == "__main__":
    unittest.main()
