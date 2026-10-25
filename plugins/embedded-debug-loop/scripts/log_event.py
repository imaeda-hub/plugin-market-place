#!/usr/bin/env python3
"""改善用のログ（JSON Lines）に、1行足す（K-11）。

使い方：
  python3 log_event.py <ログのファイル> --iteration <番号> --pds <Plan|Do|See> --stage <工程> --role <役> --judgment <判断> [--command <実行したコマンド>] [--result <結果>]

1行の中身：time（UTC、ISO 8601）、iteration、pds、stage、role、judgment、command、result。
ログのファイルと、その上のフォルダが無ければ作る。既にある行は消さずに、後ろへ足す。
標準ライブラリだけで動く（Python 3.9 以上）。
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PDS_STAGES = ("Plan", "Do", "See")


def build_record(args):
    return {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "iteration": args.iteration,
        "pds": args.pds,
        "stage": args.stage,
        "role": args.role,
        "judgment": args.judgment,
        "command": args.command,
        "result": args.result,
    }


def main(argv):
    parser = argparse.ArgumentParser(description="改善用のログ（JSON Lines）に1行足す")
    parser.add_argument("log_file", help="ログのファイルの場所（絶対パスを推奨）")
    parser.add_argument("--iteration", type=int, required=True, help="イテレーションの番号（1以上）")
    parser.add_argument("--pds", required=True, choices=PDS_STAGES, help="PDS の段")
    parser.add_argument("--stage", required=True, help="工程")
    parser.add_argument("--role", required=True, help="役（まとめ役、ソースコード担当、ビルド・デプロイ担当、確認役）")
    parser.add_argument("--judgment", required=True, help="判断")
    parser.add_argument("--command", default="", help="実行したコマンド")
    parser.add_argument("--result", default="", help="結果")
    args = parser.parse_args(argv[1:])

    if args.iteration < 1:
        print("イテレーションの番号は1以上", file=sys.stderr)
        return 2
    for name in ("stage", "role", "judgment"):
        if not getattr(args, name).strip():
            print(f"{name} が空", file=sys.stderr)
            return 2

    path = Path(args.log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(build_record(args), ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(f"足した：{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
