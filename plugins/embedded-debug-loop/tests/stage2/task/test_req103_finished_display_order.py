"""task.json の displays の試験（REQ-103 結論と結果を、決まった順と形で表示する）。

終わった後の画面は、結論、デバッグループ全体の結果、各イテレーションの PDS 概要（表）の順に出す。
この順は task.json の displays（when が finished のもの）で決まるので、その並びを確かめる。
"""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TASK = ROOT / "com.github.copilot" / "extensions" / "embedded-debug-loop" / "task.json"
ORDER = [("conclusion", "text"), ("debug_result", "text"), ("pds_summary", "table")]


def finished_head(displays):
    """終わった後に出る表示（when が finished）の、初めの3つの（key, type）。"""
    items = [(d.get("key"), d.get("type")) for d in displays if isinstance(d, dict) and d.get("when") == "finished"]
    return items[:len(ORDER)]


class REQ103FinishedDisplayOrder(unittest.TestCase):
    def load_displays(self):
        return json.loads(TASK.read_text(encoding="utf-8"))["displays"]

    def test_REQ103_conclusion_then_result_then_pds_table(self):
        """REQ-103 終わった後の表示は、結論、デバッグループ全体の結果、PDS の表の順に並ぶ。"""
        self.assertEqual(finished_head(self.load_displays()), ORDER)

    def test_REQ103_pds_table_moved_to_front_is_rejected(self):
        """REQ-103 PDS の表を結論より前に置いた並びは、決まった順に合わないとして断られる。"""
        displays = self.load_displays()
        pds = next(d for d in displays if d.get("key") == "pds_summary")
        displays = [pds] + [d for d in displays if d is not pds]
        self.assertNotEqual(finished_head(displays), ORDER)

    def test_REQ103_missing_conclusion_is_rejected(self):
        """REQ-103 結論の表示がない並びは、決まった順に合わないとして断られる。"""
        displays = [d for d in self.load_displays() if d.get("key") != "conclusion"]
        self.assertNotEqual(finished_head(displays), ORDER)


if __name__ == "__main__":
    unittest.main()
