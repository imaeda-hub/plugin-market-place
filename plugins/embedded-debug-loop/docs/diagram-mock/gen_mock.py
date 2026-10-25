"""作る前の確認で見せる、工程のループ図とエージェント構成の図の見本（SVG）を作る。"""
import math
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
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


def head(w, h):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'font-family="{FONT}">\n'
        '<defs>'
        f'<marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{C["line"]}"/></marker>'
        f'<marker id="arb" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{C["cur_bg"]}"/></marker>'
        f'<pattern id="g" width="20" height="20" patternUnits="userSpaceOnUse">'
        f'<path d="M20 0 L0 0 0 20" fill="none" stroke="{C["grid"]}" stroke-width="1"/></pattern>'
        '</defs>\n'
        f'<rect width="{w}" height="{h}" fill="{C["bg"]}"/><rect width="{w}" height="{h}" fill="url(#g)"/>\n'
    )


def box(x, y, w, h, label, state="todo", sub=None, r=4):
    bg, bd, tx, sw = {
        "todo": (C["todo_bg"], C["todo_bd"], C["ink"], 1.5),
        "done": (C["done_bg"], C["todo_bd"], C["done_tx"], 1.5),
        "cur": (C["cur_bg"], C["cur_bg"], C["cur_tx"], 2.5),
        "wait": (C["wait_bg"], "#b8860b", C["ink"], 2.5),
        "err": (C["err_bg"], "#8e1f1c", "#ffffff", 2.5),
    }[state]
    s = f'<rect x="{x-w/2}" y="{y-h/2}" width="{w}" height="{h}" rx="{r}" fill="{bg}" stroke="{bd}" stroke-width="{sw}"/>'
    if sub:
        s += f'<text x="{x}" y="{y-3}" text-anchor="middle" font-size="14" font-weight="700" fill="{tx}">{label}</text>'
        s += f'<text x="{x}" y="{y+14}" text-anchor="middle" font-size="11" fill="{tx}">{sub}</text>'
    else:
        s += f'<text x="{x}" y="{y+5}" text-anchor="middle" font-size="14" font-weight="700" fill="{tx}">{label}</text>'
    return s + "\n"


def arrow(x1, y1, x2, y2, label=None, dx=0, dy=-6, color=None, dash=False, anchor="middle"):
    m = "arb" if color else "ar"
    col = color or C["line"]
    d = ' stroke-dasharray="6 4"' if dash else ""
    s = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" stroke-width="1.8"{d} marker-end="url(#{m})"/>'
    if label:
        s += (f'<text x="{(x1+x2)/2+dx}" y="{(y1+y2)/2+dy}" text-anchor="{anchor}" font-size="11.5" '
              f'fill="{C["ink"]}">{label}</text>')
    return s + "\n"


def legend(x, y):
    items = [("done", "終わった工程"), ("cur", "いまの工程"), ("wait", "判断待ち（質問）"), ("err", "判断待ち（エラー）"), ("todo", "これから")]
    s = ""
    for i, (st, t) in enumerate(items):
        s += box(x + i * 128 + 14, y, 22, 16, "", st, r=3)
        s += f'<text x="{x + i*128 + 32}" y="{y+5}" font-size="12" fill="{C["ink"]}">{t}</text>\n'
    return s


def loop_svg(states, iteration, status, reason, title):
    W, H = 960, 600
    cx, cy, R = 520, 300, 185
    steps = ["静的調査", "ソースコード実装", "ビルド", "デプロイ", "ログ取得", "分析と次の計画"]
    pds = ["Plan", "Do", "Do", "Do", "Do", "See"]
    angles = [-90, -30, 30, 90, 150, 210]
    s = head(W, H)
    s += f'<text x="24" y="34" font-size="18" font-weight="700" fill="{C["ink"]}">{title}</text>\n'
    # ループの輪
    s += f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="{C["todo_bd"]}" stroke-width="1" stroke-dasharray="2 5"/>\n'
    for i in range(6):
        a1 = math.radians(angles[i] + 17)
        a2 = math.radians(angles[(i + 1) % 6] - 17)
        x1, y1 = cx + R * math.cos(a1), cy + R * math.sin(a1)
        x2, y2 = cx + R * math.cos(a2), cy + R * math.sin(a2)
        col = C["cur_bg"] if states[i] == "done" and states[(i + 1) % 6] in ("cur", "wait", "err") else C["line"]
        m = "arb" if col == C["cur_bg"] else "ar"
        s += (f'<path d="M{x1:.1f},{y1:.1f} A{R},{R} 0 0 1 {x2:.1f},{y2:.1f}" fill="none" stroke="{col}" '
              f'stroke-width="2.2" marker-end="url(#{m})"/>\n')
    for i, name in enumerate(steps):
        a = math.radians(angles[i])
        x, y = cx + R * math.cos(a), cy + R * math.sin(a)
        s += box(x, y, 150, 50, name, states[i], sub=pds[i])
    # 中央：イテレーションと状態
    s += f'<text x="{cx}" y="{cy-30}" text-anchor="middle" font-size="13" fill="{C["done_tx"]}">Iteration</text>\n'
    s += f'<text x="{cx}" y="{cy+8}" text-anchor="middle" font-size="34" font-weight="700" fill="{C["ink"]}">{iteration}</text>\n'
    chip = {"動いている": C["cur_bg"], "人間の判断待ち": C["wait_bg"], "終わった": C["line"]}[status]
    chip_tx = C["ink"] if status == "人間の判断待ち" else "#ffffff"
    s += f'<rect x="{cx-70}" y="{cy+22}" width="140" height="26" rx="13" fill="{chip}"/>'
    s += f'<text x="{cx}" y="{cy+40}" text-anchor="middle" font-size="13" font-weight="700" fill="{chip_tx}">{status}</text>\n'
    if reason:
        s += f'<text x="{cx}" y="{cy+68}" text-anchor="middle" font-size="12" fill="{C["ink"]}">理由：{reason}</text>\n'
    # 入口と出口
    s += box(130, 110, 150, 46, "初期の対話", "done", sub="成功条件・制約の確認")
    s += arrow(205, 110, cx - 78, cy - R - 4, "材料がそろったら", dy=-8)
    s += box(130, 480, 150, 46, "結果の出力", "todo", sub="結論・PDSの表")
    a = math.radians(210)
    s += arrow(cx + R * math.cos(a) - 40, cy + R * math.sin(a) + 26, 150, 455,
               "終了条件（成功／上限／停止）", dx=-12, dy=0, dash=True, anchor="end")
    s += legend(220, 570)
    return s + "</svg>\n"


def agent_svg(active):
    W, H = 960, 620
    s = head(W, H)
    s += f'<text x="24" y="34" font-size="18" font-weight="700" fill="{C["ink"]}">エージェント構成</text>\n'
    st = lambda k: "cur" if k == active else "todo"
    # 人間
    s += box(480, 90, 200, 50, "人間（利用者）", "todo", sub="調査プロンプト・判断")
    # まとめ役
    s += box(480, 290, 220, 64, "まとめ役の AI", st("lead"), sub="Plan・See／ループの管理")
    # 担当
    s += box(160, 290, 200, 60, "ソースコード担当", st("src"), sub="静的調査・修正・ログ追加")
    s += box(800, 290, 210, 60, "ビルド・デプロイ担当", st("build"), sub="ビルド・デプロイ・ログ取得")
    s += box(480, 490, 200, 56, "確認役の AI", st("check"), sub="合格の条件で評価")
    # 対象
    s += box(160, 490, 200, 50, "ソースコード", "done", sub="ローカルPC（C/C++）")
    s += box(800, 490, 200, 50, "実機", "done", sub="シェルコンソール")
    # ルール（スキル）
    for x, y, t in [(160, 170, "ログ追加のルール"), (730, 170, "クロスコンパイルのルール"), (880, 170, "デプロイのルール")]:
        s += (f'<rect x="{x-70}" y="{y-16}" width="140" height="32" rx="2" fill="#fffbe6" stroke="#b8860b" '
              f'stroke-dasharray="4 3"/><text x="{x}" y="{y+5}" text-anchor="middle" font-size="12" fill="{C["ink"]}">{t}</text>\n')
    s += arrow(160, 186, 160, 258, "従う", dx=18, dy=4)
    s += arrow(730, 186, 770, 258)
    s += arrow(880, 186, 840, 258)
    s += f'<text x="805" y="225" text-anchor="middle" font-size="11.5" fill="{C["ink"]}">従う</text>\n'
    s += f'<text x="810" y="140" text-anchor="middle" font-size="11" fill="#8a6d00">利用者が書き換えるルール（プラグインの中の部品）</text>\n'
    # 人間 ⇄ まとめ役
    s += arrow(460, 116, 460, 256, "プロンプト・判断", dx=-8, dy=0, anchor="end")
    s += arrow(500, 256, 500, 116, "質問・エラー報告", dx=8, dy=0, anchor="start")
    # まとめ役 ⇄ ソース担当
    s += arrow(368, 278, 262, 278, "Plan（調べる・直すこと）", dy=-8)
    s += arrow(262, 304, 368, 304, "調査結果・差分", dy=18)
    # まとめ役 ⇄ ビルド担当
    bcol = C["cur_bg"] if active == "build" else None
    s += arrow(592, 278, 693, 278, "ビルド・デプロイの指示", dy=-8, color=bcol)
    s += arrow(693, 304, 592, 304, "結果・ログ", dy=18)
    # まとめ役 ⇄ 確認役
    s += arrow(470, 324, 470, 460, "成果物", dx=-8, dy=0, anchor="end")
    s += arrow(490, 460, 490, 324, "評価（See）", dx=8, dy=0, anchor="start")
    # 担当 ⇄ 対象
    s += arrow(150, 322, 150, 463, "読む", dx=-8, dy=0, anchor="end")
    s += arrow(170, 322, 170, 463, "修正", dx=8, dy=0, anchor="start")
    s += arrow(790, 322, 790, 463, "モジュール転送", dx=-8, dy=0, anchor="end", color=bcol)
    s += arrow(810, 463, 810, 322, "ログ", dx=8, dy=0, anchor="start")
    s += legend(220, 590).replace("終わった工程", "対象").replace("いまの工程", "いま動いている AI")
    return s + "</svg>\n"


OUT.mkdir(parents=True, exist_ok=True)
(OUT / "loop_running.svg").write_text(loop_svg(
    ["done", "done", "cur", "todo", "todo", "todo"], "2 / 3", "動いている", None,
    "工程のループ図（例：2回目のビルド中）"), encoding="utf-8")
(OUT / "loop_waiting.svg").write_text(loop_svg(
    ["done", "done", "done", "err", "todo", "todo"], "2 / 3", "人間の判断待ち", "デプロイ失敗",
    "工程のループ図（例：デプロイに失敗して判断待ち）"), encoding="utf-8")
(OUT / "agents.svg").write_text(agent_svg("build"), encoding="utf-8")
