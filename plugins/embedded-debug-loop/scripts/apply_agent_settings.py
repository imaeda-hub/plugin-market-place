#!/usr/bin/env python3
"""作業を始めるとき、画面で選んだエフォートレベルを各エージェントの定義に書き込む（K-17）。

使い方：python3 apply_agent_settings.py <エージェントのフォルダ> <設定のJSONファイル>

- 設定のJSONは {"effort_orchestrator": "...", "effort_worker": "...", "effort_worker_b": "...", "effort_verifier": "..."} の形。
  キーが無いエージェントは書き換えない。
- 値は「既定のまま」「low」「medium」「high」のどれか。「既定のまま」なら reasoningEffort の行を消す。
- モデル（model）は書き換えない。モデルの扱いは、ひな形の共通の仕組みに任せる。
- 値が1つでも正しくないときは、どのファイルも書き換えずに終わる。
- 標準ライブラリだけで動く（Python 3.9 以上）。
"""
import json
import sys
from pathlib import Path

EFFORT_FILES = {
    "effort_orchestrator": "orchestrator.agent.md",
    "effort_worker": "worker.agent.md",
    "effort_worker_b": "worker-b.agent.md",
    "effort_verifier": "verifier.agent.md",
}
DEFAULT = "既定のまま"
VALID_VALUES = (DEFAULT, "low", "medium", "high")


def apply_effort(text, effort):
    """フロントマターの reasoningEffort を書き換えた文を返す。フロントマターが無ければ ValueError。"""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise ValueError("フロントマターがない")
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        raise ValueError("フロントマターが閉じていない")
    front = [line for line in lines[1:end] if not line.startswith("reasoningEffort:")]
    if effort != DEFAULT:
        front.append(f"reasoningEffort: {effort}")
    return "\n".join([lines[0]] + front + lines[end:])


def main(argv):
    if len(argv) != 3:
        print("使い方：python3 apply_agent_settings.py <エージェントのフォルダ> <設定のJSONファイル>", file=sys.stderr)
        return 2
    agents_dir = Path(argv[1])
    try:
        settings = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"設定を読めない：{error}", file=sys.stderr)
        return 2
    if not isinstance(settings, dict):
        print("設定はキーと値の組のJSONである必要がある", file=sys.stderr)
        return 2

    # まず全部を確かめ、そのあとで書く。
    planned = []
    for key, filename in EFFORT_FILES.items():
        if key not in settings:
            continue
        value = settings[key]
        if value not in VALID_VALUES:
            print(f"{key} の値が正しくない：{value}", file=sys.stderr)
            return 2
        path = agents_dir / filename
        if not path.is_file():
            print(f"エージェントの定義がない：{path}", file=sys.stderr)
            return 2
        try:
            new_text = apply_effort(path.read_text(encoding="utf-8"), value)
        except ValueError as error:
            print(f"{path.name}：{error}", file=sys.stderr)
            return 2
        planned.append((path, value, new_text))

    for path, value, new_text in planned:
        path.write_text(new_text, encoding="utf-8")
    if planned:
        for path, value, _ in planned:
            print(f"{path.name}: reasoningEffort = {value}")
    else:
        print("変えたものはない")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
