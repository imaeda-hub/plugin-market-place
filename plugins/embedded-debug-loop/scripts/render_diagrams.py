#!/usr/bin/env python3
"""工程のループ図とエージェント構成の図を SVG で書き出す（K-12）。

使い方：python3 render_diagrams.py <状態のJSONファイル> <出力フォルダ>

状態のJSON（キー）：
  stage：工程。初期の対話、静的調査、ソースコード実装、ビルド、デプロイ、ログ取得、分析と次の計画、結果の出力 のどれか。
  run_state：動きの状態。動いている、人間の判断待ち、終わった のどれか。
  reason：理由。動いているときは null。
    人間の判断待ちは「成功条件の確認」「不明点の質問」（質問）か、「ビルド失敗」「デプロイ失敗」「実機が応答しない・ログが取れない」「ほかのエラー」（エラー）。
    終わったは「成功条件を達成」「上限回数に達した」「ユーザーが止めた」のどれか。
  iteration：イテレーションの番号（1以上）。まだ無いときは null。
  max_iterations：繰り返しの上限（1以上）。
  active：いま動いている AI の一覧。lead（まとめ役）、src（ソースコード担当）、build（ビルド・デプロイ担当）、check（確認役）のうち。空でもよい。

出力：<出力フォルダ>/process_loop.svg（工程のループ図）と <出力フォルダ>/agent_diagram.svg（エージェント構成の図）。
描き方は docs/diagram-mock/gen_mock.py に合わせる。色は、終わった工程＝灰、いまの工程＝青、判断待ち（質問）＝黄、判断待ち（エラー）＝赤、これから＝白。
標準ライブラリだけで動く（Python 3.9 以上）。
"""
import html
import json
import math
import sys
from pathlib import Path

STAGES = ["初期の対話", "静的調査", "ソースコード実装", "ビルド", "デプロイ", "ログ取得", "分析と次の計画", "結果の出力"]
RING = ["静的調査", "ソースコード実装", "ビルド", "デプロイ", "ログ取得", "分析と次の計画"]
RING_PDS = ["Plan", "Do", "Do", "Do", "Do", "See"]
RUN_STATES = ["動いている", "人間の判断待ち", "終わった"]
QUESTION_REASONS = ["成功条件の確認", "不明点の質問"]
ERROR_REASONS = ["ビルド失敗", "デプロイ失敗", "実機が応答しない・ログが取れない", "ほかのエラー"]
END_REASONS = ["成功条件を達成", "上限回数に達した", "ユーザーが止めた"]
AI_IDS = ["lead", "src", "build", "check"]

FONT = "'Noto Sans JP','Hiragino Sans','Meiryo','WenQuanYi Zen Hei',sans-serif"
C = {
    "ink": "#1d2733",
    "line": "#5b6b7c",
    "todo_bg": "#ffffff",
    "todo_bd": "#9aa7b4",
    "done_bg": "#e3e8ee",
    "done_tx": "#6b7886",
    "cur_bg": "#1565c0",
    "cur_tx": "#ffffff",
    "wait_bg": "#f6c343",
    "err_bg": "#d64541",
    "bg": "#f7f8fa",
    "grid": "#e9edf1",
}
STATE_STYLE = {
    "todo": (C["todo_bg"], C["todo_bd"], C["ink"], 1.5),
    "done": (C["done_bg"], C["todo_bd"], C["done_tx"], 1.5),
    "cur": (C["cur_bg"], C["cur_bg"], C["cur_tx"], 2.5),
    "wait": (C["wait_bg"], "#b8860b", C["ink"], 2.5),
    "err": (C["err_bg"], "#8e1f1c", "#ffffff", 2.5),
}


def check_state(state):
    """状態の値を確かめ、読んだ値を返す。おかしければ ValueError。"""
    if not isinstance(state, dict):
        raise ValueError("状態はJSONのオブジェクトである必要がある")
    stage = state.get("stage")
    if stage not in STAGES:
        raise ValueError(f"工程が正しくない：{stage}")
    run_state = state.get("run_state")
    if run_state not in RUN_STATES:
        raise ValueError(f"動きの状態が正しくない：{run_state}")
    reason = state.get("reason")
    if run_state == "動いている":
        if reason is not None:
            raise ValueError("動いているときは理由を書かない")
    elif run_state == "人間の判断待ち":
        if reason not in QUESTION_REASONS + ERROR_REASONS:
            raise ValueError(f"判断待ちの理由が正しくない：{reason}")
    else:
        if reason not in END_REASONS:
            raise ValueError(f"終わったときの理由が正しくない：{reason}")
    iteration = state.get("iteration")
    if iteration is not None and (isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 1):
        raise ValueError(f"イテレーションの番号が正しくない：{iteration}")
    maximum = state.get("max_iterations")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise ValueError(f"繰り返しの上限が正しくない：{maximum}")
    active = state.get("active", [])
    if not isinstance(active, list) or any(item not in AI_IDS for item in active):
        raise ValueError(f"いま動いている AI が正しくない：{active}")
    return stage, run_state, reason, iteration, maximum, active


def stage_states(stage, run_state, reason):
    """各工程の状態（done、cur、wait、err、todo）を返す。"""
    index = STAGES.index(stage)
    result = {}
    for i, name in enumerate(STAGES):
        if run_state == "終わった" or i < index:
            style = "done"
        elif i > index:
            style = "todo"
        elif run_state == "動いている":
            style = "cur"
        elif reason in QUESTION_REASONS:
            style = "wait"
        else:
            style = "err"
        result[name] = style
    return result


def head(width, height):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="{FONT}">\n'
        '<defs>'
        f'<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{C["line"]}"/></marker>'
        f'<marker id="arb" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{C["cur_bg"]}"/></marker>'
        f'<pattern id="g" width="20" height="20" patternUnits="userSpaceOnUse">'
        f'<path d="M20 0 L0 0 0 20" fill="none" stroke="{C["grid"]}" stroke-width="1"/></pattern>'
        '</defs>\n'
        f'<rect width="{width}" height="{height}" fill="{C["bg"]}"/><rect width="{width}" height="{height}" fill="url(#g)"/>\n'
    )


def box(x, y, w, h, label, state="todo", sub=None, r=4):
    bg, border, text_color, stroke = STATE_STYLE[state]
    label = html.escape(label)
    s = (f'<rect x="{x - w / 2}" y="{y - h / 2}" width="{w}" height="{h}" rx="{r}" fill="{bg}" '
         f'stroke="{border}" stroke-width="{stroke}"/>')
    if sub:
        s += (f'<text x="{x}" y="{y - 3}" text-anchor="middle" font-size="14" font-weight="700" '
              f'fill="{text_color}">{label}</text>')
        s += (f'<text x="{x}" y="{y + 14}" text-anchor="middle" font-size="11" fill="{text_color}">'
              f'{html.escape(sub)}</text>')
    else:
        s += (f'<text x="{x}" y="{y + 5}" text-anchor="middle" font-size="14" font-weight="700" '
              f'fill="{text_color}">{label}</text>')
    return s + "\n"


def arrow(x1, y1, x2, y2, label=None, dx=0, dy=-6, color=None, dash=False, anchor="middle"):
    marker = "arb" if color else "ar"
    col = color or C["line"]
    dash_attr = ' stroke-dasharray="6 4"' if dash else ""
    s = (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" stroke-width="1.8"{dash_attr} '
         f'marker-end="url(#{marker})"/>')
    if label:
        s += (f'<text x="{(x1 + x2) / 2 + dx}" y="{(y1 + y2) / 2 + dy}" text-anchor="{anchor}" font-size="11.5" '
              f'fill="{C["ink"]}">{html.escape(label)}</text>')
    return s + "\n"


def legend(x, y, items):
    s = ""
    for i, (style, text) in enumerate(items):
        s += box(x + i * 128 + 14, y, 22, 16, "", style, r=3)
        s += f'<text x="{x + i * 128 + 32}" y="{y + 5}" font-size="12" fill="{C["ink"]}">{html.escape(text)}</text>\n'
    return s


LOOP_LEGEND = [("done", "終わった工程"), ("cur", "いまの工程"), ("wait", "判断待ち（質問）"),
               ("err", "判断待ち（エラー）"), ("todo", "これから")]


def loop_svg(states, iteration, maximum, run_state, reason):
    width, height = 960, 600
    cx, cy, radius = 520, 300, 185
    angles = [-90, -30, 30, 90, 150, 210]
    ring_states = [states[name] for name in RING]
    s = head(width, height)
    s += f'<text x="24" y="34" font-size="18" font-weight="700" fill="{C["ink"]}">工程のループ図</text>\n'
    s += (f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{C["todo_bd"]}" stroke-width="1" '
          f'stroke-dasharray="2 5"/>\n')
    for i in range(6):
        a1 = math.radians(angles[i] + 17)
        a2 = math.radians(angles[(i + 1) % 6] - 17)
        x1, y1 = cx + radius * math.cos(a1), cy + radius * math.sin(a1)
        x2, y2 = cx + radius * math.cos(a2), cy + radius * math.sin(a2)
        lit = ring_states[i] == "done" and ring_states[(i + 1) % 6] in ("cur", "wait", "err")
        col = C["cur_bg"] if lit else C["line"]
        marker = "arb" if lit else "ar"
        s += (f'<path d="M{x1:.1f},{y1:.1f} A{radius},{radius} 0 0 1 {x2:.1f},{y2:.1f}" fill="none" '
              f'stroke="{col}" stroke-width="2.2" marker-end="url(#{marker})"/>\n')
    for i, name in enumerate(RING):
        a = math.radians(angles[i])
        x, y = cx + radius * math.cos(a), cy + radius * math.sin(a)
        s += box(x, y, 150, 50, name, ring_states[i], sub=RING_PDS[i])
    number = f"{iteration} / {maximum}" if iteration else "—"
    chip = {"動いている": C["cur_bg"], "人間の判断待ち": C["wait_bg"], "終わった": C["line"]}[run_state]
    chip_text = C["ink"] if run_state == "人間の判断待ち" else "#ffffff"
    s += f'<text x="{cx}" y="{cy - 30}" text-anchor="middle" font-size="13" fill="{C["done_tx"]}">Iteration</text>\n'
    s += (f'<text x="{cx}" y="{cy + 8}" text-anchor="middle" font-size="34" font-weight="700" '
          f'fill="{C["ink"]}">{html.escape(number)}</text>\n')
    s += f'<rect x="{cx - 70}" y="{cy + 22}" width="140" height="26" rx="13" fill="{chip}"/>'
    s += (f'<text x="{cx}" y="{cy + 40}" text-anchor="middle" font-size="13" font-weight="700" '
          f'fill="{chip_text}">{run_state}</text>\n')
    if reason:
        s += (f'<text x="{cx}" y="{cy + 68}" text-anchor="middle" font-size="12" fill="{C["ink"]}">'
              f'理由：{html.escape(reason)}</text>\n')
    s += box(130, 110, 150, 46, "初期の対話", states["初期の対話"], sub="成功条件・制約の確認")
    s += arrow(205, 110, cx - 78, cy - radius - 4, "材料がそろったら", dy=-8)
    s += box(130, 480, 150, 46, "結果の出力", states["結果の出力"], sub="結論・PDSの表")
    a = math.radians(210)
    s += arrow(cx + radius * math.cos(a) - 40, cy + radius * math.sin(a) + 26, 150, 455,
               "終了条件（成功／上限／停止）", dx=-12, dy=0, dash=True, anchor="end")
    s += legend(220, 570, LOOP_LEGEND)
    return s + "</svg>\n"


def agent_svg(active):
    width, height = 960, 620
    s = head(width, height)
    s += f'<text x="24" y="34" font-size="18" font-weight="700" fill="{C["ink"]}">エージェント構成</text>\n'

    def style(ai):
        return "cur" if ai in active else "todo"

    def link(*ais):
        return C["cur_bg"] if any(ai in active for ai in ais) else None

    s += box(480, 90, 200, 50, "人間（利用者）", "todo", sub="調査プロンプト・判断")
    s += box(480, 290, 220, 64, "まとめ役の AI", style("lead"), sub="Plan・See／ループの管理")
    s += box(160, 290, 200, 60, "ソースコード担当", style("src"), sub="静的調査・修正・ログ追加")
    s += box(800, 290, 210, 60, "ビルド・デプロイ担当", style("build"), sub="ビルド・デプロイ・ログ取得")
    s += box(480, 490, 200, 56, "確認役の AI", style("check"), sub="合格の条件で評価")
    s += box(160, 490, 200, 50, "ソースコード", "done", sub="ローカルPC（C/C++）")
    s += box(800, 490, 200, 50, "実機", "done", sub="シェルコンソール")
    for x, y, text in [(160, 170, "ログ追加のルール"), (730, 170, "クロスコンパイルのルール"), (880, 170, "デプロイのルール")]:
        s += (f'<rect x="{x - 70}" y="{y - 16}" width="140" height="32" rx="2" fill="#fffbe6" stroke="#b8860b" '
              f'stroke-dasharray="4 3"/><text x="{x}" y="{y + 5}" text-anchor="middle" font-size="12" '
              f'fill="{C["ink"]}">{text}</text>\n')
    s += arrow(160, 186, 160, 258, "従う", dx=18, dy=4, color=link("src"))
    s += arrow(730, 186, 770, 258, color=link("build"))
    s += arrow(880, 186, 840, 258, color=link("build"))
    s += f'<text x="805" y="225" text-anchor="middle" font-size="11.5" fill="{C["ink"]}">従う</text>\n'
    s += (f'<text x="810" y="140" text-anchor="middle" font-size="11" fill="#8a6d00">'
          f'利用者が書き換えるルール（プラグインの中の部品）</text>\n')
    s += arrow(460, 116, 460, 256, "プロンプト・判断", dx=-8, dy=0, anchor="end", color=link("lead"))
    s += arrow(500, 256, 500, 116, "質問・エラー報告", dx=8, dy=0, anchor="start", color=link("lead"))
    s += arrow(368, 278, 262, 278, "Plan（調べる・直すこと）", dy=-8, color=link("lead", "src"))
    s += arrow(262, 304, 368, 304, "調査結果・差分", dy=18, color=link("lead", "src"))
    s += arrow(592, 278, 693, 278, "ビルド・デプロイの指示", dy=-8, color=link("lead", "build"))
    s += arrow(693, 304, 592, 304, "結果・ログ", dy=18, color=link("lead", "build"))
    s += arrow(470, 324, 470, 460, "成果物", dx=-8, dy=0, anchor="end", color=link("lead", "check"))
    s += arrow(490, 460, 490, 324, "評価（See）", dx=8, dy=0, anchor="start", color=link("lead", "check"))
    s += arrow(150, 322, 150, 463, "読む", dx=-8, dy=0, anchor="end", color=link("src"))
    s += arrow(170, 322, 170, 463, "修正", dx=8, dy=0, anchor="start", color=link("src"))
    s += arrow(790, 322, 790, 463, "モジュール転送", dx=-8, dy=0, anchor="end", color=link("build"))
    s += arrow(810, 463, 810, 322, "ログ", dx=8, dy=0, anchor="start", color=link("build"))
    agent_legend = [("done", "対象"), ("cur", "いま動いている AI"), ("wait", "判断待ち（質問）"),
                    ("err", "判断待ち（エラー）"), ("todo", "これから")]
    s += legend(220, 590, agent_legend)
    return s + "</svg>\n"


def main(argv):
    if len(argv) != 3:
        print("使い方：python3 render_diagrams.py <状態のJSONファイル> <出力フォルダ>", file=sys.stderr)
        return 2
    try:
        state = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        stage, run_state, reason, iteration, maximum, active = check_state(state)
    except (OSError, ValueError) as error:
        print(f"状態が正しくない：{error}", file=sys.stderr)
        return 2
    out = Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    states = stage_states(stage, run_state, reason)
    (out / "process_loop.svg").write_text(loop_svg(states, iteration, maximum, run_state, reason), encoding="utf-8")
    (out / "agent_diagram.svg").write_text(agent_svg(active), encoding="utf-8")
    print(f"書いた：{out / 'process_loop.svg'}")
    print(f"書いた：{out / 'agent_diagram.svg'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
