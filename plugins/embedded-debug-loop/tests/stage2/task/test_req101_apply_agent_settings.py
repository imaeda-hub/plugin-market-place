"""scripts/apply_agent_settings.py の試験（REQ-101 作業の始めに、エフォートレベルを各エージェントに反映する）。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "apply_agent_settings.py"

AGENT_TEXT = (
    "---\n"
    "description: \"試験用\"\n"
    "model: [claude-sonnet-5.5, gpt-6.1-sol]\n"
    "---\n"
    "\n"
    "本文\n"
)
NAMES = ["orchestrator", "worker", "worker-b", "verifier"]


class REQ101ApplyAgentSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        for name in NAMES:
            (self.dir / f"{name}.agent.md").write_text(AGENT_TEXT, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, settings):
        settings_file = self.dir / "settings.json"
        settings_file.write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.dir), str(settings_file)],
            capture_output=True, text=True,
        )

    def read(self, name):
        return (self.dir / f"{name}.agent.md").read_text(encoding="utf-8")

    def test_REQ101_high_is_written_to_each_agent(self):
        """REQ-101 選んだ値（high）が、エージェントの reasoningEffort に入る。"""
        result = self.run_script({
            "effort_orchestrator": "high",
            "effort_worker": "low",
            "effort_worker_b": "medium",
            "effort_verifier": "high",
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("reasoningEffort: high", self.read("orchestrator"))
        self.assertIn("reasoningEffort: low", self.read("worker"))
        self.assertIn("reasoningEffort: medium", self.read("worker-b"))
        self.assertIn("reasoningEffort: high", self.read("verifier"))

    def test_REQ101_default_removes_the_line(self):
        """REQ-101 「既定のまま」を選ぶと、reasoningEffort の行がなくなる。"""
        self.run_script({"effort_worker": "high"})
        self.assertIn("reasoningEffort: high", self.read("worker"))
        result = self.run_script({"effort_worker": "既定のまま"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("reasoningEffort", self.read("worker"))

    def test_REQ101_model_line_is_kept(self):
        """REQ-101 モデルの行（model）は書き換わらない。"""
        self.run_script({"effort_orchestrator": "low"})
        self.assertIn("model: [claude-sonnet-5.5, gpt-6.1-sol]", self.read("orchestrator"))
        self.assertIn("本文", self.read("orchestrator"))

    def test_REQ101_missing_key_leaves_file_alone(self):
        """REQ-101 設定に無いエージェントの定義は変えない。"""
        before = self.read("verifier")
        result = self.run_script({"effort_worker": "low"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read("verifier"), before)

    def test_REQ101_invalid_value_changes_nothing(self):
        """REQ-101 正しくない値があれば、どのファイルも書き換えずに失敗する。"""
        before = {name: self.read(name) for name in NAMES}
        result = self.run_script({"effort_orchestrator": "high", "effort_worker": "extreme"})
        self.assertNotEqual(result.returncode, 0)
        for name in NAMES:
            self.assertEqual(self.read(name), before[name])

    def test_REQ101_missing_frontmatter_is_an_error(self):
        """REQ-101 フロントマターがない定義は、エラーにして書き換えない。"""
        (self.dir / "worker.agent.md").write_text("本文だけ\n", encoding="utf-8")
        result = self.run_script({"effort_worker": "high"})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((self.dir / "worker.agent.md").read_text(encoding="utf-8"), "本文だけ\n")

    def test_REQ101_wrong_arguments_is_an_error(self):
        """REQ-101 引数が足りないときは、使い方を出して失敗する。"""
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
