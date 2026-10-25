"""scripts/snapshot_and_diff.py の試験（REQ-104 変えたソースコードの差分を、ファイルで残す）。"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "snapshot_and_diff.py"


class REQ104SnapshotAndDiff(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.src = self.root / "src"
        self.snap = self.root / "work" / "snapshot"
        self.patch = self.root / "work" / "result" / "code-diff.patch"
        self.src.mkdir()
        (self.src / "main.c").write_text("int main(void) {\n    return 0;\n}\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)

    def test_REQ104_snapshot_copies_the_source(self):
        """REQ-104 写しは、変える前のソースと同じ内容になる。"""
        result = self.run_script("snapshot", str(self.src), str(self.snap))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.snap / "main.c").read_text(encoding="utf-8"),
                         (self.src / "main.c").read_text(encoding="utf-8"))

    def test_REQ104_second_snapshot_does_not_overwrite(self):
        """REQ-104 写しが既にあれば、取り直さない（変えた後に写しが書き換わらない）。"""
        self.run_script("snapshot", str(self.src), str(self.snap))
        (self.src / "main.c").write_text("changed\n", encoding="utf-8")
        result = self.run_script("snapshot", str(self.src), str(self.snap))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("int main", (self.snap / "main.c").read_text(encoding="utf-8"))

    def test_REQ104_diff_shows_only_the_changed_lines(self):
        """REQ-104 差分に、変えた行が unified diff の形で出る。"""
        self.run_script("snapshot", str(self.src), str(self.snap))
        (self.src / "main.c").write_text("int main(void) {\n    return 1;\n}\n", encoding="utf-8")
        result = self.run_script("diff", str(self.src), str(self.snap), str(self.patch))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.patch.read_text(encoding="utf-8")
        self.assertIn("--- a/main.c", text)
        self.assertIn("+++ b/main.c", text)
        self.assertIn("-    return 0;", text)
        self.assertIn("+    return 1;", text)

    def test_REQ104_no_change_gives_an_empty_diff(self):
        """REQ-104 変えていなければ、差分のファイルは空になる。"""
        self.run_script("snapshot", str(self.src), str(self.snap))
        result = self.run_script("diff", str(self.src), str(self.snap), str(self.patch))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.patch.read_text(encoding="utf-8"), "")

    def test_REQ104_new_file_is_shown_from_dev_null(self):
        """REQ-104 新しく作ったファイルは、/dev/null からの追加として出る。"""
        self.run_script("snapshot", str(self.src), str(self.snap))
        (self.src / "dbg.h").write_text("#define X 1\n", encoding="utf-8")
        result = self.run_script("diff", str(self.src), str(self.snap), str(self.patch))
        self.assertEqual(result.returncode, 0, result.stderr)
        text = self.patch.read_text(encoding="utf-8")
        self.assertIn("--- /dev/null", text)
        self.assertIn("+#define X 1", text)

    def test_REQ104_git_folder_is_ignored(self):
        """REQ-104 .git のフォルダは差分に入らない。"""
        self.run_script("snapshot", str(self.src), str(self.snap))
        (self.src / ".git").mkdir()
        (self.src / ".git" / "config").write_text("x\n", encoding="utf-8")
        result = self.run_script("diff", str(self.src), str(self.snap), str(self.patch))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.patch.read_text(encoding="utf-8"), "")

    def test_REQ104_missing_source_is_an_error(self):
        """REQ-104 ソースのフォルダが無いと、写しを取らずに失敗する。"""
        result = self.run_script("snapshot", str(self.root / "nothing"), str(self.snap))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.snap.exists())

    def test_REQ104_diff_without_snapshot_is_an_error(self):
        """REQ-104 写しが無いときの差分は、失敗する。"""
        result = self.run_script("diff", str(self.src), str(self.snap), str(self.patch))
        self.assertEqual(result.returncode, 2)

    def test_REQ104_wrong_arguments_is_an_error(self):
        """REQ-104 引数が正しくないと、使い方を出して失敗する。"""
        result = self.run_script("unknown")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
