#!/usr/bin/env python3
"""ng-data の MCP サーバー（標準ライブラリだけ。stdio で JSON-RPC を話す）。

ツール extract_ng: 試験結果（results.xlsx）と試験仕様書（spec.docx）を読み、
結果の行、凡例、仕様書の行、NG の行（項目IDで仕様書とつないだもの）を JSON で返す。
ファイルは書き換えない。機能名のまとめと、項目を選ぶ判断はしない（AI がナレッジで行う）。
"""
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

SEP = "、"
KANSO = "恒温槽"
RESULT_SHEET = "結果"
LEGEND_SHEET = "凡例"
RESULT_REQUIRED = ["項目ID", "判定"]
RESULT_FIELDS = ["項目ID", "項目名", "判定", "備考"]
SPEC_REQUIRED = ["項目ID", "機能", "前提条件"]
KNOWN_JUDGEMENTS = ("OK", "NG", "保留", "")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def text_of(el):
    """要素の中の文字（t 要素の文字）を集める。ふりがな（rPh）は除く。"""
    parts = []

    def walk(e):
        for c in e:
            name = local(c.tag)
            if name == "rPh":
                continue
            if name == "t":
                parts.append(c.text or "")
            else:
                walk(c)

    walk(el)
    return "".join(parts)


def col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n - 1


def read_xml(zf, name):
    try:
        with zf.open(name) as f:
            return ET.parse(f).getroot()
    except KeyError:
        raise ValueError("ファイルの中に %s がありません" % name)


def resolve(base, target):
    if target.startswith("/"):
        return target[1:]
    out = []
    for part in (base + target).split("/"):
        if part == "..":
            if out:
                out.pop()
        elif part not in ("", "."):
            out.append(part)
    return "/".join(out)


# ---- results.xlsx ----

def shared_strings(zf):
    try:
        root = read_xml(zf, "xl/sharedStrings.xml")
    except ValueError:
        return []
    return [text_of(si) for si in root if local(si.tag) == "si"]


def sheet_paths(zf):
    wb = read_xml(zf, "xl/workbook.xml")
    rels = read_xml(zf, "xl/_rels/workbook.xml.rels")
    targets = {r.get("Id"): r.get("Target") for r in rels if local(r.tag) == "Relationship"}
    paths = {}
    for s in wb.iter():
        if local(s.tag) != "sheet":
            continue
        rid = None
        for k, v in s.attrib.items():
            if local(k) == "id":
                rid = v
        if rid not in targets:
            raise ValueError("シート %s の場所が分かりません" % s.get("name"))
        paths[s.get("name")] = resolve("xl/", targets[rid])
    return paths


def cell_value(c, shared):
    kind = c.get("t", "")
    if kind == "inlineStr":
        for x in c:
            if local(x.tag) == "is":
                return text_of(x)
        return ""
    for x in c:
        if local(x.tag) == "v":
            if x.text is None:
                return ""
            if kind == "s":
                return shared[int(x.text)]
            return x.text
    return ""


def sheet_rows(zf, path, shared):
    root = read_xml(zf, path)
    rows = []
    for row in root.iter():
        if local(row.tag) != "row":
            continue
        values = {}
        pos = 0
        for c in row:
            if local(c.tag) != "c":
                continue
            ref = c.get("r")
            idx = col_index(ref) if ref else pos
            values[idx] = cell_value(c, shared)
            pos = idx + 1
        width = max(values) + 1 if values else 0
        rows.append([values.get(i, "") for i in range(width)])
    return rows


# ---- 表の共通の読み方（xlsx の行、docx の表の行の両方） ----

def table(rows, required):
    """required の見出しをすべて含む行を探し、その下の行を辞書にする。なければ None。"""
    for i, row in enumerate(rows):
        heads = [h.strip() for h in row]
        if all(name in heads for name in required):
            out = []
            for r in rows[i + 1:]:
                vals = [v.strip() for v in r]
                if not any(vals):
                    continue
                rec = {}
                for j, h in enumerate(heads):
                    if h and h not in rec:
                        rec[h] = vals[j] if j < len(vals) else ""
                out.append(rec)
            return out
    return None


# ---- spec.docx ----

def docx_tables(zf):
    root = read_xml(zf, "word/document.xml")
    tables = []
    for tbl in root.iter():
        if local(tbl.tag) != "tbl":
            continue
        rows = []
        for tr in tbl:
            if local(tr.tag) != "tr":
                continue
            cells = []
            for tc in tr:
                if local(tc.tag) != "tc":
                    continue
                paras = [text_of(p) for p in tc if local(p.tag) == "p"]
                cells.append("\n".join(paras))
            rows.append(cells)
        tables.append(rows)
    return tables


def prereq_list(text):
    return [p.strip() for p in text.split(SEP) if p.strip()]


# ---- 本体 ----

def extract_ng(results_path, spec_path):
    warnings = []

    with zipfile.ZipFile(results_path) as zf:
        shared = shared_strings(zf)
        paths = sheet_paths(zf)
        missing = [n for n in (RESULT_SHEET, LEGEND_SHEET) if n not in paths]
        if missing:
            raise ValueError("results.xlsx に %s のシートがありません（シート: %s）"
                             % ("、".join(missing), "、".join(paths)))
        result_rows = sheet_rows(zf, paths[RESULT_SHEET], shared)
        legend_rows = sheet_rows(zf, paths[LEGEND_SHEET], shared)

    results_raw = table(result_rows, RESULT_REQUIRED)
    if results_raw is None:
        raise ValueError("「結果」のシートに、見出し（項目ID・判定）の行がありません")
    results = [{k: r.get(k, "") for k in RESULT_FIELDS} for r in results_raw]

    unknown = sorted({r["判定"] for r in results if r["判定"] not in KNOWN_JUDGEMENTS})
    if unknown:
        warnings.append("想定していない判定の値があります: " + "、".join(unknown))

    spec_raw = []
    with zipfile.ZipFile(spec_path) as zf:
        for rows in docx_tables(zf):
            found = table(rows, SPEC_REQUIRED)
            if found is not None:
                spec_raw.extend(found)
    if not spec_raw:
        raise ValueError("spec.docx に 項目ID・機能・前提条件 の見出しの表がありません")

    spec = []
    for r in spec_raw:
        pre = r.get("前提条件", "")
        items = prereq_list(pre)
        spec.append({
            "項目ID": r.get("項目ID", ""),
            "機能": r.get("機能", ""),
            "前提条件": pre,
            "前提条件一覧": items,
            "前提条件の数": len(items),
            "恒温槽を含む": KANSO in pre,
        })

    id_count = {}
    by_id = {}
    for s in spec:
        id_count[s["項目ID"]] = id_count.get(s["項目ID"], 0) + 1
        by_id.setdefault(s["項目ID"], s)
    for pid, n in id_count.items():
        if n > 1:
            warnings.append("仕様書に項目ID %s が %d 件あります（最初の行を使いました）" % (pid, n))

    ng = []
    for r in results:
        if r["判定"] != "NG":
            continue
        s = by_id.get(r["項目ID"])
        if s is None:
            warnings.append("NG の項目ID %s が仕様書にありません" % r["項目ID"])
        ng.append({
            "項目ID": r["項目ID"],
            "項目名": r["項目名"],
            "判定": r["判定"],
            "備考": r["備考"],
            "仕様書に該当": s is not None,
            "機能": s["機能"] if s else None,
            "前提条件": s["前提条件"] if s else None,
            "前提条件一覧": s["前提条件一覧"] if s else None,
            "前提条件の数": s["前提条件の数"] if s else None,
            "恒温槽を含む": s["恒温槽を含む"] if s else None,
        })

    return {
        "結果": results,
        "凡例": [row for row in legend_rows if any(c.strip() for c in row)],
        "仕様書": spec,
        "NG": ng,
        "注意": warnings,
    }


# ---- MCP（stdio、1行に1つの JSON-RPC） ----

PROTOCOL = "2024-11-05"
TOOL = {
    "name": "extract_ng",
    "description": "試験結果 results.xlsx と試験仕様書 spec.docx を読み、結果の行、凡例、仕様書の行、NG の行（仕様書とつないだもの）を返す。ファイルは書き換えない。",
    "inputSchema": {
        "type": "object",
        "properties": {
            "results_path": {"type": "string", "description": "results.xlsx の絶対パス"},
            "spec_path": {"type": "string", "description": "spec.docx の絶対パス"},
        },
        "required": ["results_path", "spec_path"],
    },
}


def ok(mid, result):
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def err(mid, code, message):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def handle(msg):
    mid = msg.get("id")
    method = msg.get("method")
    if mid is None:
        return None  # 通知（notifications/initialized など）には返さない
    if method == "initialize":
        ver = (msg.get("params") or {}).get("protocolVersion", PROTOCOL)
        return ok(mid, {
            "protocolVersion": ver,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "ng-data", "version": "1.0.0"},
        })
    if method == "ping":
        return ok(mid, {})
    if method == "tools/list":
        return ok(mid, {"tools": [TOOL]})
    if method == "tools/call":
        params = msg.get("params") or {}
        if params.get("name") != "extract_ng":
            return err(mid, -32602, "unknown tool: %s" % params.get("name"))
        args = params.get("arguments") or {}
        for key in ("results_path", "spec_path"):
            if not args.get(key):
                return ok(mid, {"content": [{"type": "text", "text": "エラー: %s が必要です" % key}], "isError": True})
        try:
            data = extract_ng(args["results_path"], args["spec_path"])
            text = json.dumps(data, ensure_ascii=False, indent=2)
            return ok(mid, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:  # 読めないときは、理由を返す
            return ok(mid, {"content": [{"type": "text", "text": "エラー: %s" % e}], "isError": True})
    return err(mid, -32601, "method not found: %s" % method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = err(None, -32700, "parse error")
        else:
            resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
