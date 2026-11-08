import copy
from datetime import date
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("advisories", Path(__file__).parents[1] / "check_rust_advisories.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class AdvisoryGateTests(unittest.TestCase):
    def test_new_changed_expired_and_exploitable_findings_fail(self):
        report = {"vulnerabilities": {"found": False, "list": []}, "warnings": {"unsound": [{
            "package": {"name": "example", "version": "1.0.0"}, "advisory": {"id": "TEST-1"}}]}}
        review = {"package": "example", "version": "1.0.0", "advisory": "TEST-1", "kind": "unsound",
                  "reason": "Reviewed call sites", "expires": "2026-12-07"}
        gate.check(report, [review], date(2026, 11, 7))
        for change in ({"version": "1.0.1"}, {"advisory": "TEST-2"}, {"reason": ""}, {"expires": "2026-11-07"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                gate.check(report, [{**review, **change}], date(2026, 11, 7))
        with self.assertRaises(ValueError):
            gate.check(report, [], date(2026, 11, 7))
        vulnerable = copy.deepcopy(report)
        vulnerable["vulnerabilities"] = {"found": True, "list": [report["warnings"]["unsound"][0]]}
        with self.assertRaises(ValueError):
            gate.check(vulnerable, [review], date(2026, 11, 7))
        with self.assertRaises(KeyError):
            gate.check({}, [review])
