"""Enforce the eval floor under ``make test``.

Bump ``EXPECTED_GREEN`` as each slice lands: Part 2 → 3, Part 3 → 5, Part 4 → 9,
Part 5 → 10, Part 6 → 12. The board only goes up — this test makes a regression
(a previously-green case going red) fail the build.
"""

from __future__ import annotations

from tests.eval.run_eval import run

EXPECTED_GREEN = 12  # Part 6: fraud (TC009) + graceful degradation (TC011). Full suite.


def test_eval_floor():
    green, total = run()
    assert green >= EXPECTED_GREEN, f"regression: {green}/{total} green, floor is {EXPECTED_GREEN}"
