#!/usr/bin/env python3
"""売上データの CSV（列は 日付・担当・金額）を読み、担当ごとの金額と合計を JSON で出す。

- 担当ごとに、その担当の円を足す。万円は1万円未満を切り捨てる（K-07）。
  1万円に満たない担当の表記は「1万円未満」（K-08）。
- 合計は、全行の円を足してから万円に切り捨てる（K-09、K-21）。担当ごとの万円を足さない。
- 金額は、桁区切りのカンマや「円」などを除いて整数として読む（K-12）。
- 読めない行（列が足りない、担当が空欄、金額が整数に読めない）があれば止め、
  その行を標準エラー出力に書いて終了コード 2 で終わる。行を勝手に飛ばさない。
- 1行目が「日付,担当,金額」なら見出しとして読み飛ばす。完全に空の行は数えない。
- 標準ライブラリだけを使う。

使い方：python3 sum_sales.py <売上データ CSV の絶対パス>
"""

import csv
import json
import sys

HEADER = ["日付", "担当", "金額"]
# 金額から取り除く文字（桁区切り、全角のカンマ、空白、単位）
STRIP_CHARS = [",", "，", " ", "　", "円"]


class RowError(Exception):
    def __init__(self, lineno, cells, reason):
        super().__init__(reason)
        self.lineno = lineno
        self.cells = cells
        self.reason = reason


def man_label(man):
    """万円の数を表示の文字にする。1万円未満は「1万円未満」（K-08）。"""
    if man == 0:
        return "1万円未満"
    return f"{man}万円"


def parse_amount(text):
    s = text
    for ch in STRIP_CHARS:
        s = s.replace(ch, "")
    return int(s)  # 読めないときは ValueError


def read_records(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        text = f.read()
    reader = csv.reader(text.splitlines())
    records = []
    for lineno, cells in enumerate(reader, start=1):
        cells = [c.strip() for c in cells]
        if all(c == "" for c in cells):
            continue
        if lineno == 1 and cells == HEADER:
            continue
        records.append((lineno, cells))
    return records


def read_rows(path):
    rows = []
    for lineno, cells in read_records(path):
        if len(cells) < 3:
            raise RowError(lineno, cells, "列が3つ（日付・担当・金額）に足りない")
        date = cells[0]
        name = cells[1]
        # 桁区切りのカンマが囲みなしで入ると列が割れるので、3列目以降を金額として結ぶ
        amount_text = ",".join(cells[2:])
        if name == "":
            raise RowError(lineno, cells, "担当が空欄")
        if amount_text.strip() == "":
            raise RowError(lineno, cells, "金額が空欄")
        try:
            amount = parse_amount(amount_text)
        except ValueError:
            raise RowError(lineno, cells, "金額を整数として読めない")
        rows.append((lineno, date, name, amount))
    return rows


def summarize(rows):
    order = []
    yen_by_name = {}
    for _, _date, name, amount in rows:
        if name not in yen_by_name:
            order.append(name)
            yen_by_name[name] = 0
        yen_by_name[name] += amount

    people = []
    for name in order:
        yen = yen_by_name[name]
        man = yen // 10000
        people.append({"name": name, "yen": yen, "man": man, "label": man_label(man)})

    total_yen = sum(yen_by_name.values())
    total_man = total_yen // 10000
    return {
        "rows": len(rows),
        "people": people,
        "total_yen": total_yen,
        "total_man": total_man,
        "total_label": man_label(total_man),
    }


def main(argv):
    if len(argv) != 2:
        print("使い方：python3 sum_sales.py <売上データ CSV の絶対パス>", file=sys.stderr)
        return 1
    path = argv[1]
    try:
        rows = read_rows(path)
    except RowError as e:
        line = ",".join(e.cells)
        print(
            f"読めない行があるため止めました：{e.lineno} 行目「{line}」（{e.reason}）",
            file=sys.stderr,
        )
        return 2
    except UnicodeDecodeError:
        print("売上データを UTF-8 として読めない", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"売上データを開けない：{e}", file=sys.stderr)
        return 2
    if not rows:
        print("売上の行がない", file=sys.stderr)
        return 2
    print(json.dumps(summarize(rows), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
