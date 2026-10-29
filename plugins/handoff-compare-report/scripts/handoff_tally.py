#!/usr/bin/env python3
"""申し送りの3つの形 (a)(b)(c) の比較を、病棟のフォルダの4つのファイルから数え直し、比較報告 compare_report.md を確かめる。

MCP サーバー（標準入力と標準出力の JSON-RPC）としても、コマンドラインからも動く。Python 3 の標準ライブラリだけを使う。
  python3 handoff_tally.py                                          MCP サーバーとして動く
  python3 handoff_tally.py tally <病棟のフォルダ>                      数えた結果を JSON で標準出力に出す
  python3 handoff_tally.py check <病棟のフォルダ> <compare_report.md>   報告を数え直しと照らし、項目ごとの合否を JSON で出す
  python3 handoff_tally.py --help

終了コード: 0（数えられた・合格）、1（数えられない・不合格。理由は JSON の errors と 違い）、2（誤った引数）、3（報告を読めない）
ファイルは書き換えない。Excel は、Markdown に直さず、セルの値をそのまま読む。

決まり（ナレッジの番号つき。文は、頼みのナレッジの文をそのまま写した）：
- K-07：判定シートでは形を X・Y・Z の記号で伏せてあり、記号は患者ごとに付け替えている（同じ X でも患者によって形が違う）。数える前に、時間の記録の「記号の対応」のシートで、患者ごとに記号を (a)(b)(c) に戻す。報告では (a)(b)(c) で書く。
- K-09：judgments.xlsx（判定シート）は「漏れ」「見立て」「受け手」「凡例」の4つのシートからなる。「漏れ」のシートには判定者2人の列と「合議」の列があり、項目は番号で書かれる。列の見出しの名前までは決まっていない（前回は「患者・記号・項目番号・判定者1・判定者2・合議」）。 例外：列の見出しの名前が前回と違ってもよい。
- K-10：漏れは判定者2人の列で数える。判定が分かれた項目は「合議」の列の判定を使い、合議の列が空なら2人の判定は同じなのでそのまま使う。判定者1人の列だけで数えない。
- K-11：見立ての不同意は、判定シートの「見立て」のシートの「不同意」の数をそのまま使う（値は「同意・不同意・書かれていない」）。「書かれていない」件の扱いは特に決まっていない。
- K-12：判定シートの「受け手」シートの「気づいた欠け」（受け手役が受け手の要約を書くときに、足りないと気づいて聞き返したことの数）を、形ごとに合計する。
- K-14：受け手の要約の欄は、受け手役が書く欄なので漏れに数えない（項目番号ではなく、正解の一覧の欄が「受け手の要約」の項目を除く）。
- K-15：漏れは形ごとに合計し、欄ごと（病状の重さ、患者の要約、すること、気をつけること）の件数と患者別の数も出す。形ごとの行に書くのは、漏れの合計と欄ごとの件数。漏れの率を出すかどうかは特に決まっていない。
- K-16：1件あたりの時間は、timelog.xlsx の「書く」と「直す」の分を足して、形ごとに平均を出し、分で小数第1位まで書く（例：9.0分）。
- K-27：時間の記録の備考に「中断」とある件は、急変や電話で手が止まって時間が正しくないので、その形の1件あたりの時間の平均から外す。漏れ、見立ての不同意、受け手が気づいた欠けの数には入れる。
- K-31：漏れの欄ごとの内訳は、正解の一覧（reference.xlsx）でその患者の項目番号から欄を引いて数える（番号と欄の対応を決め打ちにしない）。受け手の要約の欄は漏れに数えない。
- K-38：数えるときは、Markdown に直さず、Excel を直接読んでセルの値をそのまま使って数える。
- K-21：結論の決め方：(b) か (c) を入れるのは、(a) と比べて漏れの合計が3件以上少なく、かつ1件あたりの時間の増え方が2分以内のときだけ。ただし、見立ての不同意が (a) より多い形は、この2つに当てはまっても入れない。両方入れられる形があるときは、漏れの合計が少ない方にする。どちらも当てはまらなければ結論は (a)。（_decide が行う）
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from decimal import ROUND_HALF_UP, Decimal

SERVER_NAME = "handoff-tally"
SERVER_VERSION = "1.0.0"
REQUIRED_FILES = ("reference.xlsx", "handoffs.docx", "judgments.xlsx", "timelog.xlsx")
FORMS = ("a", "b", "c")
FIELDS = ("病状の重さ", "患者の要約", "すること", "気をつけること")
SKIP_FIELD = "受け手の要約"
LEAK = "漏れ"
NOT_LEAK = ("あり",)
DISAGREE = "不同意"
CHUUDAN = "中断"
MIN_LEAK_GAIN = 3
MAX_MINUTES_UP = Decimal("2.0")

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

PATIENT_RE = re.compile(r"P\s*[-‐－ー]?\s*(\d+)", re.IGNORECASE)
LETTER_EXACT_RE = re.compile(r"\s*[（(]?\s*([abcABC])\s*[）)]?\s*")
LETTER_INSIDE_RE = re.compile(r"[（(]\s*([abcABC])\s*[）)]")
FORM_LINE_RE = re.compile(
    r"^\((a|b|c)\) ([^：\n]+)：漏れ (\d+)件（病状の重さ (\d+)、患者の要約 (\d+)、すること (\d+)、気をつけること (\d+)）、"
    r"見立ての不同意 (\d+)件、1件あたり (\d+\.\d)分、受け手が気づいた欠け (\d+)件$"
)
CONCLUSION_RE = re.compile(r"^結論：\((a|b|c)\)$")
TABLE_HEADER = ["患者", "(a)", "(b)", "(c)"]

WHERE_SYMBOL = "timelog.xlsx の「記号の対応」のシート"
WHERE_TIME = "timelog.xlsx の「時間」のシート"
WHERE_LEAK = "judgments.xlsx の「漏れ」のシート"
WHERE_VIEW = "judgments.xlsx の「見立て」のシート"
WHERE_RECEIVE = "judgments.xlsx の「受け手」のシート"
WHERE_REF = "reference.xlsx の最初のシート"


class TallyError(Exception):
    """数えられないときの誤り。文で理由を持つ。"""


# ---------------------------------------------------------------- Excel を読む（zipfile と xml）

def _tag(name):
    return "{%s}%s" % (NS, name)


def _col_index(ref):
    number = 0
    for ch in ref:
        if not ch.isalpha():
            break
        number = number * 26 + (ord(ch.upper()) - ord("A") + 1)
    return number - 1


def _row_index(ref):
    return int("".join(ch for ch in ref if ch.isdigit()))


def _cell_value(cell, shared):
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        holder = cell.find(_tag("is"))
        if holder is None:
            return None
        return "".join(t.text or "" for t in holder.iter(_tag("t")))
    value_el = cell.find(_tag("v"))
    if value_el is None or value_el.text is None:
        return None
    raw = value_el.text
    if kind == "s":
        return shared[int(raw)]
    if kind in ("str", "e"):
        return raw
    if kind == "b":
        return raw.strip() == "1"
    try:
        number = float(raw)
    except ValueError:
        return raw
    return int(number) if number.is_integer() else number


def _read_sheet(xml_bytes, shared):
    root = ET.fromstring(xml_bytes)
    cells = {}
    max_row = 0
    max_col = 0
    for cell in root.iter(_tag("c")):
        ref = cell.get("r")
        if not ref:
            continue
        value = _cell_value(cell, shared)
        if value is None or value == "":
            continue
        row, col = _row_index(ref), _col_index(ref)
        cells[(row, col)] = value
        max_row = max(max_row, row)
        max_col = max(max_col, col + 1)
    return [[cells.get((r, c)) for c in range(max_col)] for r in range(1, max_row + 1)]


def read_workbook(path):
    """Excel のブックを読み、シート名 -> 行の並び（セルの値そのまま）を返す。"""
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise TallyError("%s を Excel のファイルとして開けない（%s）" % (os.path.basename(path), exc))
    with archive:
        try:
            names = set(archive.namelist())
            book_xml = ET.fromstring(archive.read("xl/workbook.xml"))
            rels_xml = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            shared = []
            if "xl/sharedStrings.xml" in names:
                sst = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                for item in sst.findall(_tag("si")):
                    shared.append("".join(t.text or "" for t in item.iter(_tag("t"))))
            targets = {rel.get("Id"): rel.get("Target", "") for rel in rels_xml}
            sheets = {}
            holder = book_xml.find(_tag("sheets"))
            for sheet in (list(holder) if holder is not None else []):
                target = targets.get(sheet.get("{%s}id" % NS_REL), "")
                part = target[1:] if target.startswith("/") else "xl/" + target
                sheets[sheet.get("name", "")] = _read_sheet(archive.read(part), shared)
            return sheets
        except (KeyError, ValueError, IndexError, ET.ParseError) as exc:
            raise TallyError("%s の中身を読めない（%s）" % (os.path.basename(path), exc))


def _sheet(book, name, where):
    if name in book:
        return book[name]
    raise TallyError("%s に「%s」のシートがない" % (where, name))


# ---------------------------------------------------------------- 値の読み方

def text_of(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def number_of(value, where):
    """空なら None、数なら Decimal。数でなければ誤り。"""
    text = text_of(value).strip()
    if text == "":
        return None
    try:
        number = Decimal(text)
    except ArithmeticError:
        raise TallyError("%s：数で書かれていない（%s）" % (where, text))
    if not number.is_finite():
        raise TallyError("%s：数で書かれていない（%s）" % (where, text))
    return number


def _count_of(value, where):
    number = number_of(value, where)
    if number is None:
        return 0
    if number < 0 or number != number.to_integral_value():
        raise TallyError("%s：件数は 0 以上の整数で書かれていない（%s）" % (where, text_of(value)))
    return int(number)


def _patient(value, where):
    text = text_of(value)
    match = PATIENT_RE.search(text)
    if not match:
        raise TallyError("%s：患者の書き方（%s）が P-01 の形でない" % (where, text.strip()))
    return "P-%02d" % int(match.group(1))


def _letter(text):
    """(a)・a・（b）などから a・b・c を取る。形でなければ None。"""
    match = LETTER_EXACT_RE.fullmatch(text) or LETTER_INSIDE_RE.search(text)
    return match.group(1).lower() if match else None


def _form_of(mapping, patient, value, where):
    """記号を形に戻す。K-07：記号は患者ごとに付け替えてあるので、患者と記号の組で「記号の対応」を引く。"""
    text = text_of(value).strip()
    key = (patient, text.upper())
    if key in mapping:
        return mapping[key]
    letter = _letter(text)
    if letter is not None:
        return letter
    raise TallyError("%s：患者 %s の記号「%s」が、記号の対応にも形にもない" % (where, patient, text))


def _blank_row(row):
    return all(text_of(v).strip() == "" for v in row)


def _cell(row, col):
    return row[col] if col is not None and col < len(row) else None


def _has(word):
    return lambda text: word in text


def _zero_forms():
    return {f: 0 for f in FORMS}


def _find_header(rows, wanted, where):
    """先頭の10行から見出しの行を探す。wanted は 名前 -> 見出しの文字が合うかの関数（見出しの文字が少し違っても読む）。"""
    for index, row in enumerate(rows[:10]):
        texts = [text_of(v).strip() for v in row]
        found = {name: [j for j, t in enumerate(texts) if t and test(t)] for name, test in wanted.items()}
        if all(found.values()):
            return index, found
    raise TallyError("%s に、見出しの行が見つからない（%s が要る）" % (where, "、".join(wanted)))


def _one(found, name, where):
    cols = found[name]
    if len(cols) != 1:
        raise TallyError("%s：「%s」の見出しの列が1つに決まらない（%d 列）" % (where, name, len(cols)))
    return cols[0]


# ---------------------------------------------------------------- 数える

def _symbol_map(rows, patients):
    """「記号の対応」：(患者, 記号) -> 形。K-07。"""
    idx, found = _find_header(rows, {
        "患者": _has("患者"),
        "記号": _has("記号"),
        "形": lambda t: "形" in t and "記号" not in t,
    }, WHERE_SYMBOL)
    p_col = _one(found, "患者", WHERE_SYMBOL)
    s_col = _one(found, "記号", WHERE_SYMBOL)
    f_col = _one(found, "形", WHERE_SYMBOL)
    mapping = {}
    for row in rows[idx + 1:]:
        if _blank_row(row):
            continue
        patient = _patient(_cell(row, p_col), WHERE_SYMBOL)
        symbol = text_of(_cell(row, s_col)).strip().upper()
        form = _letter(text_of(_cell(row, f_col)).strip())
        if not symbol or form is None:
            raise TallyError("%s：患者 %s の記号と形（(a)(b)(c) のどれか）が読めない" % (WHERE_SYMBOL, patient))
        mapping[(patient, symbol)] = form
        patients.add(patient)
    return mapping


def _reference(rows):
    """正解の一覧：(患者, 項目番号) -> 欄。K-31：欄は、その患者の項目番号から引く。"""
    idx, found = _find_header(rows, {
        "患者": _has("患者"),
        "項目": _has("項目"),
        "欄": lambda t: "欄" in t and "項目" not in t,
    }, WHERE_REF)
    p_col = _one(found, "患者", WHERE_REF)
    i_col = _one(found, "項目", WHERE_REF)
    f_col = _one(found, "欄", WHERE_REF)
    table = {}
    for row in rows[idx + 1:]:
        if _blank_row(row):
            continue
        patient = _patient(_cell(row, p_col), WHERE_REF)
        item = text_of(_cell(row, i_col)).strip()
        field = text_of(_cell(row, f_col)).strip()
        if not item or not field:
            raise TallyError("%s：%s の項目番号か欄が空の行がある" % (WHERE_REF, patient))
        table[(patient, item)] = field
    return table


def _count_leaks(rows, mapping, ref, fields, per_patient, patients, warnings):
    """「漏れ」のシート。K-10：判定者2人の列で数える。合議の列があればそれを使う。K-31：欄は正解の一覧で引く。"""
    idx, found = _find_header(rows, {
        "患者": _has("患者"),
        "記号": _has("記号"),
        "項目": _has("項目"),
        "合議": _has("合議"),
        "判定": lambda t: "判定" in t and "合議" not in t,
    }, WHERE_LEAK)
    p_col = _one(found, "患者", WHERE_LEAK)
    s_col = _one(found, "記号", WHERE_LEAK)
    i_col = _one(found, "項目", WHERE_LEAK)
    g_col = _one(found, "合議", WHERE_LEAK)
    if len(found["判定"]) != 2:
        raise TallyError("%s：判定者の列が2つ見つからない（%d つ）" % (WHERE_LEAK, len(found["判定"])))
    first_col, second_col = found["判定"]
    for row in rows[idx + 1:]:
        if _blank_row(row):
            continue
        patient = _patient(_cell(row, p_col), WHERE_LEAK)
        patients.add(patient)
        symbol = text_of(_cell(row, s_col)).strip().upper()
        item = text_of(_cell(row, i_col)).strip()
        where = "%s（%s の項目 %s）" % (WHERE_LEAK, patient, item)
        joint = text_of(_cell(row, g_col)).strip()
        first = text_of(_cell(row, first_col)).strip()
        second = text_of(_cell(row, second_col)).strip()
        # K-10：漏れは判定者2人の列で数える。判定が分かれた項目は「合議」の列の判定を使い、合議の列が空なら2人の判定は同じなのでそのまま使う。判定者1人の列だけで数えない。
        if joint:
            decision = joint
        elif first and first == second:
            decision = first
        else:
            warnings.append("%s：合議の列が空で、判定者2人の判定が同じでないので数えなかった（%s、%s）" % (where, first or "空", second or "空"))
            continue
        if decision != LEAK and decision not in NOT_LEAK:
            warnings.append("%s：判定「%s」は、漏れにもあり にも当たらないので数えなかった" % (where, decision))
            continue
        field = ref.get((patient, item))
        if field is None:
            raise TallyError("%s：正解の一覧（reference.xlsx）に、この患者の項目番号 %s がない" % (WHERE_LEAK, item))
        form = _form_of(mapping, patient, symbol, where)
        # K-14、K-31：受け手の要約の欄は漏れに数えない。
        if field == SKIP_FIELD:
            continue
        if field not in FIELDS:
            raise TallyError("%s：正解の一覧の欄「%s」は、4つの欄（%s）のどれでもない" % (where, field, "、".join(FIELDS)))
        if decision == LEAK:
            fields[form][field] += 1
            per_patient.setdefault(patient, _zero_forms())[form] += 1


def _count_disagree(rows, mapping, patients, disagree):
    """「見立て」のシート。K-11：「不同意」の数をそのまま数える。「書かれていない」の扱いは決めず、数えない。"""
    idx, found = _find_header(rows, {"患者": _has("患者"), "記号": _has("記号")}, WHERE_VIEW)
    p_col = _one(found, "患者", WHERE_VIEW)
    s_col = _one(found, "記号", WHERE_VIEW)
    for row in rows[idx + 1:]:
        if _blank_row(row):
            continue
        patient = _patient(_cell(row, p_col), WHERE_VIEW)
        patients.add(patient)
        form = _form_of(mapping, patient, text_of(_cell(row, s_col)).strip(), WHERE_VIEW)
        values = [text_of(v).strip() for v in row]
        if DISAGREE in values:
            disagree[form] += 1


def _count_gaps(rows, mapping, patients, gaps):
    """「受け手」のシート。K-12：「気づいた欠け」の数を、形ごとに合計する。"""
    idx, found = _find_header(rows, {
        "患者": _has("患者"),
        "記号": _has("記号"),
        "欠け": _has("欠け"),
    }, WHERE_RECEIVE)
    p_col = _one(found, "患者", WHERE_RECEIVE)
    s_col = _one(found, "記号", WHERE_RECEIVE)
    k_col = _one(found, "欠け", WHERE_RECEIVE)
    for row in rows[idx + 1:]:
        if _blank_row(row):
            continue
        patient = _patient(_cell(row, p_col), WHERE_RECEIVE)
        patients.add(patient)
        form = _form_of(mapping, patient, text_of(_cell(row, s_col)).strip(), WHERE_RECEIVE)
        gaps[form] += _count_of(_cell(row, k_col), WHERE_RECEIVE)


def _time_stats(rows, mapping, patients, minutes, timed, excluded):
    """「時間」のシート。K-16：書く＋直す の平均。K-27：備考に「中断」の件は平均から外す（数には入れる）。"""
    idx, found = _find_header(rows, {
        "患者": _has("患者"),
        "形": lambda t: "形" in t or "記号" in t,
        "書く": _has("書く"),
        "直す": _has("直す"),
        "備考": _has("備考"),
    }, WHERE_TIME)
    p_col = _one(found, "患者", WHERE_TIME)
    f_col = _one(found, "形", WHERE_TIME)
    w_col = _one(found, "書く", WHERE_TIME)
    x_col = _one(found, "直す", WHERE_TIME)
    r_col = _one(found, "備考", WHERE_TIME)
    for row in rows[idx + 1:]:
        if _blank_row(row):
            continue
        patient = _patient(_cell(row, p_col), WHERE_TIME)
        patients.add(patient)
        form = _form_of(mapping, patient, text_of(_cell(row, f_col)).strip(), WHERE_TIME)
        if CHUUDAN in text_of(_cell(row, r_col)):
            excluded[form] += 1
            continue
        write = number_of(_cell(row, w_col), WHERE_TIME)
        fix = number_of(_cell(row, x_col), WHERE_TIME)
        if write is None or fix is None:
            raise TallyError("%s：患者 %s の「書く」か「直す」の分が空（中断ではない件）" % (WHERE_TIME, patient))
        minutes[form] += write + fix
        timed[form] += 1


def _decide(forms):
    """結論。K-21：結論の決め方：(b) か (c) を入れるのは、(a) と比べて漏れの合計が3件以上少なく、かつ1件あたりの時間の増え方が2分以内のときだけ。ただし、見立ての不同意が (a) より多い形は、この2つに当てはまっても入れない。両方入れられる形があるときは、漏れの合計が少ない方にする。どちらも当てはまらなければ結論は (a)。
    1件あたりは、表示する分（小数第1位）の値で比べる。
    戻り値：（結論。決まらないときは None）、（判断に使った差）、（決まらないときの理由）。"""
    a = forms["a"]
    detail = {}
    passed = []
    for form in ("b", "c"):
        x = forms[form]
        gain = a["漏れ"] - x["漏れ"]
        up = Decimal(x["1件あたり"]) - Decimal(a["1件あたり"])
        disagree_ok = x["見立ての不同意"] <= a["見立ての不同意"]
        ok = gain >= MIN_LEAK_GAIN and up <= MAX_MINUTES_UP and disagree_ok
        detail[form] = {
            "漏れの減り": gain,
            "1件あたりの増え": format(up, "f"),
            "見立ての不同意が(a)より多くない": disagree_ok,
            "入れられる": ok,
        }
        if ok:
            passed.append(form)
    if not passed:
        return "a", detail, ""
    if len(passed) == 1:
        return passed[0], detail, ""
    b_leak, c_leak = forms["b"]["漏れ"], forms["c"]["漏れ"]
    if b_leak == c_leak:
        return None, detail, "(b) と (c) の両方が入れられ、漏れの合計が同じで、決まりがないので結論が決まらない"
    return ("b" if b_leak < c_leak else "c"), detail, ""


def _tally(folder, warnings):
    timelog = read_workbook(os.path.join(folder, "timelog.xlsx"))
    judgments = read_workbook(os.path.join(folder, "judgments.xlsx"))
    reference = read_workbook(os.path.join(folder, "reference.xlsx"))

    patients = set()
    mapping = _symbol_map(_sheet(timelog, "記号の対応", "timelog.xlsx"), patients)
    ref = _reference(next(iter(reference.values()), []))

    fields = {f: {k: 0 for k in FIELDS} for f in FORMS}
    per_patient = {}
    _count_leaks(_sheet(judgments, "漏れ", "judgments.xlsx"), mapping, ref, fields, per_patient, patients, warnings)

    disagree = {f: 0 for f in FORMS}
    _count_disagree(_sheet(judgments, "見立て", "judgments.xlsx"), mapping, patients, disagree)

    gaps = {f: 0 for f in FORMS}
    _count_gaps(_sheet(judgments, "受け手", "judgments.xlsx"), mapping, patients, gaps)

    minutes = {f: Decimal(0) for f in FORMS}
    timed = {f: 0 for f in FORMS}
    excluded = {f: 0 for f in FORMS}
    _time_stats(_sheet(timelog, "時間", "timelog.xlsx"), mapping, patients, minutes, timed, excluded)

    if not patients:
        raise TallyError("患者が1人も見つからない")

    forms = {}
    for f in FORMS:
        if timed[f] == 0:
            raise TallyError("形 (%s) の時間の記録が、中断を除いて1件もない" % f)
        average = (minutes[f] / timed[f]).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        forms[f] = {
            "漏れ": sum(fields[f].values()),
            "欄": dict(fields[f]),
            "見立ての不同意": disagree[f],
            "1件あたり": format(average, "f"),
            "件数": timed[f],
            "中断で外した件": excluded[f],
            "受け手が気づいた欠け": gaps[f],
        }

    conclusion, detail, note = _decide(forms)
    ordered = sorted(patients)
    return {
        "ok": conclusion is not None,
        "missing": [],
        "errors": [note] if note else [],
        "warnings": warnings,
        "forms": forms,
        "patients": ordered,
        "per_patient": {p: per_patient.get(p, _zero_forms()) for p in ordered},
        "conclusion": conclusion,
        "conclusion_check": detail,
    }


def tally(ward_folder):
    """病棟のフォルダを数える。ファイルは書き換えない。"""
    missing = [name for name in REQUIRED_FILES if not os.path.isfile(os.path.join(ward_folder, name))]
    if missing:
        return {
            "ok": False,
            "missing": missing,
            "errors": ["病棟のフォルダに足りないファイルがある：" + "、".join(missing)],
            "warnings": [],
            "conclusion": None,
        }
    warnings = []
    try:
        return _tally(ward_folder, warnings)
    except TallyError as exc:
        return {"ok": False, "missing": [], "errors": [str(exc)], "warnings": warnings, "conclusion": None}


# ---------------------------------------------------------------- 報告を確かめる

FORM_NAMES = ("漏れ", "病状の重さ", "患者の要約", "すること", "気をつけること", "見立ての不同意", "受け手が気づいた欠け")


def _cells(line):
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _compare_form(match, form):
    """K-18 の行の数を、数え直しと照らす。"""
    want = [
        form["漏れ"], form["欄"]["病状の重さ"], form["欄"]["患者の要約"],
        form["欄"]["すること"], form["欄"]["気をつけること"],
        form["見立ての不同意"], form["受け手が気づいた欠け"],
    ]
    got = [int(match.group(i)) for i in (3, 4, 5, 6, 7, 8, 10)]
    problems = []
    for name, g, w in zip(FORM_NAMES, got, want):
        if g != w:
            problems.append("%s が %d（数え直しは %d）" % (name, g, w))
    if match.group(9) != form["1件あたり"]:
        problems.append("1件あたりが %s分（数え直しは %s分）" % (match.group(9), form["1件あたり"]))
    return problems


def _compare_table(lines, result):
    """患者別の表：列は 患者・(a)・(b)・(c)、患者は P-01 の形、表の数は数え直しと同じ。"""
    head = None
    for i, line in enumerate(lines):
        if line.strip().startswith("|") and _cells(line) == TABLE_HEADER:
            head = i
            break
    if head is None:
        return ["「| 患者 | (a) | (b) | (c) |」の見出しの表がない"]
    problems = []
    rows = {}
    for line in lines[head + 1:]:
        if not line.strip().startswith("|"):
            break
        cells = _cells(line)
        if all(c and set(c) <= set(":-") for c in cells):
            continue
        if len(cells) != 4 or not re.fullmatch(r"P-\d{2}", cells[0]) or not all(re.fullmatch(r"\d+", c) for c in cells[1:]):
            problems.append("表の行の形が違う（%s）" % line.strip())
            continue
        rows[cells[0]] = [int(c) for c in cells[1:]]
    for patient in sorted(set(rows) | set(result["patients"])):
        want = [result["per_patient"][patient][f] for f in FORMS] if patient in result["per_patient"] else None
        got = rows.get(patient)
        if got != want:
            problems.append("%s の漏れが %s（数え直しは %s）" % (patient, got, want))
    return problems


def check_report(ward_folder, report_path):
    """報告 compare_report.md を、数え直しと照らす。報告は書き換えない。"""
    result = tally(ward_folder)
    with open(report_path, encoding="utf-8") as handle:
        text = handle.read()
    lines = [line.rstrip() for line in text.splitlines()]
    items = []

    def add(name, problems):
        items.append({"項目": name, "合否": "不合格" if problems else "合格", "違い": "；".join(problems)})

    if not result["ok"]:
        add("数え直し", ["数え直せなかったので、報告を確かめられない（%s）" % "；".join(result["errors"] or result["missing"])])
    else:
        first = lines[0] if lines else ""
        match = CONCLUSION_RE.match(first)
        problems = []
        if not match:
            problems.append("1行目が「結論：(a)」「結論：(b)」「結論：(c)」のどれでもない（今は「%s」）" % first)
        elif match.group(1) != result["conclusion"]:
            problems.append("結論が数え直しと違う（報告は (%s)、数え直しは (%s)）" % (match.group(1), result["conclusion"]))
        add("1行目（結論）", problems)

        second = lines[1] if len(lines) > 1 else ""
        add("2行目（理由）", [] if second.startswith("理由：") else ["2行目が「理由：」で始まらない（今は「%s」）" % second])

        for form in FORMS:
            hits = []
            for line in lines:
                found = FORM_LINE_RE.match(line)
                if found and found.group(1) == form:
                    hits.append(found)
            if len(hits) != 1:
                add("(%s) の行" % form, ["(%s) の行が %d 行ある（1行のはず）" % (form, len(hits))])
            else:
                add("(%s) の行" % form, _compare_form(hits[0], result["forms"][form]))

        add("患者別の表", _compare_table(lines, result))

    all_ok = all(item["合否"] == "合格" for item in items)
    return {"合否": "合格" if all_ok else "不合格", "項目": items, "数え直し": result}


# ---------------------------------------------------------------- コマンドラインと MCP サーバー

USAGE = """使い方:
  python3 handoff_tally.py                                          MCP サーバーとして動く（標準入力と標準出力で JSON-RPC）
  python3 handoff_tally.py tally <病棟のフォルダ>                      4つのファイルを数え、結果を JSON で出す
  python3 handoff_tally.py check <病棟のフォルダ> <compare_report.md>   報告を数え直しと照らし、項目ごとの合否を JSON で出す
  python3 handoff_tally.py --help

終了コード: 0 数えられた・合格、1 数えられない・不合格（理由は JSON）、2 誤った引数、3 報告を読めない
"""

TOOLS = [
    {
        "name": "tally",
        "description": "病棟のフォルダの4つのファイル（reference.xlsx・handoffs.docx・judgments.xlsx・timelog.xlsx）から、3つの形の漏れ・見立ての不同意・受け手が気づいた欠け・1件あたりの時間を数え、結論を決める。足りないファイルがあればその名前を返す。ファイルは書き換えない。",
        "inputSchema": {
            "type": "object",
            "properties": {"ward_folder": {"type": "string", "description": "病棟のフォルダの絶対パス"}},
            "required": ["ward_folder"],
        },
    },
    {
        "name": "check_report",
        "description": "compare_report.md を、tally の数え直しと照らし、1・2行目の形、形ごとの3行の形と数、結論、患者別の表を確かめ、項目ごとの合否と違いを返す。報告は書き換えない。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ward_folder": {"type": "string", "description": "病棟のフォルダの絶対パス"},
                "report_path": {"type": "string", "description": "compare_report.md の絶対パス"},
            },
            "required": ["ward_folder", "report_path"],
        },
    },
]


def _reply(payload):
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _text_result(text, is_error=False):
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def _call_tool(name, args):
    if name == "tally":
        folder = args.get("ward_folder")
        if not isinstance(folder, str) or not folder:
            return _text_result("ward_folder（病棟のフォルダの絶対パス）が要る", True)
        result = tally(folder)
        return _text_result(json.dumps(result, ensure_ascii=False, indent=2), not result["ok"])
    if name == "check_report":
        folder = args.get("ward_folder")
        report = args.get("report_path")
        if not (isinstance(folder, str) and folder and isinstance(report, str) and report):
            return _text_result("ward_folder と report_path が要る", True)
        try:
            result = check_report(folder, report)
        except OSError as exc:
            return _text_result("報告を読めない：%s" % exc, True)
        return _text_result(json.dumps(result, ensure_ascii=False, indent=2), result["合否"] != "合格")
    return None


def serve():
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            _reply({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON として読めない"}})
            continue
        if not isinstance(msg, dict) or "id" not in msg:
            continue
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "initialize":
            result = {
                "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            try:
                result = _call_tool(params.get("name"), params.get("arguments") or {})
            except Exception as exc:  # 想定外の失敗は、ツールの失敗として返す
                result = _text_result("想定外の失敗：%s" % exc, True)
            if result is None:
                _reply({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32602, "message": "知らないツール：%s" % params.get("name")}})
                continue
        else:
            _reply({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "知らない方法：%s" % method}})
            continue
        _reply({"jsonrpc": "2.0", "id": msg["id"], "result": result})


def main(argv):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not argv:
        serve()
        return 0
    if argv == ["--help"] or argv == ["-h"]:
        print(USAGE)
        return 0
    if argv[0] == "tally" and len(argv) == 2:
        result = tally(argv[1])
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    if argv[0] == "check" and len(argv) == 3:
        try:
            result = check_report(argv[1], argv[2])
        except OSError as exc:
            print("報告を読めない：%s" % exc, file=sys.stderr)
            return 3
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["合否"] == "合格" else 1
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
