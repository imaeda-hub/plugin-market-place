"""scripts/log_event.py の試験（REQ-105 改善用のログを残す）。"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "log_event.py"

BASE_ARGS = ["--iteration", "1", "--pds", "Do", "--stage", "ビルド", "--role", "ビルド・デプロイ担当",
             "--judgment", "クロスコンパイルする", "--command", "make -f Makefile.target Release", "--result", "成功"]


class REQ105LogEvent(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "logs" / "improvement.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, args):
        return subprocess.run([sys.executable, str(SCRIPT), str(self.log), *args],
                              capture_output=True, text=True)

    def test_REQ105_one_line_of_json_with_all_fields(self):
        """REQ-105 1行の JSON に、時刻、イテレーション、PDS の段、工程、役、判断、コマンド、結果が入る。"""
        result = self.run_script(BASE_ARGS)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        for key in ("time", "iteration", "pds", "stage", "role", "judgment", "command", "result"):
            self.assertIn(key, record)
        self.assertEqual(record["iteration"], 1)
        self.assertEqual(record["pds"], "Do")
        self.assertEqual(record["result"], "成功")

    def test_REQ105_appends_and_keeps_earlier_lines(self):
        """REQ-105 2回目の記録は、後ろへ足される。前の行は消えない。"""
        self.run_script(BASE_ARGS)
        self.run_script(["--iteration", "2", "--pds", "See", "--stage", "分析と次の計画", "--role", "まとめ役",
                         "--judgment", "次は変数の型を見る"])
        lines = self.log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["pds"], "See")
        self.assertEqual(json.loads(lines[1])["command"], "")

    def test_REQ105_unknown_pds_is_an_error(self):
        """REQ-105 PDS の段が Plan、Do、See のどれでもないと、失敗して行を足さない。"""
        args = [a if a != "Do" else "Study" for a in BASE_ARGS]
        result = self.run_script(args)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())

    def test_REQ105_iteration_zero_is_an_error(self):
        """REQ-105 イテレーションの番号が1より小さいと、失敗する。"""
        args = [a if a != "1" else "0" for a in BASE_ARGS]
        result = self.run_script(args)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

    def test_REQ105_blank_judgment_is_an_error(self):
        """REQ-105 判断が空だと、失敗する。"""
        args = [a if a != "クロスコンパイルする" else "  " for a in BASE_ARGS]
        result = self.run_script(args)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.log.exists())

    def test_REQ105_missing_required_option_is_an_error(self):
        """REQ-105 必要な項目（役）が無いと、失敗する。"""
        args = ["--iteration", "1", "--pds", "Do", "--stage", "ビルド", "--judgment", "x"]
        result = self.run_script(args)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
