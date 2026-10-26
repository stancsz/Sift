import ast
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmarks import acceptance_tasks as tasks


REFERENCES = {
    "engineering": '''import math
def valid(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)): raise TypeError('number required')
    if not math.isfinite(x): raise ValueError('finite number required')
def clamp(value, lower=0, upper=100):
    for x in (value, lower, upper): valid(x)
    if lower > upper: raise ValueError('inverted bounds')
    return min(upper, max(lower, value))
def clamp_all(values, lower=0, upper=100):
    return [clamp(x, lower, upper) for x in values]
def clamp_report(values, lower=0, upper=100):
    data=clamp_all(values, lower, upper)
    return dict(count=len(data), min=min(data) if data else None, max=max(data) if data else None, sum=sum(data))
''',
    "migration": '''import math
def normalize_settings(settings):
    data=dict(settings)
    if set(data)-{'name','timeout_ms','timeout_seconds','retries'}: raise ValueError('unknown key')
    if 'timeout_ms' in data and 'timeout_seconds' in data: raise ValueError('conflicting fields')
    name=data.get('name','default')
    if not isinstance(name,str): raise TypeError('name')
    retries=data.get('retries',0)
    if type(retries) is not int or retries<0: raise ValueError('retries')
    if 'timeout_ms' in data:
        value=data['timeout_ms']
        if type(value) is not int or value<0: raise ValueError('timeout_ms')
        timeout=value/1000
    else:
        timeout=data.get('timeout_seconds',30)
        if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<0: raise ValueError('timeout_seconds')
    return dict(name=name.strip() or 'default', timeout_seconds=timeout, retries=retries)
def migrate_many(values): return [normalize_settings(value) for value in values]
''',
    "expenses": '''import csv,io
from decimal import Decimal,InvalidOperation,ROUND_HALF_EVEN
def parse(text):
    reader=csv.DictReader(io.StringIO(text))
    fields=reader.fieldnames or []
    if not {'category','amount'}<=set(fields) or len(fields)!=len(set(fields)): raise ValueError('headers')
    rows=[]; currencies=set()
    for row in reader:
        if not any(str(v or '').strip() for v in row.values()): continue
        if None in row or row.get('amount') is None or not str(row.get('category') or '').strip(): raise ValueError('row')
        try: amount=Decimal(row['amount'].strip())
        except (InvalidOperation,AttributeError): raise ValueError('amount')
        if not amount.is_finite(): raise ValueError('finite amount')
        currency=str(row.get('currency') or '').strip()
        if currency: currencies.add(currency)
        if len(currencies)>1: raise ValueError('mixed currencies')
        rows.append((row['category'].strip(),amount))
    return rows
def expense_totals(text):
    names={};totals={}
    for name,amount in parse(text):
        canonical=names.setdefault(name.casefold(),name)
        totals[canonical]=totals.get(canonical,Decimal(0))+amount
    return {name:amount.quantize(Decimal('.01'),rounding=ROUND_HALF_EVEN) for name,amount in totals.items()}
def expense_report(text):
    totals=expense_totals(text)
    return dict(totals=totals, grand_total=sum(totals.values(),Decimal('0.00')).quantize(Decimal('.01'),rounding=ROUND_HALF_EVEN), count=len(parse(text)))
''',
}


class GeneratorTests(unittest.TestCase):
    def test_shapes_and_baseline_failures(self):
        self.assertEqual(tasks.TASKS, ("engineering", "migration", "expenses"))
        for name in tasks.TASKS:
            source = tasks.initial_source(name)
            compile(source, "task.py", "exec")
            for level in range(9):
                result = tasks.stage(name, level, 123)
                compile(result["tests"], "test_task.py", "exec")
                tree = ast.parse(result["tests"])
                cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
                self.assertEqual([n.name for n in cls.body if isinstance(n, ast.FunctionDef)], ["test_behavior", "test_evidence"])
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "task.py").write_text(source)
                (root / "test_task.py").write_text(tasks.stage(name, 0, 123)["tests"])
                (root / "evidence.json").write_text(json.dumps({"acceptance_delay_seconds": 0}))
                run = subprocess.run([sys.executable, "-m", "unittest", "test_task"], cwd=root, capture_output=True)
                self.assertNotEqual(run.returncode, 0)

    def test_reference_contracts(self):
        # Execute every emitted cumulative specification against independently
        # authored complete implementations, using separate public/hidden seeds.
        for name, reference in REFERENCES.items():
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "task.py").write_text(reference, encoding="utf-8")
                (root / "evidence.json").write_text(json.dumps({"acceptance_delay_seconds": 999}))
                for number in range(10):
                    for seed in (831, 100834):
                        definition = tasks.stage(name, number, seed)
                        with self.subTest(task=name, stage=number, seed=seed):
                            self.assertIn(tasks._REQ[name][0], definition["requirement"])
                            run = subprocess.run([sys.executable, "-c", definition["tests"]], cwd=root,
                                                 capture_output=True, text=True, timeout=10)
                            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


if __name__ == "__main__":
    unittest.main()
