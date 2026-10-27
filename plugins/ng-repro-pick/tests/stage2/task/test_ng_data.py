"""ng-data の extract_ng の試験（標準ライブラリの unittest）。

試験は、試験用の results.xlsx と spec.docx を一時フォルダに作って読ませる。
"""
import hashlib
import importlib.util
import os
import tempfile
import unittest
import zipfile
from xml.sax.saxutils import escape

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.normpath(os.path.join(HERE, "..", "..", "..", "scripts", "ng_data_server.py"))

_spec = importlib.util.spec_from_file_location("ng_data_server", SCRIPT)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
RNS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_xlsx(path, sheets, inline=()):
    """sheets: [(シート名, 行の一覧)]。文字は共有文字列に入れる。inline のシートは inlineStr にする。"""
    shared = []

    def sidx(s):
        if s not in shared:
            shared.append(s)
        return shared.index(s)

    sheet_xml, rels, wb_sheets = [], [], []
    for n, (name, rows) in enumerate(sheets, 1):
        body = []
        for r, row in enumerate(rows, 1):
            cells = []
            for c, val in enumerate(row):
                ref = "%s%d" % ("ABCDEFGH"[c], r)
                if name in inline:
                    cells.append('<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, escape(val)))
                else:
                    cells.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, sidx(val)))
            body.append('<row r="%d">%s</row>' % (r, "".join(cells)))
        sheet_xml.append('<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (NS, "".join(body)))
        rels.append('<Relationship Id="rId%d" Type="x" Target="worksheets/sheet%d.xml"/>' % (n, n))
        wb_sheets.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (escape(name), n, n))
    sst = "".join("<si><t>%s</t></si>" % escape(s) for s in shared)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", '<workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>'
                    % (NS, RNS, "".join(wb_sheets)))
        zf.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="%s">%s</Relationships>'
                    % (PKG, "".join(rels)))
        for n, xml in enumerate(sheet_xml, 1):
            zf.writestr("xl/worksheets/sheet%d.xml" % n, xml)
        zf.writestr("xl/sharedStrings.xml", '<sst xmlns="%s">%s</sst>' % (NS, sst))


def make_docx(path, tables):
    """tables: [表（行の一覧。行は列の文字の一覧）]"""
    body = []
    for rows in tables:
        trs = []
        for row in rows:
            tcs = "".join('<w:tc><w:p><w:r><w:t>%s</w:t></w:r></w:p></w:tc>' % escape(c) for c in row)
            trs.append("<w:tr>%s</w:tr>" % tcs)
        body.append("<w:tbl>%s</w:tbl>" % "".join(trs))
    xml = '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (WNS, "".join(body))
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", xml)


RESULTS = [
    ["項目ID", "項目名", "判定", "備考"],
    ["T-1101", "電源投入", "OK", ""],
    ["T-1105", "UART 受信", "NG", "受信できない"],
    ["T-1106", "UART受信処理", "NG", ""],
    ["T-1110", "LED 表示", "NG", "点灯しない"],
    ["T-1111", "LED 表示", "保留", "準備中"],
]
SPEC = [
    ["項目ID", "機能", "前提条件"],
    ["T-1101", "電源投入", "実機"],
    ["T-1105", "UART 受信", "実機、恒温槽、PC"],
    ["T-1106", "UART受信処理", "実機"],
    ["T-1110", "LED 表示", "実機、電源"],
    ["T-1111", "LED 表示", "実機、電源、ケーブル"],
]


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.xlsx = os.path.join(self.dir, "results.xlsx")
        self.docx = os.path.join(self.dir, "spec.docx")
        make_xlsx(self.xlsx, [("結果", RESULTS), ("凡例", [["OK", "仕様どおりに動いた"], ["NG", "仕様どおりに動かなかった"], ["保留", "試験の準備が整わず判定していない"]])], inline=("凡例",))
        make_docx(self.docx, [SPEC])

    def tearDown(self):
        self._tmp.cleanup()


class Req101Tests(_Base):
    def test_reads_results_legend_and_spec_rows(self):
        """REQ-101: 結果の行すべて、凡例、仕様書の行すべてと、前提条件の一覧と数が返る。"""
        data = server.extract_ng(self.xlsx, self.docx)
        self.assertEqual(len(data["結果"]), 5)
        self.assertEqual(data["結果"][0], {"項目ID": "T-1101", "項目名": "電源投入", "判定": "OK", "備考": ""})
        self.assertEqual(data["凡例"][1], ["NG", "仕様どおりに動かなかった"])
        self.assertEqual(len(data["仕様書"]), 5)
        t1105 = [s for s in data["仕様書"] if s["項目ID"] == "T-1105"][0]
        self.assertEqual(t1105["前提条件一覧"], ["実機", "恒温槽", "PC"])
        self.assertEqual(t1105["前提条件の数"], 3)

    def test_inputs_are_not_changed(self):
        """REQ-101: 読んだ後も、2つのファイルの中身は変わらない。"""
        before = [hashlib.sha256(open(p, "rb").read()).hexdigest() for p in (self.xlsx, self.docx)]
        server.extract_ng(self.xlsx, self.docx)
        after = [hashlib.sha256(open(p, "rb").read()).hexdigest() for p in (self.xlsx, self.docx)]
        self.assertEqual(before, after)

    def test_missing_legend_sheet_is_an_error(self):
        """REQ-101: 異常な入力（「凡例」のシートがない）は、エラーになる。"""
        bad = os.path.join(self.dir, "bad.xlsx")
        make_xlsx(bad, [("結果", RESULTS)])
        with self.assertRaises(ValueError):
            server.extract_ng(bad, self.docx)

    def test_spec_without_requirement_table_is_an_error(self):
        """REQ-101: 異常な入力（項目ID・機能・前提条件の表がない）は、エラーになる。"""
        bad = os.path.join(self.dir, "bad.docx")
        make_docx(bad, [[["項目ID", "内容"], ["T-1", "x"]]])
        with self.assertRaises(ValueError):
            server.extract_ng(self.xlsx, bad)


class Req102Tests(_Base):
    def test_only_ng_rows_are_joined_with_spec(self):
        """REQ-102: NG の行だけが、仕様書の機能と前提条件とつながって返る。保留は入らない。"""
        data = server.extract_ng(self.xlsx, self.docx)
        ids = [r["項目ID"] for r in data["NG"]]
        self.assertEqual(ids, ["T-1105", "T-1106", "T-1110"])
        t1105 = data["NG"][0]
        self.assertEqual(t1105["機能"], "UART 受信")
        self.assertTrue(t1105["恒温槽を含む"])
        self.assertEqual(t1105["前提条件の数"], 3)
        self.assertFalse(data["NG"][1]["恒温槽を含む"])

    def test_ng_without_spec_row_is_reported_in_warnings(self):
        """REQ-102: 仕様書にない項目IDのNGは、該当なしとして、注意に書かれる。"""
        results = RESULTS + [["T-9999", "未知", "NG", ""]]
        path = os.path.join(self.dir, "r2.xlsx")
        make_xlsx(path, [("結果", results), ("凡例", [["OK", "x"]])], inline=("凡例",))
        data = server.extract_ng(path, self.docx)
        extra = [r for r in data["NG"] if r["項目ID"] == "T-9999"][0]
        self.assertFalse(extra["仕様書に該当"])
        self.assertTrue(any("T-9999" in w for w in data["注意"]))


if __name__ == "__main__":
    unittest.main()
