"""Behavioral checks from authored cases fixed before the structured-record fix."""

import copy
import json
from pathlib import Path
import unittest

from sift import compact_messages


def count(messages):
    return (len(json.dumps(messages)) + 3) // 4


def quoted_excerpts(messages):
    return [json.loads(line.split("] ", 1)[1])
            for message in messages if message["content"].startswith("Earlier conversation,")
            for line in message["content"].splitlines()[1:]]


class StructuredEvidenceTests(unittest.TestCase):
    def test_predeclared_cross_record_facts_fit_and_remain_exact(self):
        path = Path(__file__).resolve().parents[1] / "benchmarks" / "structured_evidence_cases.json"
        corpus = json.loads(path.read_text(encoding="utf-8"))
        for case in corpus["cases"]:
            with self.subTest(case=case["name"]):
                source = [
                    {"role": "user", "content": case["historical_document"]},
                    {"role": "assistant", "content": corpus["acknowledgement"]},
                    {"role": "user", "content": case["question"]},
                ]
                original = copy.deepcopy(source)
                result = compact_messages(source, count, target=900)
                self.assertTrue(result.audit["compacted"])
                self.assertLessEqual(count(result.messages), 900)
                self.assertEqual(result.messages[-1], source[-1])
                self.assertEqual(source, original)
                quotes = quoted_excerpts(result.messages)
                for span in case["must_retain"]:
                    self.assertTrue(any(span["text"] in quote for quote in quotes), span["record_id"])

    def test_long_record_whitespace_and_escapes_are_quoted_verbatim(self):
        record = "  " + json.dumps({"record_id": "RECEIPT-R81", "observations": "crate \\\"sealed\\\" " * 30,
                                    "disposition": "hold"}, ensure_ascii=False) + "  "
        document = "\n".join([f"routine checkpoint {index}" for index in range(100)] +
                              [record] + [f"routine checkpoint {index}" for index in range(100, 200)])
        source = [{"role": "user", "content": document}, {"role": "assistant", "content": "Received."},
                  {"role": "user", "content": "Give the observations and disposition for RECEIPT-R81."}]
        result = compact_messages(source, count, target=800)
        self.assertTrue(any(record in quote for quote in quoted_excerpts(result.messages)))
        self.assertLessEqual(count(result.messages), 800)

    def test_failed_test_keeps_adjacent_json_diagnostic(self):
        diagnostic = json.dumps({"actual": "HALF_UP", "expected": "HALF_EVEN", "difference": "0.01"})
        document = "\n".join([f"routine step {index}" for index in range(400)] +
                              ["FAILED test_invoice_rounding", diagnostic] +
                              [f"routine step {index}" for index in range(400, 800)])
        result = compact_messages([
            {"role": "user", "content": document}, {"role": "assistant", "content": "Received."},
            {"role": "user", "content": "Why did test_invoice_rounding fail?"},
        ], count, target=500)
        self.assertTrue(any("FAILED test_invoice_rounding" in quote and diagnostic in quote
                            for quote in quoted_excerpts(result.messages)))
        self.assertLessEqual(count(result.messages), 500)

    def test_malformed_deep_and_oversized_records_use_bounded_fallback(self):
        for record in ('{"record_id":"BROKEN-R81",}', "[" * 1_000 + "0" + "]" * 1_000,
                       json.dumps({"record_id": "LARGE-R81", "detail": "filler " * 800})):
            with self.subTest(length=len(record)):
                document = "routine\n" * 500 + record + "\nERROR E81: missing receipt\n" + "routine\n" * 500
                source = [{"role": "user", "content": document},
                          {"role": "assistant", "content": "Received."},
                          {"role": "user", "content": "What caused ERROR E81?"}]
                original = copy.deepcopy(source)
                result = compact_messages(source, count, target=700)
                self.assertIn("missing receipt", str(result.messages))
                self.assertLessEqual(count(result.messages), 700)
                self.assertEqual(source, original)

    def test_long_csv_row_keeps_its_original_physical_line(self):
        row = ('SAMPLE-ORCHID-73,VALVE-G62,2026-10-15T11:20Z,27.8,manual_review,'
               + '"Operator wrote ""read after equilibration""; ' + 'valve checked; ' * 31 + 'seal held"')
        document = '\n'.join([f'normal row {index},accepted' for index in range(100)]
                             + [row] + [f'normal row {index},accepted' for index in range(100, 200)])
        source = [{'role': 'user', 'content': document},
                  {'role': 'assistant', 'content': 'Worksheet received.'},
                  {'role': 'user', 'content': 'Quote the full original row for SAMPLE-ORCHID-73.'}]
        original = copy.deepcopy(source)
        result = compact_messages(source, count, target=900)
        self.assertTrue(any(row in quote for quote in quoted_excerpts(result.messages)))
        self.assertLessEqual(count(result.messages), 900)
        self.assertEqual(source, original)

    def test_multiline_source_keeps_indentation_and_line_breaks(self):
        function = ('def charge(invoice):\n'
                    '    amount = invoice["amount"]\n'
                    '    if invoice["currency"] == "USD":\n'
                    '        return amount * 100')
        document = '\n'.join(['# context ' + str(index) for index in range(80)]
                             + [function] + ['# context ' + str(index) for index in range(80, 160)])
        source = [{'role': 'user', 'content': document},
                  {'role': 'assistant', 'content': 'Source received.'},
                  {'role': 'user', 'content': 'Quote the charge function exactly, with indentation.'}]
        original = copy.deepcopy(source)
        result = compact_messages(source, count, target=500)
        self.assertTrue(any(function in quote for quote in quoted_excerpts(result.messages)))
        self.assertLessEqual(count(result.messages), 500)
        self.assertEqual(source, original)

    def test_large_blank_gap_does_not_make_a_selected_excerpt_huge(self):
        source = [{'role': 'user', 'content': 'needle\n' + '\n' * 100_000 + 'next'},
                  {'role': 'assistant', 'content': 'Received.'},
                  {'role': 'user', 'content': 'Where is the needle?'}]
        result = compact_messages(source, count, target=700)
        self.assertTrue(any('needle' in quote for quote in quoted_excerpts(result.messages)))
        self.assertLessEqual(count(result.messages), 700)


if __name__ == "__main__":
    unittest.main()
