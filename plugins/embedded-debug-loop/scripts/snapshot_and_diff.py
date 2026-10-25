#!/usr/bin/env python3
"""ソースコードのフォルダの写しを取り、変えた差分（unified diff）のファイルを作る。

使い方：
  python3 snapshot_and_diff.py snapshot <ソースのフォルダ> <写しのフォルダ>
      写しがまだ無ければ取る。あれば何もしない（変える前に1回だけ取るため）。
  python3 snapshot_and_diff.py diff <ソースのフォルダ> <写しのフォルダ> <差分のファイル>
      写しと今のソースの差分を、差分のファイルに書く。変えていなければ空のファイルになる。

.git のフォルダは対象にしない。標準ライブラリだけで動く（Python 3.9 以上）。
"""
import difflib
import shutil
import sys
from pathlib import Path

IGNORE = {".git"}


def list_files(root):
    """相対パス（/ 区切り）から実際のファイルへの対応を返す。"""
    result = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in IGNORE for part in rel.parts):
            continue
        result[rel.as_posix()] = path
    return result


def snapshot(src, dst):
    if not src.is_dir():
        return 2, f"ソースのフォルダがない：{src}"
    if dst.exists():
        return 0, "写しは既にあるので取らない"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*IGNORE))
    return 0, f"写しを取った：{len(list_files(dst))} ファイル"


def diff(src, dst, out):
    if not src.is_dir():
        return 2, f"ソースのフォルダがない：{src}"
    if not dst.is_dir():
        return 2, f"写しのフォルダがない：{dst}"
    old_files = list_files(dst)
    new_files = list_files(src)
    chunks = []
    for rel in sorted(set(old_files) | set(new_files)):
        old = old_files[rel].read_bytes() if rel in old_files else None
        new = new_files[rel].read_bytes() if rel in new_files else None
        if old == new:
            continue
        if (old is not None and b"\0" in old) or (new is not None and b"\0" in new):
            chunks.append(f"Binary files a/{rel} and b/{rel} differ\n")
            continue
        old_lines = old.decode("utf-8", "replace").splitlines(keepends=True) if old is not None else []
        new_lines = new.decode("utf-8", "replace").splitlines(keepends=True) if new is not None else []
        from_name = f"a/{rel}" if old is not None else "/dev/null"
        to_name = f"b/{rel}" if new is not None else "/dev/null"
        for line in difflib.unified_diff(old_lines, new_lines, fromfile=from_name, tofile=to_name):
            chunks.append(line if line.endswith("\n") else line + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(chunks), encoding="utf-8")
    changed = sum(1 for chunk in chunks if chunk.startswith("--- "))
    return 0, f"差分を書いた：{out}（変えたファイル {changed} 件）"


def main(argv):
    usage = ("使い方：\n"
             "  python3 snapshot_and_diff.py snapshot <ソースのフォルダ> <写しのフォルダ>\n"
             "  python3 snapshot_and_diff.py diff <ソースのフォルダ> <写しのフォルダ> <差分のファイル>")
    if len(argv) >= 2 and argv[1] == "snapshot" and len(argv) == 4:
        code, message = snapshot(Path(argv[2]), Path(argv[3]))
    elif len(argv) >= 2 and argv[1] == "diff" and len(argv) == 5:
        code, message = diff(Path(argv[2]), Path(argv[3]), Path(argv[4]))
    else:
        print(usage, file=sys.stderr)
        return 2
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
