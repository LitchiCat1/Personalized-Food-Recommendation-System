"""Plot the completed 19-user confirmation and both adjacent 20-user trials."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def build(report):
    data = json.loads((report/"analysis.json").read_text(encoding="utf-8"))
    confirmation = data["confirmation"]
    comparisons = [s for s in data["stages"] if s["users"] == 20]
    assert confirmation["users"] == 19 and confirmation["passed"]
    assert len(comparisons) == 2 and all(s["first_failed"] == 1 for s in comparisons)
    selected = [confirmation, *comparisons]
    plt.rcParams.update({"font.sans-serif": ["Microsoft JhengHei", "Microsoft YaHei", "DejaVu Sans"], "axes.unicode_minus": False, "font.size": 11})
    fig, ax = plt.subplots(figsize=(10.5, 4.2))
    y = list(range(3))
    completed = [s["successful_users"] for s in selected]
    failed = [s["first_failed"] for s in selected]
    ax.barh(y, completed, color="#00876b", label="完成操作流程", height=.6)
    ax.barh(y, failed, left=completed, color="#bd8429", label="首次連線未完成", height=.6)
    for i,s in enumerate(selected):
        ax.text(completed[i]/2, i, f"{completed[i]} 人", ha="center", va="center", color="white", fontsize=14, fontweight="bold")
        if failed[i]:
            ax.text(completed[i]+failed[i]/2, i, str(failed[i]), ha="center", va="center", color="white", fontweight="bold")
    labels = [f"19 人持續確認\n{s['duration_s']:.1f} 秒" if i==0 else f"20 人比較 {i}\n{s['duration_s']:.1f} 秒" for i,s in enumerate(selected)]
    ax.set_yticks(y, labels)
    ax.invert_yaxis(); ax.set_xlim(0, 21); ax.set_xticks([0,5,10,15,19,20])
    ax.set_xlabel("人數")
    ax.set_title("以所有人都順利完成操作作為穩定標準", loc="left", fontweight="bold", pad=42)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0,1.01), ncol=2)
    ax.spines[["top","right","left"]].set_visible(False)
    ax.grid(axis="x",color="#e0e6e8"); ax.set_axisbelow(True)
    fig.text(.025,.02,"19 人確認完整執行約兩分鐘；20 人的比較試驗在出現首次連線未完成後結束該級循環。",fontsize=9)
    fig.tight_layout(rect=(0,.07,1,1))
    output=report/"03-stable-capacity-reason.png"
    fig.savefig(output,dpi=180)
    plt.close(fig)
    print(output)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("report",type=Path)
    build(parser.parse_args().report.resolve())
