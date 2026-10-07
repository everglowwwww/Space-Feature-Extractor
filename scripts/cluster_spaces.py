#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
空间聚类 —— 从各空间单元的特征数据提取"典型原型"（可复用、mode 可插拔）。

用途：把 30 个空间单元按指定特征子集聚类，输出典型原型（簇心/代表）+ 归属 + 可视化 + CSV。
聚类结果沉淀在 skill 中，本脚本=唯一实现，无需每次重写。

复用方式（一个脚本，靠 --mode 切不同研究目的）：
  --mode shell     # 空间原型（壳子，5 物理围护字段）→ VR 构建的壳子原型
  --mode function  # 空间功能类型（语义功能要素占比）→ 功能混合度
  --mode style     # 视觉陈设风格（色彩/材质/光/感知；含文本字段自动 One-Hot）→ 陈设方案

用法：
  python scripts/cluster_spaces.py --mode shell     # 壳子（默认 k=3）
  python scripts/cluster_spaces.py --mode function  # 功能类型（自动定 k）
  python scripts/cluster_spaces.py --mode style     # 风格
  python scripts/cluster_spaces.py --mode <m> --k 4 # 指定 k
  python scripts/cluster_spaces.py --mode <m> --out output/cluster
"""
import os, sys, json, csv, argparse
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT = os.path.join(ROOT, "input")
OUTPUT = os.path.join(ROOT, "output")

# ---------------------------------------------------------------------------
# 各聚类模式的特征子集（数值字段 + 分类字段）。加新聚类只需在此扩展。
# ---------------------------------------------------------------------------
MODES = {
    "shell": {
        "desc": "空间原型聚类（壳子：物理围护参数）",
        "num_fields": ["net_area_m2", "ceiling_height_m",
                       "length_width_ratio", "height_width_ratio", "enclosure_ratio"],
        "cat_fields": [],
        "default_k": 3,  # 经轮廓系数+可解释性确认
        "field_cn": {"net_area_m2": "净使用面积(㎡)", "ceiling_height_m": "层高(m)",
                     "length_width_ratio": "长宽比", "height_width_ratio": "高宽比",
                     "enclosure_ratio": "围合度"},
    },
    "function": {
        "desc": "空间功能类型聚类（空间构成：功能要素占比）",
        "num_fields": ["sem_seating_pct", "sem_work_surface_pct", "sem_storage_pct",
                       "sem_plant_deco_pct", "sem_lighting_pct", "sem_window_door_pct",
                       "furniture_density"],
        "cat_fields": [],
        "field_cn": {"sem_seating_pct": "座椅占比%", "sem_work_surface_pct": "台面占比%",
                     "sem_storage_pct": "储物占比%", "sem_plant_deco_pct": "植物占比%",
                     "sem_lighting_pct": "照明占比%", "sem_window_door_pct": "门窗占比%",
                     "furniture_density": "家具密度"},
    },
    "style": {
        "desc": "视觉陈设风格聚类（色彩/材质/光/感知，含文本One-Hot）",
        "num_fields": ["color_temperature_K", "estimated_illuminance_lux", "daylight_factor",
                       "openness_score", "privacy_score", "estimated_RT60_s",
                       "furniture_density", "seating_density_per_m2", "total_seats",
                       "cv_brightness", "cv_contrast", "cv_color_temperature_K",
                       "cv_warmth_index", "cv_saturation", "cv_depth_cue"],
        "cat_fields": ["color_scheme", "floor_material", "wall_material",
                       "ceiling_material", "lighting_type"],
        "field_cn": {"color_temperature_K": "色温(K)", "estimated_illuminance_lux": "照度(lux)",
                     "daylight_factor": "采光系数", "openness_score": "开阔感",
                     "privacy_score": "私密性", "estimated_RT60_s": "混响RT60(s)",
                     "furniture_density": "家具密度", "seating_density_per_m2": "座位密度",
                     "total_seats": "总座位数", "cv_brightness": "画面亮度",
                     "cv_contrast": "对比度", "cv_color_temperature_K": "色温CV(K)",
                     "cv_warmth_index": "冷暖指数", "cv_saturation": "饱和度",
                     "cv_depth_cue": "纵深感"},
    },
    "furnishing": {
        "desc": "陈设配置聚类（密度 / 形态复杂度——论文实验自变量）",
        "num_fields": ["furniture_density", "seating_density_per_m2", "total_seats",
                       "sem_seating_pct", "sem_work_surface_pct", "sem_storage_pct",
                       "sem_plant_deco_pct", "sem_lighting_pct",
                       "color_1_pct", "color_2_pct", "color_3_pct"],
        "cat_fields": [],
        "field_cn": {"furniture_density": "家具密度", "seating_density_per_m2": "座位密度",
                     "total_seats": "总座位数", "sem_seating_pct": "座椅占比%",
                     "sem_work_surface_pct": "台面占比%", "sem_storage_pct": "储物占比%",
                     "sem_plant_deco_pct": "植物占比%", "sem_lighting_pct": "照明占比%",
                     "color_1_pct": "主色1占比%", "color_2_pct": "主色2占比%",
                     "color_3_pct": "主色3占比%"},
    },
}


def discover_units():
    units = []
    for proj in sorted(os.listdir(INPUT)):
        pp = os.path.join(INPUT, proj)
        if not os.path.isdir(pp):
            continue
        if not proj[:1].isdigit() and "-" not in proj[:2]:
            continue
        for u in sorted(os.listdir(pp)):
            if os.path.isdir(os.path.join(pp, u)) and os.path.isfile(os.path.join(pp, u, "plan.png")):
                units.append((proj, u))
    return units


def load_features(proj, unit):
    with open(os.path.join(OUTPUT, proj, unit, "features.json"), encoding="utf-8") as f:
        return json.load(f)


def build_matrix(units, mode):
    """抽取该 mode 特征：返回 (X_num ndarray, num_names, cat_df, labels)。cat_df 可为 None。"""
    cfg = MODES[mode]
    import pandas as pd
    X_num, labels, cat_rows = [], [], []
    for proj, unit in units:
        feats = load_features(proj, unit)
        labels.append(f"{proj} {unit}")
        X_num.append([float(feats[f]) if feats.get(f) is not None else np.nan
                      for f in cfg["num_fields"]])
        cat_rows.append({c: (feats.get(c) or "") for c in cfg["cat_fields"]})
    num_names = [cfg["field_cn"].get(f, f) for f in cfg["num_fields"]]
    cat_df = pd.DataFrame(cat_rows, index=labels) if cfg["cat_fields"] else None
    return np.array(X_num, dtype=float), num_names, cat_df, labels


def encode_matrix(X_num, cat_df, num_names):
    """数值标准化 + 分类 One-Hot，返回 (Xenc, enc_names, num_scaler, cat_dot)。"""
    from sklearn.preprocessing import StandardScaler
    num_scaler = StandardScaler()
    Xs_num = num_scaler.fit_transform(X_num)
    if cat_df is not None and len(cat_df.columns):
        import pandas as pd
        onehot = pd.get_dummies(cat_df, prefix_sep="__")
        Xenc = np.hstack([Xs_num, onehot.values.astype(float)])
        def _nm(x):
            s = str(x)
            return s.replace("__", "(", 1) + ")" if "__" in s else s
        enc_names = num_names + [_nm(c) for c in onehot.columns]
        return Xenc, enc_names, num_scaler, cat_df
    return Xs_num, num_names, num_scaler, None


def kmeans_best_k(X, k_max=5):
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    best_k, best_s, scores = 2, -1.0, []
    n = len(X)
    for k in range(2, min(k_max, n - 1) + 1):
        km = KMeans(n_clusters=k, n_init=20, random_state=42).fit(X)
        s = silhouette_score(X, km.labels_)
        scores.append((k, s))
        if s > best_s:
            best_k, best_s = k, s
    return best_k, scores


def run_cluster(Xenc, labels, enc_names, num_names, cat_df, num_scaler, mode,
                fixed_k=None, out_dir=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from sklearn.cluster import KMeans, AgglomerativeClustering
    from sklearn.decomposition import PCA
    from sklearn.metrics import silhouette_score
    from scipy.cluster.hierarchy import linkage, dendrogram
    from collections import Counter
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    os.makedirs(out_dir, exist_ok=True)
    cfg = MODES[mode]
    if np.isnan(Xenc).any():
        Xenc = np.nan_to_num(Xenc, nan=np.nanmean(Xenc, axis=0))
    Xs = np.nan_to_num(Xenc, nan=np.nanmean(Xenc, axis=0)) if np.isnan(Xenc).any() else Xenc
    n = len(Xs)

    best_k = fixed_k if fixed_k is not None else kmeans_best_k(Xs)[0]
    scores = kmeans_best_k(Xs)[1]
    km = KMeans(n_clusters=best_k, n_init=20, random_state=42).fit(Xs)
    sil = silhouette_score(Xs, km.labels_) if best_k < n else float("nan")
    ward = AgglomerativeClustering(n_clusters=best_k, linkage="ward").fit(Xs)
    Z = linkage(Xs, method="ward")

    print("=" * 70)
    print(f"空间聚类 [{mode}] {cfg['desc']}")
    print(f"  样本 {n} | 数值字段 {len(num_names)} 个" +
          (f" + 分类字段 {len(cfg['cat_fields'])} 个(One-Hot)" if cfg["cat_fields"] else ""))
    print(f"  最优 k = {best_k} | 轮廓系数 = {sil:.3f} | k 扫描: " +
          ", ".join(f"k{k}={s:.3f}" for k, s in scores if s is not None))
    print("=" * 70)

    # 簇心（数值部分反标准化回真实单位）
    num_cols = len(num_names)
    cen_num = num_scaler.inverse_transform(km.cluster_centers_[:, :num_cols])
    orig_num = num_scaler.inverse_transform(Xenc[:, :num_cols])   # 每单元原始数值
    print("\n[典型原型簇心（数值-真实单位）]")
    print(f"  {'簇':<3} " + "  ".join(f"{nm:>9}" for nm in num_names))
    for i, c in enumerate(cen_num):
        print(f"  {i:<3} " + "  ".join(f"{v:>9.2f}" for v in c))

    # 分类：每簇最常见类别
    cat_modes = {}
    if cat_df is not None and len(cat_df.columns):
        from collections import Counter
        for cl in range(best_k):
            members = cat_df[km.labels_ == cl]
            cat_modes[cl] = {}
            for col in cat_df.columns:
                vals = members[col].tolist()
                if vals:
                    cat_modes[cl][col] = Counter(vals).most_common(1)[0][0]
        print("\n[典型原型分类-各簇最常见类别]")
        for cl in range(best_k):
            print(f"  簇{cl}: " + " | ".join(f"{col}={cat_modes[cl].get(col,'')}" for col in cat_df.columns))

    size = Counter(km.labels_)
    singleton = {c for c, s_ in size.items() if s_ == 1}
    anomalies = [lbl for i, lbl in enumerate(labels) if km.labels_[i] in singleton]
    if anomalies:
        print("\n[异常/特殊标注] 单例簇单元:")
        for a in anomalies:
            print("   -", a)

    # --- 可视化：PCA 散点 / 簇心数值雷达 / k 轮廓 / 树状 ---
    pca = PCA(n_components=2).fit(Xs)
    pca_pts = pca.transform(Xs)
    pca_ctr = pca.transform(km.cluster_centers_)
    plt.figure(figsize=(7, 6))
    sc = plt.scatter(pca_pts[:, 0], pca_pts[:, 1], c=km.labels_, cmap="tab10", s=60)
    plt.scatter(pca_ctr[:, 0], pca_ctr[:, 1], marker="x", s=180, c="red", label="centroid")
    plt.title(f"{cfg['desc']} PCA (k={best_k})")
    plt.colorbar(sc, label="cluster"); plt.legend()
    plt.savefig(os.path.join(out_dir, "pca_scatter.png"), dpi=120, bbox_inches="tight"); plt.close()

    if num_cols >= 3:
        ang = np.linspace(0, 2 * np.pi, num_cols, endpoint=False).tolist()
        ang += ang[:1]
        fig = plt.figure(figsize=(6, 6)); ax = fig.add_subplot(111, projection="polar")
        for i, c in enumerate(cen_num):
            vals = ((c - c.min()) / (np.ptp(c) + 1e-9)).tolist(); vals += vals[:1]
            ax.plot(ang, vals, label=f"原型{i}"); ax.fill(ang, vals, alpha=0.1)
        ax.set_xticks(ang[:-1]); ax.set_xticklabels(num_names)
        ax.set_title(f"原型数值轮廓 (k={best_k})"); ax.legend(loc="lower right")
        plt.savefig(os.path.join(out_dir, "centroid_radar.png"), dpi=120, bbox_inches="tight"); plt.close()

    if scores:
        ks = [k for k, _ in scores if _ is not None]; ss = [s_ for _, s_ in scores if s_ is not None]
        plt.figure(figsize=(6, 4)); plt.plot(ks, ss, "o-")
        plt.axvline(best_k, color="r", ls="--"); plt.title("轮廓系数 vs k")
        plt.xlabel("k"); plt.ylabel("silhouette")
        plt.savefig(os.path.join(out_dir, "silhouette_vs_k.png"), dpi=120, bbox_inches="tight"); plt.close()

    plt.figure(figsize=(10, 5))
    dendrogram(Z, labels=[l.split()[-1] for l in labels], leaf_rotation=90, leaf_font_size=6)
    plt.title(f"层次聚类树状图 (Ward) k={best_k}")
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "dendrogram.png"), dpi=120, bbox_inches="tight"); plt.close()

    # --- CSV ---
    csv_path = os.path.join(out_dir, "cluster_assignments.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["单元", "簇"] + num_names + ["聚类(kmeans)", "聚类(ward)", "备注"])
        for i, lbl in enumerate(labels):
            note = "异常(单例)" if km.labels_[i] in singleton else ""
            w.writerow([lbl, km.labels_[i]] + [round(v, 3) for v in orig_num[i]] +
                       [km.labels_[i], ward.labels_[i], note])
    proto_path = os.path.join(out_dir, "prototypes.csv")
    with open(proto_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["原型"] + num_names)
        for i, c in enumerate(cen_num):
            w.writerow([i] + [round(v, 3) for v in c])

    # summary（供汇报脚本读取权威 k / 轮廓系数）
    import json as _json
    with open(os.path.join(out_dir, "cluster_summary.json"), "w", encoding="utf-8") as f:
        _json.dump({"mode": mode, "k": best_k, "silhouette": sil, "n_samples": n}, f,
                   ensure_ascii=False, indent=2)

    return dict(best_k=best_k, silhouette=sil, anomalies=anomalies,
                centroids=cen_num.tolist(), out_dir=out_dir)

def main():
    ap = argparse.ArgumentParser(description="空间聚类（壳子/功能/风格，可复用）")
    ap.add_argument("--mode", choices=list(MODES.keys()), default="shell")
    ap.add_argument("--k", type=int, default=None, help="指定聚类数（缺省用轮廓系数/模式默认）")
    ap.add_argument("--out", default=os.path.join(OUTPUT, "cluster"), help="输出目录")
    args = ap.parse_args()

    units = discover_units()
    if not units:
        print("未找到空间单元"); return
    X_num, num_names, cat_df, labels = build_matrix(units, args.mode)
    Xenc, enc_names, num_scaler, cat_df2 = encode_matrix(X_num, cat_df, num_names)
    fixed_k = args.k if args.k is not None else MODES[args.mode].get("default_k")
    out_dir = args.out if args.out.endswith(args.mode) else os.path.join(args.out, args.mode)
    run_cluster(Xenc, labels, enc_names, num_names, cat_df2, num_scaler, args.mode,
                fixed_k=fixed_k, out_dir=out_dir)
    print(f"\n输出: {out_dir}")


if __name__ == "__main__":
    main()
