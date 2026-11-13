"""choch_rule.py must stay a verbatim copy of PR #16's swing_points / choch_events."""
import inspect
import unittest
from pathlib import Path

import choch_rule

PR16 = Path(__file__).resolve().parents[2] / ".claude" / "worktrees" / "pr-16" / "functions" / "ml" / "choch_crypto_study.py"


class TestChochRuleCopy(unittest.TestCase):
    @unittest.skipUnless(PR16.exists(), "PR #16 worktree not checked out")
    def test_matches_pr16(self):
        src = PR16.read_text()
        for name in ("swing_points", "choch_events"):
            self.assertIn(inspect.getsource(getattr(choch_rule, name)), src, name)


if __name__ == "__main__":
    unittest.main()
