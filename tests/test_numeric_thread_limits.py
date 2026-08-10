from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


class NumericThreadLimitTest(unittest.TestCase):
    @staticmethod
    def _probe(extra_env: dict[str, str] | None = None) -> dict[str, str]:
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        for name in (
            "POWER_SIMU_NUMERIC_THREADS",
            "OMP_NUM_THREADS",
            "MKL_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
        ):
            env.pop(name, None)
        env.update(extra_env or {})
        command = (
            "import json, os, simu; "
            "print(json.dumps({name: os.environ.get(name, '') for name in "
            "['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS','NUMEXPR_NUM_THREADS']}))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return json.loads(completed.stdout.strip())

    def test_package_defaults_numeric_libraries_to_one_thread(self):
        values = self._probe()

        self.assertEqual(set(values.values()), {"1"})

    def test_explicit_numeric_thread_limit_is_applied_without_overwriting_specific_override(self):
        values = self._probe(
            {
                "POWER_SIMU_NUMERIC_THREADS": "3",
                "MKL_NUM_THREADS": "2",
            }
        )

        self.assertEqual(values["OMP_NUM_THREADS"], "3")
        self.assertEqual(values["OPENBLAS_NUM_THREADS"], "3")
        self.assertEqual(values["NUMEXPR_NUM_THREADS"], "3")
        self.assertEqual(values["MKL_NUM_THREADS"], "2")


if __name__ == "__main__":
    unittest.main()
