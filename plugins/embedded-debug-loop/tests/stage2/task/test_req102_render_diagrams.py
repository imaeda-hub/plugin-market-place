"""scripts/render_diagrams.py の試験（REQ-102 工程のループ図と構成の図を、工程が変わるたびに描き直す）。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "render_diagrams.py"

BLUE = "#1565c0"
YELLOW = "#f6c343"
RED = "#d64541"
GREY = "#e3e8ee"


def make_state(**changes):
    state = {
        "stage": "ビルド",
        "run_state": "動いている",
        "reason": None,
        "iteration": 2,
        "max_iterations": 3,
        "active": ["build"],
    }
    state.update(changes)
    return state


class REQ102RenderDiagrams(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def render(self, state):
        state_file = self.root / "state.json"
        state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        out = self.root / "out"
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(state_file), str(out)],
            capture_output=True, text=True,
        )
        return result, out

    def test_REQ102_running_stage_is_blue_and_writes_both_svgs(self):
        """REQ-102 動いている工程が青で描かれ、2つの SVG が書き出される。"""
        result, out = self.render(make_state())
        self.assertEqual(result.returncode, 0, result.stderr)
        loop = (out / "process_loop.svg").read_text(encoding="utf-8")
        agents = (out / "agent_diagram.svg").read_text(encoding="utf-8")
        self.assertTrue(loop.startswith("<svg"))
        self.assertTrue(agents.startswith("<svg"))
        self.assertIn(BLUE, loop)
        self.assertIn(BLUE, agents)

    def test_REQ102_question_wait_is_yellow(self):
        """REQ-102 判断待ち（質問）は黄で描かれる。"""
        result, out = self.render(make_state(
            stage="初期の対話", run_state="人間の判断待ち", reason="成功条件の確認", iteration=None, active=[]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(YELLOW, (out / "process_loop.svg").read_text(encoding="utf-8"))

    def test_REQ102_error_wait_is_red(self):
        """REQ-102 判断待ち（エラー）は赤で描かれる。"""
        result, out = self.render(make_state(
            stage="デプロイ", run_state="人間の判断待ち", reason="デプロイ失敗"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(RED, (out / "process_loop.svg").read_text(encoding="utf-8"))

    def test_REQ102_finished_is_grey(self):
        """REQ-102 終わった工程は灰で描かれる。"""
        result, out = self.render(make_state(
            stage="結果の出力", run_state="終わった", reason="成功条件を達成", active=[]))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(GREY, (out / "process_loop.svg").read_text(encoding="utf-8"))

    def test_REQ102_unknown_stage_is_an_error(self):
        """REQ-102 知らない工程は、図を書かずに失敗する。"""
        result, out = self.render(make_state(stage="雑談"))
        self.assertEqual(result.returncode, 2)
        self.assertFalse((out / "process_loop.svg").exists())

    def test_REQ102_reason_while_running_is_an_error(self):
        """REQ-102 動いているときに理由があると、失敗する。"""
        result, _ = self.render(make_state(reason="ビルド失敗"))
        self.assertEqual(result.returncode, 2)

    def test_REQ102_wait_with_end_reason_is_an_error(self):
        """REQ-102 判断待ちに、終わった理由を書くと、失敗する。"""
        result, _ = self.render(make_state(run_state="人間の判断待ち", reason="成功条件を達成"))
        self.assertEqual(result.returncode, 2)

    def test_REQ102_zero_max_iterations_is_an_error(self):
        """REQ-102 繰り返しの上限が1より小さいと、失敗する。"""
        result, _ = self.render(make_state(max_iterations=0))
        self.assertEqual(result.returncode, 2)

    def test_REQ102_not_json_is_an_error(self):
        """REQ-102 JSON でない状態ファイルは、失敗する。"""
        state_file = self.root / "broken.json"
        state_file.write_text("{ not json", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), str(state_file), str(self.root / "out")],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
