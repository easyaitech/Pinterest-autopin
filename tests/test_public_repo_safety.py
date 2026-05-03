from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class PublicRepoSafetyTest(unittest.TestCase):
    def tracked_files(self) -> list[Path]:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        return [REPO_ROOT / line for line in result.stdout.splitlines() if line.strip()]

    def test_tracked_files_do_not_contain_known_local_account_values(self) -> None:
        forbidden = [
            "ba" + "scn_",
            "OR" + "IEN",
            "Wabi " + "Sabi" + " Tea Ceremony",
        ]

        matches: list[str] = []
        for path in self.tracked_files():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for value in forbidden:
                if value in text:
                    matches.append(str(path.relative_to(REPO_ROOT)))

        self.assertEqual([], matches)

    def test_public_examples_use_non_real_placeholders(self) -> None:
        worker_config = json.loads(
            (REPO_ROOT / "examples" / "worker-config.example.json").read_text(encoding="utf-8")
        )
        request = json.loads(
            (REPO_ROOT / "examples" / "request.json").read_text(encoding="utf-8")
        )

        self.assertEqual("<local-feishu-base-app-token>", worker_config["app_token"])
        self.assertEqual("<local-pins-table-id>", worker_config["tables"]["pins"]["table_id"])
        self.assertEqual("Example Board", request["board"])

    def test_local_secret_paths_are_ignored(self) -> None:
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

        for pattern in (
            ".env",
            ".secrets/",
            ".gstack/",
            "worker-config.local.json",
            "feishu-worker-config.local.json",
            "request.local.json",
            "chrome-profile/",
        ):
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, gitignore)

    def test_docs_call_out_public_repo_safety(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("This repository is public", readme)
        self.assertIn("Never commit Pinterest or Feishu account-specific data", readme)
        self.assertIn(".gstack/feishu-worker-config.json", readme)


if __name__ == "__main__":
    unittest.main()
