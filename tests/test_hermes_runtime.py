from __future__ import annotations

import tempfile
import unittest

from pathlib import Path

from pinterest_autopin.hermes_runtime import RuntimeErrorConfig, build_runtime_context


class HermesRuntimeTest(unittest.TestCase):
    def test_missing_identity_fails_without_local_dev(self) -> None:
        with self.assertRaises(RuntimeErrorConfig):
            build_runtime_context(env={}, temp_dir=tempfile.gettempdir())

    def test_local_dev_creates_explicit_local_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            context = build_runtime_context(env={}, local_dev=True, temp_dir=temp_dir)

        self.assertTrue(context.run_id.startswith("local:"))
        self.assertTrue(str(context.temp_dir).startswith(temp_dir))
        self.assertTrue(context.local_dev)

    def test_requires_configured_secrets(self) -> None:
        env = {
            "HERMES_RUN_ID": "run-1",
            "HERMES_AGENT_ID": "agent-1",
            "HERMES_JOB_ID": "job-1",
        }

        with self.assertRaisesRegex(RuntimeErrorConfig, "OPENAI_API_KEY"):
            build_runtime_context(env=env, required_secrets=("OPENAI_API_KEY",))

    def test_uses_runtime_temp_and_profile_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = {
                "HERMES_RUN_ID": "run-1",
                "HERMES_AGENT_ID": "agent-1",
                "HERMES_JOB_ID": "job-1",
                "PINTEREST_AUTOPIN_TMPDIR": temp_dir,
                "PINTEREST_AUTOPIN_CHROME_PROFILE": "/tmp/profile",
            }
            context = build_runtime_context(env=env)

        self.assertEqual("run-1", context.run_id)
        self.assertEqual("/tmp/profile", context.chrome_profile)
        self.assertIn("run-1", str(Path(context.temp_dir)))


if __name__ == "__main__":
    unittest.main()
