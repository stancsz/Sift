"""Synthetic, deterministic tasks for long-session CLI acceptance."""
import random

TASKS = ("engineering", "migration", "expenses")

_REQ = {
    "engineering": [
        "Implement clamp(value, lower=0, upper=100): return value limited to inclusive bounds.",
        "Accept int/float values, reject bool and non-numeric values with TypeError; reject non-finite numbers with ValueError.",
        "Raise ValueError when lower exceeds upper.",
        "Implement clamp_all(iterable, lower=0, upper=100), returning a list and accepting generators.",
        "Implement clamp_report(iterable, lower=0, upper=100): count/min/max/sum of clamped values; empty gives count=0 and min/max/sum=None/None/0.",
        "Validate bounds as finite non-bool numbers and reject invalid bounds with TypeError or ValueError.",
        "Materialize input once; clamp_all and clamp_report must handle one-shot iterators consistently.",
        "Keep all earlier behavior, including empty inputs and inclusive bounds.",
    ],
    "migration": [
        "Implement normalize_settings(mapping): copy input, strip name, map timeout_ms to timeout_seconds, and supply defaults name='default', timeout_seconds=30.",
        "Convert nonnegative integer timeout_ms to timeout_seconds by dividing by 1000; reject bool and non-integer values.",
        "Reject negative timeout values and non-string names; empty stripped name uses the default.",
        "Reject simultaneous timeout_ms and timeout_seconds keys, even if equal.",
        "Reject unknown keys; accepted keys are name, timeout_ms, timeout_seconds, retries.",
        "Validate retries as a nonnegative integer excluding bool; default retries=0.",
        "Do not mutate inputs; normalized output must be idempotent.",
        "Implement migrate_many(iterable) preserving order and returning independently normalized dictionaries.",
    ],
    "expenses": [
        "Implement expense_totals(csv_text): parse CSV header category,amount and return category totals as Decimal quantized to 0.01 using HALF_EVEN.",
        "Strip category whitespace and aggregate categories case-insensitively, preserving first spelling in output.",
        "Ignore blank rows; parse amounts as Decimal and reject malformed rows/amounts with ValueError.",
        "Allow negative amounts as refunds; reject non-finite amounts.",
        "Support optional currency column; reject mixed nonblank currencies.",
        "Implement expense_report(csv_text) with totals, grand_total (fixed to two decimals), and count of parsed nonblank rows.",
        "Reject missing required headers and duplicate headers; input is never modified.",
        "Keep deterministic output ordering by first category appearance and exact Decimal arithmetic.",
    ],
}

_INITIAL = {
    "engineering": "def clamp(value, lower=0, upper=100):\n    return value\n",
    "migration": "def normalize_settings(settings):\n    return settings\n",
    "expenses": "def expense_totals(csv_text):\n    return {}\n",
}

def initial_source(task: str) -> str:
    if task not in TASKS:
        raise ValueError("unknown task")
    return _INITIAL[task]

def _engineering_tests(stage: int, seed: int) -> str:
    rng = random.Random(seed)
    probes = [rng.randint(-200, 200) for _ in range(16)]
    body = """    def test_behavior(self):
        import task
        self.assertEqual(task.clamp(-3), 0)
        self.assertEqual(task.clamp(120), 100)
        self.assertEqual(task.clamp(7, 5, 9), 7)
"""
    if stage >= 1: body += "        for x in (True, '2', None):\n            with self.assertRaises(TypeError): task.clamp(x)\n"
    if stage >= 2: body += "        with self.assertRaises(ValueError): task.clamp(1, 5, 2)\n"
    if stage >= 3: body += "        with self.assertRaises(ValueError): task.clamp(float('inf'))\n"
    if stage >= 4: body += "        self.assertEqual(task.clamp_all([-1, 4, 120]), [0, 4, 100])\n"
    if stage >= 5: body += "        self.assertEqual(task.clamp_report([]), {'count': 0, 'min': None, 'max': None, 'sum': 0})\n        self.assertEqual(task.clamp_report([2, 8])['sum'], 10)\n"
    if stage >= 6: body += "        with self.assertRaises((TypeError, ValueError)): task.clamp(1, float('nan'), 4)\n"
    if stage >= 7: body += "        it = iter([1, 101]); self.assertEqual(task.clamp_all(it), [1, 100])\n"
    if stage >= 8: body += f"        self.assertEqual(task.clamp_all({probes!r}), [max(0, min(100, x)) for x in {probes!r}])\n"
    return body

def _migration_tests(stage: int, seed: int) -> str:
    body = """    def test_behavior(self):
        import task
        self.assertEqual(task.normalize_settings({}), {'name': 'default', 'timeout_seconds': 30, 'retries': 0})
        self.assertEqual(task.normalize_settings({'name': ' X ', 'timeout_seconds': 4}), {'name': 'X', 'timeout_seconds': 4, 'retries': 0})
"""
    cases = [
        "self.assertEqual(task.normalize_settings({'timeout_ms': 2500})['timeout_seconds'], 2.5)",
        "with self.assertRaises((TypeError, ValueError)): task.normalize_settings({'timeout_ms': True})",
        "with self.assertRaises(ValueError): task.normalize_settings({'timeout_ms': 1, 'timeout_seconds': 1})",
        "with self.assertRaises(ValueError): task.normalize_settings({'extra': 1})",
        "with self.assertRaises((TypeError, ValueError)): task.normalize_settings({'retries': -1})",
        "d={'name':' A '}; out=task.normalize_settings(d); self.assertEqual(d, {'name':' A '}); self.assertEqual(task.normalize_settings(out), out)",
        "self.assertEqual(task.migrate_many([{}, {'name':' B '}]), [{'name':'default','timeout_seconds':30,'retries':0},{'name':'B','timeout_seconds':30,'retries':0}])",
    ]
    for i, case in enumerate(cases, 1):
        if stage >= i: body += "        " + case + "\n"
    if stage >= 8:
        milliseconds = 1000 + seed % 7000
        body += f"        self.assertEqual(task.normalize_settings({{'timeout_ms': {milliseconds}}})['timeout_seconds'], {milliseconds / 1000!r})\n"
    return body

def _expense_tests(stage: int, seed: int) -> str:
    body = """    def test_behavior(self):
        import task
        from decimal import Decimal
        data = 'category,amount\\nFood,1.005\\nfood,2.00\\nTransit,3.00\\n'
        self.assertEqual(task.expense_totals(data), {'Food': Decimal('3.00'), 'Transit': Decimal('3.00')})
"""
    cases = [
        "self.assertEqual(task.expense_totals('category,amount\\n A ,1\\na,2\\n'), {'A': Decimal('3.00')})",
        "self.assertEqual(task.expense_totals('category,amount\\nrefund,-2\\n')['refund'], Decimal('-2.00'))",
        "with self.assertRaises(ValueError): task.expense_totals('category,amount\\nx,nope\\n')",
        "with self.assertRaises(ValueError): task.expense_totals('category,amount,currency\\nx,1,USD\\ny,2,CAD\\n')",
        "r=task.expense_report('category,amount\\nx,1.00\\nx,2.00\\n'); self.assertEqual(r['count'], 2); self.assertEqual(r['grand_total'], Decimal('3.00'))",
        "with self.assertRaises(ValueError): task.expense_totals('amount\\n1\\n')",
        "self.assertEqual(list(task.expense_totals('category,amount\\nb,1\\na,2\\n')), ['b','a'])",
    ]
    for i, case in enumerate(cases, 1):
        if stage >= i: body += "        " + case + "\n"
    if stage >= 8:
        amount = seed % 89 + 10
        body += f"        self.assertEqual(task.expense_totals('category,amount\\nedge,{amount}.00\\n')['edge'], Decimal('{amount}.00'))\n"
        body += "        self.assertEqual(task.expense_totals('category,amount\\nx,1.005\\nx,0.005\\n')['x'], Decimal('1.01'))\n"
    return body

def stage(task: str, number: int, seed: int) -> dict:
    if task not in TASKS or not isinstance(number, int) or number < 0 or not isinstance(seed, int):
        raise ValueError("invalid task, stage, or seed")
    n = min(number, 8)
    tests = {"engineering": _engineering_tests, "migration": _migration_tests, "expenses": _expense_tests}[task](n, seed)
    tests += "    def test_evidence(self):\n        import json\n        from pathlib import Path\n        value = json.loads(Path('evidence.json').read_text())['acceptance_delay_seconds']\n        self.assertIs(type(value), int)\n"
    return {"requirement": "Stage " + str(number) + ": " + " ".join(_REQ[task][:min(n + 1, 8)]) + " Investigate and update task.py if tests fail, then execute the tests.",
            "tests": "import unittest\n\nclass Acceptance(unittest.TestCase):\n" + tests + "\nif __name__ == '__main__':\n    unittest.main()\n"}
