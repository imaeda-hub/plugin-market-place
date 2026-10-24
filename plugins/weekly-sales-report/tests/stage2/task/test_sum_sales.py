"""sum_sales.py の試験（標準ライブラリの unittest）。

試験の名前に、確かめる要件の番号（REQ-101 など）を入れる。
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.normpath(os.path.join(HERE, "..", "..", "..", "scripts", "sum_sales.py"))

HEADER = "日付,担当,金額\n"


def run_script(csv_text, args_extra=None):
    """CSV の中身を一時ファイルに書いてスクリプトを動かし、(終了コード, 標準出力, 標準エラー) を返す。"""
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "sales.csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(csv_text)
        args = [sys.executable, SCRIPT, path] if args_extra is None else [sys.executable, SCRIPT] + args_extra
        p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8")
        return p.returncode, p.stdout, p.stderr


def people_map(result):
    return {p["name"]: p for p in result["people"]}


class Req101PerPersonAmount(unittest.TestCase):
    def test_REQ_101_担当ごとの金額は円から万円にし1万円未満を切り捨てる(self):
        code, out, err = run_script(HEADER + "2026-10-05,佐藤,312000\n2026-10-06,鈴木,187000\n")
        self.assertEqual(code, 0, err)
        people = people_map(json.loads(out))
        self.assertEqual(people["佐藤"]["man"], 31)
        self.assertEqual(people["佐藤"]["label"], "31万円")
        self.assertEqual(people["鈴木"]["man"], 18)
        self.assertEqual(people["鈴木"]["label"], "18万円")

    def test_REQ_101_1万円に満たない担当は1万円未満と書く(self):
        code, out, err = run_script(HEADER + "2026-10-08,田中,6000\n")
        self.assertEqual(code, 0, err)
        tanaka = people_map(json.loads(out))["田中"]
        self.assertEqual(tanaka["man"], 0)
        self.assertEqual(tanaka["label"], "1万円未満")
        self.assertNotIn("0万円", tanaka["label"])

    def test_REQ_101_同じ担当の行は円を足してから万円にする(self):
        code, out, err = run_script(
            HEADER + "2026-10-05,佐藤,6000\n2026-10-06,佐藤,6000\n"
        )
        self.assertEqual(code, 0, err)
        sato = people_map(json.loads(out))["佐藤"]
        self.assertEqual(sato["yen"], 12000)
        self.assertEqual(sato["man"], 1)

    def test_REQ_101_桁区切りや円の単位があっても整数として読める(self):
        code, out, err = run_script(
            HEADER + '2026-10-05,佐藤,"312,000円"\n2026-10-06,鈴木,187000\n'
        )
        self.assertEqual(code, 0, err)
        people = people_map(json.loads(out))
        self.assertEqual(people["佐藤"]["yen"], 312000)
        self.assertEqual(people["鈴木"]["yen"], 187000)

    def test_REQ_101_桁区切りが囲みなしでも金額として読める(self):
        code, out, err = run_script(HEADER + "2026-10-05,佐藤,312,000\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(people_map(json.loads(out))["佐藤"]["yen"], 312000)

    def test_REQ_101_見出しの行がなくても読める(self):
        code, out, err = run_script("2026-10-05,佐藤,312000\n")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["rows"], 1)


class Req102Total(unittest.TestCase):
    def test_REQ_102_合計は円のまま足してから万円に切り捨てる(self):
        # 2026-10-19〜22 の T-02 と同じ数。担当ごとの万円の和は 45 万円になるが、合計は 47 万円。
        code, out, err = run_script(
            HEADER
            + "2026-10-19,佐藤,158000\n"
            + "2026-10-20,鈴木,204000\n"
            + "2026-10-21,田中,9000\n"
            + "2026-10-22,高橋,100000\n"
        )
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["total_yen"], 471000)
        self.assertEqual(result["total_man"], 47)
        self.assertEqual(result["total_label"], "47万円")
        self.assertNotEqual(sum(p["man"] for p in result["people"]), 47)

    def test_REQ_102_合計505000円は50万円(self):
        code, out, err = run_script(
            HEADER + "2026-10-05,佐藤,312000\n2026-10-06,鈴木,187000\n2026-10-08,田中,6000\n"
        )
        self.assertEqual(code, 0, err)
        result = json.loads(out)
        self.assertEqual(result["total_yen"], 505000)
        self.assertEqual(result["total_man"], 50)
        self.assertEqual(result["total_label"], "50万円")


class Req104ReadingAndStopping(unittest.TestCase):
    def assert_stops_with_row(self, csv_text, expected_line):
        code, out, err = run_script(csv_text)
        self.assertEqual(code, 2)
        self.assertEqual(out, "", "読めない行があるときは何も出さない")
        self.assertIn(f"{expected_line} 行目", err)

    def test_REQ_104_金額が読めない行で止まり行番号を示す(self):
        self.assert_stops_with_row(HEADER + "2026-10-05,佐藤,312000\n2026-10-06,鈴木,たくさん\n", 3)

    def test_REQ_104_金額が空欄の行で止まる(self):
        self.assert_stops_with_row(HEADER + "2026-10-05,佐藤,\n", 2)

    def test_REQ_104_担当が空欄の行で止まる(self):
        self.assert_stops_with_row(HEADER + "2026-10-05,,312000\n", 2)

    def test_REQ_104_列が足りない行で止まる(self):
        self.assert_stops_with_row(HEADER + "2026-10-05,佐藤\n", 2)

    def test_REQ_104_小数の金額は整数として読めないので止まる(self):
        self.assert_stops_with_row(HEADER + "2026-10-05,佐藤,312000.5\n", 2)

    def test_REQ_104_読めない行の後の行を飛ばして集計しない(self):
        code, out, err = run_script(
            HEADER + "2026-10-05,佐藤,312000\n2026-10-06,鈴木,x\n2026-10-08,田中,6000\n"
        )
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_REQ_104_売上の行がないと止まる(self):
        code, out, err = run_script(HEADER)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_REQ_104_引数がないと使い方を出して止まる(self):
        code, out, err = run_script("", args_extra=[])
        self.assertEqual(code, 1)
        self.assertIn("使い方", err)

    def test_REQ_104_ファイルがないと止まる(self):
        p = subprocess.run(
            [sys.executable, SCRIPT, os.path.join(HERE, "no-such-file.csv")],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(p.returncode, 2)
        self.assertEqual(p.stdout, "")


if __name__ == "__main__":
    unittest.main()
