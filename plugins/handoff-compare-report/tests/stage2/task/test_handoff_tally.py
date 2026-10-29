"""handoff_tally.py の試験。合成した4つのファイルで、数え方・結論・報告の確かめ・コマンド・MCP を確かめる。

試験の名前の先頭に、確かめる要件の番号（REQ-101 など）を書く。
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "handoff_tally.py"
_spec = importlib.util.spec_from_file_location("handoff_tally", SCRIPT)
ht = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ht)

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"

REPORT_OK = """結論：(c)
理由：AI を入れない理由の例
(a) AI なし：漏れ 3件（病状の重さ 1、患者の要約 0、すること 2、気をつけること 0）、見立ての不同意 1件、1件あたり 5.5分、受け手が気づいた欠け 3件
(b) AI が全体を下書き：漏れ 1件（病状の重さ 1、患者の要約 0、すること 0、気をつけること 0）、見立ての不同意 0件、1件あたり 5.0分、受け手が気づいた欠け 0件
(c) 事実の欄だけ AI：漏れ 0件（病状の重さ 0、患者の要約 0、すること 0、気をつけること 0）、見立ての不同意 1件、1件あたり 6.0分、受け手が気づいた欠け 1件

| 患者 | (a) | (b) | (c) |
|---|---|---|---|
| P-01 | 2 | 1 | 0 |
| P-02 | 1 | 0 | 0 |
"""


def col_name(index):
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def make_xlsx(path, sheets):
    """シート名と行の並びから、最小限の xlsx を作る（文字は共有文字列、数は数のセル）。"""
    shared = []
    position = {}

    def sid(text):
        if text not in position:
            position[text] = len(shared)
            shared.append(text)
        return position[text]

    sheet_xml = []
    for _, rows in sheets:
        body = []
        for r, row in enumerate(rows, start=1):
            cells = []
            for c, value in enumerate(row):
                if value is None:
                    continue
                ref = "%s%d" % (col_name(c), r)
                if isinstance(value, (int, float)):
                    cells.append('<c r="%s"><v>%s</v></c>' % (ref, value))
                else:
                    cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, sid(value)))
            body.append('<row r="%d">%s</row>' % (r, "".join(cells)))
        sheet_xml.append('<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (NS, "".join(body)))
    sheets_xml = "".join(
        '<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(name), i + 1, i + 1)
        for i, (name, _) in enumerate(sheets)
    )
    workbook = '<workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>' % (NS, NS_R, sheets_xml)
    rels = "".join(
        '<Relationship Id="rId%d" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet%d.xml"/>'
        % (i + 1, i + 1)
        for i in range(len(sheets))
    )
    rels = (
        '<Relationships xmlns="%s">%s<Relationship Id="rIdSST" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>'
        % (NS_PKG, rels)
    )
    sst = '<sst xmlns="%s">%s</sst>' % (NS, "".join("<si><t>%s</t></si>" % escape(t) for t in shared))
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/sharedStrings.xml", sst)
        for i, xml in enumerate(sheet_xml):
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), xml)


def write_ward(folder, skip=()):
    """合成の病棟のフォルダを作る。数えると、漏れ a3 b1 c0、不同意 a1 b0 c1、欠け a3 b0 c1、1件あたり 5.5・5.0・6.0、結論 (c)。"""
    os.makedirs(folder, exist_ok=True)
    make_xlsx(os.path.join(folder, "reference.xlsx"), [("正解", [
        ["患者", "項目番号", "欄", "書かれるべきこと"],
        ["P-01", 1, "病状の重さ", "x"],
        ["P-01", 2, "患者の要約", "x"],
        ["P-01", 3, "すること", "x"],
        ["P-02", 1, "病状の重さ", "x"],
        ["P-02", 2, "すること", "x"],
        ["P-02", 4, "受け手の要約", "x"],
    ])])
    with open(os.path.join(folder, "handoffs.docx"), "wb") as handle:
        handle.write(b"dummy")
    make_xlsx(os.path.join(folder, "judgments.xlsx"), [
        ("漏れ", [
            ["患者", "記号", "項目番号", "判定者1", "判定者2", "合議"],
            ["P-01", "X", 1, "漏れ", "漏れ", None],
            ["P-01", "X", 2, "あり", "あり", None],
            ["P-01", "X", 3, "あり", "漏れ", "漏れ"],
            ["P-01", "Y", 1, "漏れ", "漏れ", None],
            ["P-02", "X", 1, "あり", "あり", None],
            ["P-02", "Y", 2, "漏れ", "あり", "あり"],
            ["P-02", "Z", 4, "漏れ", "漏れ", None],
            ["P-02", "Z", 2, "漏れ", "漏れ", None],
        ]),
        ("見立て", [
            ["患者", "記号", "判定"],
            ["P-01", "X", "不同意"],
            ["P-01", "Y", "同意"],
            ["P-02", "Y", "不同意"],
            ["P-02", "Z", "書かれていない"],
        ]),
        ("受け手", [
            ["患者", "記号", "気づいた欠け"],
            ["P-01", "X", 2],
            ["P-01", "Y", 0],
            ["P-02", "Y", 1],
            ["P-02", "Z", 1],
        ]),
        ("凡例", [["記号", "意味"], ["あり", "書かれている"]]),
    ])
    make_xlsx(os.path.join(folder, "timelog.xlsx"), [
        ("時間", [
            ["患者", "形", "書く（分）", "直す（分）", "備考"],
            ["P-01", "X", 3, 2, None],
            ["P-01", "Y", 4, 1, None],
            ["P-01", "Z", 4, 2, None],
            ["P-02", "X", 1, 2, "中断"],
            ["P-02", "Y", 3, 3, None],
            ["P-02", "Z", 2, 4, None],
        ]),
        ("記号の対応", [
            ["患者", "記号", "形"],
            ["P-01", "X", "(a)"],
            ["P-01", "Y", "(b)"],
            ["P-01", "Z", "(c)"],
            ["P-02", "X", "(b)"],
            ["P-02", "Y", "(c)"],
            ["P-02", "Z", "(a)"],
        ]),
    ])
    for name in skip:
        os.remove(os.path.join(folder, name))
    return folder


def run_cli(args, cwd=None):
    proc = subprocess.run([sys.executable, "-I", str(SCRIPT)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, timeout=120)
    return proc.returncode, proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8")


class HandoffTallyTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = write_ward(os.path.join(self._tmp.name, "ward"))

    def tearDown(self):
        self._tmp.cleanup()

    def report(self, text):
        path = os.path.join(self.folder, "compare_report.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_REQ_101_missing_file_is_named(self):
        """REQ-101 病棟のフォルダに足りないファイルがあれば、その名前を返す。"""
        folder = write_ward(os.path.join(self._tmp.name, "short"), skip=("timelog.xlsx",))
        result = ht.tally(folder)
        self.assertFalse(result["ok"])
        self.assertEqual(result["missing"], ["timelog.xlsx"])

    def test_REQ_101_cli_missing_exit_1_and_json(self):
        """REQ-101 コマンドで足りないファイルを示し、終了コード 1 で終わる。"""
        folder = write_ward(os.path.join(self._tmp.name, "short2"), skip=("judgments.xlsx",))
        code, out, _ = run_cli(["tally", folder])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["missing"], ["judgments.xlsx"])

    def test_REQ_102_reads_cell_values_directly(self):
        """REQ-102 Excel の共有文字列と数のセルを、セルの値のまま読む。"""
        book = ht.read_workbook(os.path.join(self.folder, "timelog.xlsx"))
        self.assertIn("時間", book)
        self.assertEqual(book["時間"][1][0], "P-01")
        self.assertEqual(book["時間"][1][2], 3)
        self.assertEqual(book["記号の対応"][1][2], "(a)")

    def test_REQ_103_symbols_are_mapped_per_patient(self):
        """REQ-103 記号は患者ごとに形に戻す（同じ X でも患者によって形が違う）。"""
        patients = set()
        mapping = ht._symbol_map(ht.read_workbook(os.path.join(self.folder, "timelog.xlsx"))["記号の対応"], patients)
        self.assertEqual(mapping[("P-01", "X")], "a")
        self.assertEqual(mapping[("P-02", "X")], "b")
        self.assertEqual(patients, {"P-01", "P-02"})

    def test_REQ_104_leak_counts_by_form_field_and_patient(self):
        """REQ-104 漏れを、判定者2人と合議の列、正解の一覧の欄、受け手の要約の除外で数える。"""
        result = ht.tally(self.folder)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["forms"]["a"]["漏れ"], 3)
        self.assertEqual(result["forms"]["b"]["漏れ"], 1)
        self.assertEqual(result["forms"]["c"]["漏れ"], 0)
        self.assertEqual(result["forms"]["a"]["欄"]["病状の重さ"], 1)
        self.assertEqual(result["forms"]["a"]["欄"]["すること"], 2)
        self.assertEqual(result["per_patient"]["P-01"], {"a": 2, "b": 1, "c": 0})
        self.assertEqual(result["per_patient"]["P-02"], {"a": 1, "b": 0, "c": 0})

    def test_REQ_105_disagree_and_gaps(self):
        """REQ-105 見立ての「不同意」と受け手の「気づいた欠け」を、形ごとに集める。"""
        result = ht.tally(self.folder)
        self.assertEqual([result["forms"][f]["見立ての不同意"] for f in "abc"], [1, 0, 1])
        self.assertEqual([result["forms"][f]["受け手が気づいた欠け"] for f in "abc"], [3, 0, 1])

    def test_REQ_106_minutes_one_decimal_and_chuudan_excluded(self):
        """REQ-106 1件あたりは「書く」＋「直す」の平均を小数第1位で出し、備考「中断」の件は外す。"""
        result = ht.tally(self.folder)
        self.assertEqual([result["forms"][f]["1件あたり"] for f in "abc"], ["5.5", "5.0", "6.0"])
        self.assertEqual(result["forms"]["b"]["中断で外した件"], 1)
        self.assertEqual(result["forms"]["b"]["件数"], 1)

    def test_REQ_107_conclusion_is_c(self):
        """REQ-107 (c) は漏れが3件以上少なく、時間の増えが2分以内、不同意が (a) より多くないので (c) になる。"""
        result = ht.tally(self.folder)
        self.assertEqual(result["conclusion"], "c")
        self.assertFalse(result["conclusion_check"]["b"]["入れられる"])
        self.assertTrue(result["conclusion_check"]["c"]["入れられる"])

    def test_REQ_107_disagree_blocks_candidate(self):
        """REQ-107 見立ての不同意が (a) より多い形は、ほかの条件を満たしても入れない。"""
        forms = {
            "a": {"漏れ": 9, "1件あたり": "6.5", "見立ての不同意": 0},
            "b": {"漏れ": 0, "1件あたり": "7.0", "見立ての不同意": 1},
            "c": {"漏れ": 9, "1件あたり": "6.5", "見立ての不同意": 0},
        }
        conclusion, _, _ = ht._decide(forms)
        self.assertEqual(conclusion, "a")

    def test_REQ_107_tie_is_undecided(self):
        """REQ-107 (b)(c) が両方入れられ、漏れの合計が同じときは決まらないと返す（決まりにない）。"""
        forms = {
            "a": {"漏れ": 9, "1件あたり": "6.5", "見立ての不同意": 1},
            "b": {"漏れ": 5, "1件あたり": "7.0", "見立ての不同意": 0},
            "c": {"漏れ": 5, "1件あたり": "7.0", "見立ての不同意": 0},
        }
        conclusion, _, note = ht._decide(forms)
        self.assertIsNone(conclusion)
        self.assertTrue(note)

    def test_REQ_108_correct_report_passes(self):
        """REQ-108 形の正しい報告は、項目ごとに合格になる。"""
        path = self.report(REPORT_OK)
        result = ht.check_report(self.folder, path)
        self.assertEqual(result["合否"], "合格", result["項目"])

    def test_REQ_108_wrong_conclusion_fails_first_line(self):
        """REQ-108 1行目の結論が数え直しと違えば、1行目の項目が不合格になる。"""
        path = self.report(REPORT_OK.replace("結論：(c)", "結論：(a)", 1))
        result = ht.check_report(self.folder, path)
        self.assertEqual(result["合否"], "不合格")
        first = [i for i in result["項目"] if i["項目"] == "1行目（結論）"][0]
        self.assertEqual(first["合否"], "不合格")

    def test_REQ_108_room_number_in_table_fails(self):
        """REQ-108 患者の書き方が P-01 の形でなく、病室の番号を付けた表は不合格になる。"""
        path = self.report(REPORT_OK.replace("| P-01 | 2 | 1 | 0 |", "| P-01（3号室） | 2 | 1 | 0 |"))
        result = ht.check_report(self.folder, path)
        table = [i for i in result["項目"] if i["項目"] == "患者別の表"][0]
        self.assertEqual(table["合否"], "不合格")

    def test_REQ_109_wrong_count_is_reported_with_difference(self):
        """REQ-109 形の行の数が数え直しと違えば、どの数がどれだけ違うかを違いに書く。"""
        path = self.report(REPORT_OK.replace("漏れ 3件", "漏れ 4件", 1))
        result = ht.check_report(self.folder, path)
        line_a = [i for i in result["項目"] if i["項目"] == "(a) の行"][0]
        self.assertEqual(line_a["合否"], "不合格")
        self.assertIn("漏れ が 4（数え直しは 3）", line_a["違い"])

    def test_REQ_109_check_does_not_change_report(self):
        """REQ-109 確かめるだけで、報告の中身は変わらない。"""
        path = self.report(REPORT_OK)
        before = open(path, encoding="utf-8").read()
        ht.check_report(self.folder, path)
        self.assertEqual(open(path, encoding="utf-8").read(), before)

    def test_REQ_110_help_exit_0_and_bad_args_exit_2(self):
        """REQ-110 --help は終了コード 0、誤った引数は終了コード 2 で終わる。"""
        code, out, _ = run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("tally", out)
        code, _, err = run_cli(["check", "only-one-arg"])
        self.assertEqual(code, 2)
        self.assertIn("使い方", err)

    def test_REQ_110_mcp_lists_two_tools(self):
        """REQ-110 MCP サーバーは、tally と check_report の2つのツールを出す。"""
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
        payload = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages).encode("utf-8")
        proc = subprocess.run([sys.executable, "-I", str(SCRIPT)], input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        lines = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]
        self.assertEqual(lines[0]["id"], 1)
        self.assertEqual(lines[0]["result"]["serverInfo"]["name"], "handoff-tally")
        names = [t["name"] for t in lines[1]["result"]["tools"]]
        self.assertEqual(names, ["tally", "check_report"])

    def test_REQ_101_broken_xlsx_is_reported_not_crashed(self):
        """REQ-101 Excel として読めないファイルは、落ちずに理由を返す（異常な入力）。"""
        folder = write_ward(os.path.join(self._tmp.name, "broken"))
        with open(os.path.join(folder, "judgments.xlsx"), "wb") as handle:
            handle.write(b"not a zip")
        result = ht.tally(folder)
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])


if __name__ == "__main__":
    unittest.main()
