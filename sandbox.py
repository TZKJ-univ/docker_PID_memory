#!/usr/bin/env python3
# rss_bar_no_cli_dev.py
# 使い方: python rss_bar_no_cli_dev.py dammy_0510.txt
#
# ファイルに保存したサマリを読み込み，
#   ・横軸: PID
#   ・縦軸: PeakRSS[GiB]（0 GiB も含む）
# の棒グラフをコンテナごとに描画する。
# ただしコンテナ名が **cli** または **dev-** で始まるものは除外。

import sys
import re
import matplotlib.pyplot as plt
from collections import defaultdict, OrderedDict

path = sys.argv[1] if len(sys.argv) > 1 else "dammy_0510.txt"

# ── 正規表現 ─────────────────────────────────────────
header_re = re.compile(r'^\[(.+?)]')           # [container]
row_re    = re.compile(r'^\s*(\d+)\s+([\d.]+)')  # PID  RSS

current = None
data = defaultdict(OrderedDict)   # {container: {pid: rss}}

with open(path, encoding="utf-8") as f:
    for line in f:
        h = header_re.match(line)
        if h:
            cont = h.group(1).strip()
            # skip cli と dev-*
            if cont == "cli" or cont.startswith("dev-"):
                current = None
            else:
                current = cont
            continue
        if current:
            m = row_re.match(line)
            if m:
                pid = m.group(1)
                rss = float(m.group(2))   # 0 も保持
                data[current][pid] = rss

if not data:
    sys.exit("対象となるコンテナが見つかりません。")

# ── グラフ描画 ──────────────────────────────────────
n = len(data)
cols = 2
rows = (n + cols - 1) // cols
fig, axes = plt.subplots(rows, cols, figsize=(12, 4 * rows))
axes = axes.flatten()

for ax, (cname, pid_rss) in zip(axes, data.items()):
    pids = list(pid_rss.keys())
    rss  = list(pid_rss.values())
    ax.bar(pids, rss)
    ax.set_title(cname)
    ax.set_xlabel("PID")
    ax.set_ylabel("Memory [GB]")
    ax.set_xticks(pids)
    ax.tick_params(axis="x", rotation=90)

# 余ったサブプロットを削除
for ax in axes[len(data):]:
    fig.delaxes(ax)

plt.tight_layout()
plt.show()