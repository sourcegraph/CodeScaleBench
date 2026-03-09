import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.account_health import discover_account_homes


class DiscoverAccountHomesTests(unittest.TestCase):
    def test_discovers_existing_account_dirs_without_credentials(self):
        with tempfile.TemporaryDirectory() as td:
            real_home = Path(td)
            homes_dir = real_home / ".claude-homes"
            for account_name in ("account5", "account2", "account10", "account4"):
                (homes_dir / account_name / ".claude").mkdir(parents=True)
            (homes_dir / "notes").mkdir()

            homes = discover_account_homes(real_home)

            self.assertEqual(
                [home.name for home in homes],
                ["account2", "account4", "account5", "account10"],
            )

    def test_falls_back_to_real_home_when_no_managed_accounts_exist(self):
        with tempfile.TemporaryDirectory() as td:
            real_home = Path(td)

            homes = discover_account_homes(real_home)

            self.assertEqual(homes, [real_home])


if __name__ == "__main__":
    unittest.main()
