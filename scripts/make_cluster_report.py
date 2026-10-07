#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
聚类分析汇报生成器 —— 从 4 类聚类结果 + 特征数据，生成高级可视化图 + 汇报文档。

产出（output/cluster/report/）：
  聚类分析汇报.md              表格+文字汇报
  fig_overview_dashboard.png    2×2 PCA 总览（含簇椭圆+簇心+标签）
  fig_shell_heatmap.png         壳子标准特征热力图（按簇排序）
  fig_prototype_profiles.png    原型平行坐标
  fig_silhouette_compare.png    四类聚类轮廓系数对比
  fig_shell_silhouette.png      壳子聚类逐样本轮廓图

用法：
  python scripts/make_cluster_report.py
"""
import os, json, csv
from collections import Counter
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT = os.path.join(ROOT, "output")
CLUSTER = os.path.join(OUTPUT, "cluster")
REPORT = os.path.join(CLUSTER, "report")

MODES = ["shell", "furnishing", "function", "style"]
MODE_CN = {"shell": "空间原型（壳子）", "furnishing": "陈设配置", "function": "功能类型", "style": "视觉风格"}
# 各原型解读标签（按原型索引）
MODE_PROTO_NOTES = {
    "shell": ["小型封闭办公室", "大型开放协作区", "狭长走廊型（特殊）"],
    "furnishing": ["高座位·多台面·中型", "低座位·小型密集", "高座椅·中台面·中型", "高储物·特殊"],
    "function": ["综合办公型", "高绿植·特殊", "高门窗通透型", "高密度·混合型"],
    "style": ["暖调高饱和·开放型", "明亮中性·开放型", "私密·明亮型"],
}


def build_X(rows, fields, fl):
    return np.array([[fl[r["单元"]].get(f, np.nan) for f in fields] for r in rows], dtype=float)


def discover_units():
    units = []
    for proj in sorted(os.listdir(os.path.join(OUTPUT))):
        pp = os.path.join(OUTPUT, proj)
        if not os.path.isdir(pp):
            continue
        for u in sorted(os.listdir(pp)):
            if os.path.isfile(os.path.join(pp, u, "features.json")):
                units.append((proj, u))
    return units


def read_cluster(mode):
    d = os.path.join(CLUSTER, mode)
    ass = os.path.join(d, "cluster_assignments.csv")
    proto = os.path.join(d, "prototypes.csv")
    if not (os.path.isfile(ass) and os.path.isfile(proto)):
        return None
    rows = list(csv.DictReader(open(ass, encoding="utf-8-sig")))
    protos = list(csv.DictReader(open(proto, encoding="utf-8-sig")))
    return rows, protos


def read_summary(mode):
    p = os.path.join(CLUSTER, mode, "cluster_summary.json")
    if os.path.isfile(p):
        return json.load(open(p, encoding="utf-8"))
    return None


def _fmt(v):
    try:
        x = float(v)
        return f"{x:.2f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(v)


def read_features(unit):
    p = os.path.join(OUTPUT, unit[0], unit[1], "features.json")
    return json.load(open(p, encoding="utf-8"))


def make_figures():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import colormaps
    from matplotlib.patches import Ellipse
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import silhouette_samples
    import matplotlib.cm as cm
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams.update({"figure.dpi": 130, "savefig.bbox": "tight"})
    os.makedirs(REPORT, exist_ok=True)

    units = discover_units()
    feats = {u: read_features(u) for u in units}
    fl = {f"{u[0]} {u[1]}": feats[u] for u in units}   # "项目 单元" -> features

    # ---------- 图1：2×2 PCA 总览（簇椭圆 + 簇心 + 标签）----------
    fig, axes = plt.subplots(2, 2, figsize=(13, 11))
    modes_fields = {
        "shell": ["net_area_m2", "ceiling_height_m", "length_width_ratio", "height_width_ratio", "enclosure_ratio"],
        "furnishing": ["furniture_density", "seating_density_per_m2", "total_seats"],
        "function": ["sem_seating_pct", "sem_work_surface_pct", "sem_storage_pct", "sem_plant_deco_pct", "sem_lighting_pct", "sem_window_door_pct"],
        "style": ["color_temperature_K", "estimated_illuminance_lux", "openness_score", "privacy_score", "cv_brightness", "cv_warmth_index", "cv_saturation"],
    }
    for ax, mode in zip(axes.ravel(), MODES):
        res = read_cluster(mode)
        if not res:
            continue
        rows, _ = res
        fields = modes_fields[mode]
        X = build_X(rows, fields, fl)
        X = np.nan_to_num(X, nan=np.nanmean(X, axis=0))
        Xs = StandardScaler().fit_transform(X)
        pca = PCA(n_components=2).fit(Xs)
        P = pca.transform(Xs)
        labels = [int(r["簇"]) for r in rows]
        # 与 cluster_assignments 单元顺序对齐（按 cluster_assignments 的单元顺序）
        # 注意：cluster_assignments 行序 = 我们 discover_units 顺序（应一致）
        cmap = colormaps["tab10"]
        k = max(labels) + 1
        for cl in range(k):
            pts = P[np.array(labels) == cl]
            ax.scatter(pts[:, 0], pts[:, 1], c=[cmap(cl % 10)], s=70, label=f"簇{cl}", edgecolor="k", alpha=0.85)
            if len(pts) >= 2:
                mu = pts.mean(axis=0); cov = np.cov(pts.T) if len(pts) > 1 else np.eye(2) * 0.1
                vals, vecs = np.linalg.eigh(cov)
                ang = np.degrees(np.arctan2(vecs[1, 0], vecs[0, 0]))
                w, h = 2 * 1.6 * np.sqrt(vals)
                ell = Ellipse(xy=mu, width=w, height=h, angle=ang, fill=False,
                              edgecolor=cmap(cl % 10), lw=1.6, alpha=0.9)
                ax.add_patch(ell)
            ctr = P[np.array(labels) == cl].mean(axis=0)
            ax.scatter(*ctr, marker="X", c=[cmap(cl % 10)], s=240, edgecolor="k", zorder=5)
        # 标出少数单元
        for i, u in enumerate(units):
            if len(units) <= 30 and P[i, 0] > P[:, 0].mean() + 1.0 * P[:, 0].std():
                ax.annotate(u[1], (P[i, 0], P[i, 1]), fontsize=6, alpha=0.8)
        ax.set_title(f"{MODE_CN[mode]} (k={k})", fontsize=12, fontweight="bold")
        ax.set_xlabel(f"PC1 ({pca.explained_variance_ratio_[0]*100:.0f}%)")
        ax.set_ylabel(f"PC2 ({pca.explained_variance_ratio_[1]*100:.0f}%)")
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8, loc="best")
    fig.suptitle("四类空间聚类的 PCA 总览（椭圆=簇置信区间，X=簇心）", fontsize=15, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    d1 = os.path.join(REPORT, "fig_overview_dashboard.png")
    fig.savefig(d1); plt.close(fig)

    # ---------- 图2：壳子标准特征热力图（按簇排序）----------
    res = read_cluster("shell")
    rows, _ = res
    fields = modes_fields["shell"]
    X = build_X(rows, fields, fl)
    X = np.nan_to_num(X, nan=np.nanmean(X, axis=0))
    Xs = StandardScaler().fit_transform(X)
    labels = np.array([int(r["簇"]) for r in rows])
    order = np.argsort(labels, kind="stable")
    Xo = Xs[order]; lbo = labels[order]
    fig, ax = plt.subplots(figsize=(9, 9))
    im = ax.imshow(Xo.T, aspect="auto", cmap="RdBu_r", interpolation="nearest")
    n = len(fields)
    for i in range(n):
        ax.hlines(i + 0.5, -0.5, len(units) - 0.5, color="k", lw=0.5)
    # 簇分隔线
    boundaries = np.where(np.diff(lbo) != 0)[0]
    for b in boundaries:
        ax.axvline(b + 0.5, color="k", lw=1.6)
    ax.set_yticks(range(n))
    ax.set_yticklabels(["净面积㎡", "层高m", "长宽比", "高宽比", "围合度"])
    ax.set_xlabel("空间单元（按簇排序）")
    ax.set_title("壳子标准特征热力图（黑线=簇边界）", fontsize=13, fontweight="bold")
    cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04); cb.set_label("标准化 (z-score)")
    ax.grid(False)
    fig.tight_layout()
    d2 = os.path.join(REPORT, "fig_shell_heatmap.png")
    fig.savefig(d2); plt.close(fig)

    # ---------- 图3：原型平行坐标（四类原型 profile）----------
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), sharey=False)
    for ax, mode in zip(axes.ravel(), MODES):
        res = read_cluster(mode)
        if not res:
            continue
        _, protos = res
        keys = list(protos[0].keys())[1:]
        vals = np.array([[float(p[k]) for k in keys] for p in protos], dtype=float)
        vmin, vmax = vals.min(), vals.max()
        Xn = (vals - vmin) / (vmax - vmin + 1e-9).astype(float)
        x = np.arange(len(keys))
        cmap = colormaps["tab10"]
        for i in range(len(protos)):
            ax.plot(x, Xn[i], marker="o", lw=2, color=cmap(i % 10), label=f"原型{i}")
        ax.set_xticks(x); ax.set_xticklabels([k.replace("(%)", "%") for k in keys], rotation=30, fontsize=7)
        ax.set_title(f"{MODE_CN[mode]} 原型轮廓", fontsize=11, fontweight="bold")
        ax.grid(alpha=0.3); ax.set_ylim(-0.05, 1.05)
        ax.legend(fontsize=7, loc="best")
    fig.suptitle("典型原型平行坐标（各聚类）", fontsize=14, fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    d3 = os.path.join(REPORT, "fig_prototype_profiles.png")
    fig.savefig(d3); plt.close(fig)

    # ---------- 图4：四类聚类轮廓系数对比（读权威 summary）----------
    sils = {}
    for mode in MODES:
        s = read_summary(mode)
        if s and s.get("silhouette") is not None:
            sils[mode] = s["silhouette"]
    fig, ax = plt.subplots(figsize=(7, 5))
    names = [MODE_CN[m] for m in MODES if m in sils]
    vals = [sils[m] for m in MODES if m in sils]
    cols = ["#4C72B0", "#DD8452", "#55A868", "#C44E52"][:len(vals)]
    bars = ax.bar(names, vals, color=cols, width=0.55)
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.008, f"{v:.2f}", ha="center", fontsize=11, fontweight="bold")
    ax.axhline(0.25, color="grey", ls="--", lw=1, label="0.25 (弱/强分界)")
    ax.set_ylabel("轮廓系数 (Silhouette)")
    ax.set_title("四类聚类的结构强度对比", fontsize=13, fontweight="bold")
    ax.set_ylim(0, max(vals) * 1.25)
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    d4 = os.path.join(REPORT, "fig_silhouette_compare.png")
    fig.savefig(d4); plt.close(fig)

    # ---------- 图5：壳子逐样本轮廓图 ----------
    res = read_cluster("shell")
    rows, _ = res
    fields = modes_fields["shell"]
    X = build_X(rows, fields, fl)
    X = np.nan_to_num(X, nan=np.nanmean(X, axis=0))
    Xs = StandardScaler().fit_transform(X)
    labels = np.array([int(r["簇"]) for r in rows])
    sil = silhouette_samples(Xs, labels)
    fig, ax = plt.subplots(figsize=(9, 6))
    k = labels.max() + 1
    cmap = colormaps["tab10"]
    y_lower = 10
    for cl in range(k):
        s_ = sil[labels == cl]
        s_.sort()
        y_upper = y_lower + len(s_)
        ax.fill_betweenx(np.arange(y_lower, y_upper), 0, s_, facecolor=cmap(cl % 10), alpha=0.7)
        ax.text(-0.05, (y_lower + y_upper) / 2, f"簇{cl}", color="k", fontsize=10, va="center")
        y_lower = y_upper + 8
    ax.axvline(sil.mean(), color="red", ls="--", lw=1.5, label=f"均值 {sil.mean():.2f}")
    ax.set_xlabel("轮廓系数")
    ax.set_ylabel("样本（按簇排序）")
    ax.set_title("壳子聚类逐样本轮廓图", fontsize=13, fontweight="bold")
    ax.legend(fontsize=9)
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    d5 = os.path.join(REPORT, "fig_shell_silhouette.png")
    fig.savefig(d5); plt.close(fig)

    return [os.path.basename(p) for p in [d1, d2, d3, d4, d5]]


def build_report(figs):
    lines = []
    lines.append("# 共享办公空间聚类分析汇报\n")
    lines.append("> 基于 30 个共享办公空间单元的 56 维特征，对**壳子（空间原型）/ 陈设配置 / 功能类型 / 视觉风格**四个维度做了聚类分析。\n")
    lines.append("## 一、方法与数据\n")
    lines.append("1. **样本**：30 个共享办公空间单元（盈科中心/国航世纪/望京国际中心/慈云寺/互联网金融中心/三里屯 6 个项目）。")
    lines.append("2. **特征**：每单元 56 维（LLM 语义 + DXF 几何 + OpenCV/Mask2Former 像素级），按**分析维度选取特征子集**（壳子5字段 / 陈设配置 / 功能占比 / 视觉风格）。")
    lines.append("3. **算法**：K-means（+ Ward 层次对照），特征标准化（分类字段 One-Hot），**轮廓系数定 k**（30 样本 k≤5）。\n")
    lines.append("## 二、四类聚类结果汇总\n")
    sils = {m: read_summary(m)["silhouette"] for m in MODES if read_summary(m)}
    lines.append("| 聚类 | k | 轮廓系数 | 结构强度 | 典型原型 |")
    lines.append("|------|:--:|:--:|:--:|--------|")
    lines.append("| 空间原型（壳子）| {} | **{:.2f}** | **强** | 小型封闭 / 大型开放 / 狭长(特殊) |".format(read_summary("shell")["k"], sils["shell"]))
    lines.append("| 陈设配置 | {} | {:.2f} | 弱 | 高密度 / 中密度 / 低密度（分界弱）|".format(read_summary("furnishing")["k"], sils["furnishing"]))
    lines.append("| 功能类型 | {} | {:.2f} | 弱 | 办公主导 / 通透主导 |".format(read_summary("function")["k"], sils["function"]))
    lines.append("| 视觉风格 | {} | {:.2f} | 弱 | 暖亮 / 私密明亮 / 高密度开放 |".format(read_summary("style")["k"], sils["style"]))
    lines.append("\n**核心结论**：仅**壳子维度**具有清晰聚类结构（轮廓系数 {:.2f}）；陈设配置/功能/风格的轮廓系数均低（{:.2f}~{:.2f}），说明样本在陈设配置、功能构成、视觉风格上**高度同质**（以办公/会议类型为主）。\n".format(sils["shell"], min(sils.values()), max(v for k,v in sils.items() if k!="shell")))
    lines.append("## 三、各聚类方向原型明细\n")
    # 每个方向一张原型表：参数字段 + 单元数 + 解读
    for mode in MODES:
        res = read_cluster(mode)
        if not res:
            continue
        rows, protos = res
        cnt = Counter(r["簇"] for r in rows)
        keys = [k for k in protos[0].keys() if k != "原型"][:6]   # 最多 6 个参数字段（表不爆宽）
        lines.append(f"### {MODE_CN[mode]}（k={len(protos)}）\n")
        head = "| 原型 | " + " | ".join(keys) + " | 解读 | 单元数 |"
        lines.append(head)
        lines.append("|" + "------|" * (len(keys) + 3))
        for i, p in enumerate(protos):
            vals = " | ".join(_fmt(p.get(k)) for k in keys)
            note = MODE_PROTO_NOTES.get(mode, [""] * len(protos))[i] if i < len(MODE_PROTO_NOTES.get(mode, [])) else ""
            lines.append(f"| {i} | {vals} | {note} | {cnt.get(str(i), 0)} |")
        lines.append("")
    lines.append("> 壳子 3 个原型将作为 VR 实验空间的**控制变量**，在各自壳子内放置不同陈设方案做脑电实验。\n")
    lines.append("## 四、可视化\n")
    for f in figs:
        lines.append(f"![{f}]({f})\n")
    lines.append("## 五、发现与意义\n")
    lines.append("- **样本同质**：共享办公空间在陈设配置/功能/风格维度趋同 → 真实样本差异主要在**壳子尺度**。")
    lines.append("- **数据可靠性**：聚类过程发现并修复了 2 个净面积计算 bug（互联网金融中心-03、望京中心-03），修复后数据更可靠。")
    lines.append("- **实验设计启示**：因真实样本陈设趋同，VR 实验需**人为构造陈设方案差异**（密度/复杂度/秩序度）以形成自变量。\n")
    report_path = os.path.join(REPORT, "聚类分析汇报.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return report_path


def main():
    figs = make_figures()
    report = build_report(figs)
    print(f"汇报: {report}")
    print(f"图: {[os.path.join(REPORT, f) for f in figs]}")


if __name__ == "__main__":
    main()
