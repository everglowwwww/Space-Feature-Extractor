#!/usr/bin/env python3
"""
共享办公空间分析器 v7 — Skill 版
=================================
阶段 B: 读取 LLM JSON + 平面图 + 透视照 → 56 特征 + 可视化图片

用法:
  python3 space_analyzer.py \
    --plan input/plan.jpg \
    --photos input/photo_01.png input/photo_02.png \
    --llm-json output/llm_understanding.json \
    --name "案例01_WeWork" \
    --out output/案例01_WeWork/ \
    [--report]
"""

import os, sys, json, csv, math, warnings, argparse
warnings.filterwarnings("ignore")

import cv2
import numpy as np

# =============================================
#  语义分组 (Mask2Former ADE20K 150→8组)
# =============================================
SEMANTIC_GROUPS = {
    "shell":        [0, 1, 5, 42],
    "floor":        [3],
    "window_door":  [8, 14, 58, 63],
    "seating":      [19, 23, 30, 31, 39, 69, 75, 97, 110],
    "work_surface": [15, 33, 45, 64, 70, 73, 77],
    "storage":      [10, 24, 35, 41, 44, 55, 62, 99],
    "plant_deco":   [4, 17, 22, 27, 66, 72, 100, 132, 135],
    "lighting":     [36, 82, 85, 87, 134],
}
_CID_TO_GROUP = {}
for _g, _ids in SEMANTIC_GROUPS.items():
    for _c in _ids:
        _CID_TO_GROUP[_c] = _g

GROUP_PALETTE = {
    "shell": (160,170,210), "floor": (210,175,120),
    "window_door": (100,190,255), "seating": (255,140,30),
    "work_surface": (255,210,50), "storage": (160,82,45),
    "plant_deco": (30,160,60), "lighting": (255,255,80),
    "other": (140,140,140),
}
GROUP_CN = {
    "shell":"围护壳体","floor":"地面","window_door":"门窗",
    "seating":"座椅","work_surface":"工作台面","storage":"储物",
    "plant_deco":"植物装饰","lighting":"照明","other":"其他",
}

RAL_COLORS = {
    "RAL 1001": ("#d1b98e","米色"),   "RAL 1002": ("#c8a86e","沙黄"),
    "RAL 1013": ("#e8e4d8","珍珠白"), "RAL 1015": ("#e6d2b5","淡象牙"),
    "RAL 5010": ("#004f7c","龙胆蓝"), "RAL 5024": ("#6093ac","粉蓝"),
    "RAL 6017": ("#4a7c42","五月绿"), "RAL 7035": ("#c5c7c4","浅灰"),
    "RAL 7044": ("#b8b1a2","丝灰"),   "RAL 8014": ("#49392d","棕褐"),
    "RAL 8022": ("#1a1718","黑棕"),   "RAL 9003": ("#ecece7","信号白"),
    "RAL 9010": ("#f5f3ee","纯白"),   "RAL 9016": ("#f5f5f0","交通白"),
}

# =============================================
#  中英文字段映射表 (英文key → 中文列头)
# =============================================
FIELD_CN = {
    "case_name":                "案例名称",
    "space_type":               "空间类型",
    "length_m":                 "空间总长度(m)",
    "width_m":                  "空间宽度(m)",
    "ceiling_height_m":         "层高(m)",
    "net_area_m2":              "净使用面积(m²)",
    "volume_m3":                "空间体积(m³)",
    "num_windows":              "窗户数量(组)",
    "window_wall_ratio":        "窗墙比",
    "num_doors":                "门/出入口数量(个)",
    "perimeter_m":              "围合周长(m)",
    "enclosure_ratio":          "围合度",
    "height_width_ratio":       "高宽比",
    "length_width_ratio":       "长宽比",
    "total_seats":              "总座位数(座)",
    "furniture_density":        "家具密度",
    "seating_density_per_m2":   "座位密度(座/m²)",
    "color_temperature_K":      "色温_LLM判读(K)",
    "color_scheme":             "色调方案",
    "floor_material":           "地面材质",
    "wall_material":            "墙面材质",
    "ceiling_material":         "天花材质",
    "color_1_hex":              "主色1-色值",
    "color_1_ral":              "主色1-RAL编号",
    "color_1_pct":              "主色1-面积占比(%)",
    "color_2_hex":              "主色2-色值",
    "color_2_ral":              "主色2-RAL编号",
    "color_2_pct":              "主色2-面积占比(%)",
    "color_3_hex":              "主色3-色值",
    "color_3_ral":              "主色3-RAL编号",
    "color_3_pct":              "主色3-面积占比(%)",
    "lighting_type":            "灯具类型",
    "num_visible_lights":       "可见灯具数量(个)",
    "estimated_illuminance_lux":"估算照度(lux)",
    "daylight_factor":          "采光系数",
    "openness_score":           "开阔感评分",
    "privacy_score":            "私密性评分",
    "estimated_RT60_s":         "混响时间RT60(s)",
    "cv_compactness":           "平面紧凑度",
    "cv_rectangularity":        "平面矩形度",
    "cv_convexity":             "平面凸性",
    "cv_h_transparency":        "水平通透度",
    "cv_v_transparency":        "垂直通透度",
    "sem_shell_pct":            "语义-围护壳体占比(%)",
    "sem_floor_pct":            "语义-地面占比(%)",
    "sem_window_door_pct":      "语义-门窗占比(%)",
    "sem_seating_pct":          "语义-座椅占比(%)",
    "sem_work_surface_pct":     "语义-工作台面占比(%)",
    "sem_storage_pct":          "语义-储物占比(%)",
    "sem_plant_deco_pct":       "语义-植物装饰占比(%)",
    "sem_lighting_pct":         "语义-照明占比(%)",
    "cv_brightness":            "画面亮度(0-255)",
    "cv_contrast":              "画面对比度(0-255)",
    "cv_color_temperature_K":   "色温_CV计算(K)",
    "cv_warmth_index":          "冷暖指数",
    "cv_saturation":            "画面饱和度(0-255)",
    "cv_depth_cue":             "纵深感",
}

# =============================================
#  Mask2Former 模型 (延迟加载)
# =============================================
_M2F_MODEL = None
_M2F_PROCESSOR = None
_M2F_DEVICE = None

def _load_m2f():
    global _M2F_MODEL, _M2F_PROCESSOR, _M2F_DEVICE
    if _M2F_MODEL is not None:
        return
    import torch
    from transformers import AutoImageProcessor, Mask2FormerForUniversalSegmentation
    MID = "facebook/mask2former-swin-tiny-ade-semantic"
    _M2F_DEVICE = "mps" if torch.backends.mps.is_available() else "cpu"
    print("    Loading Mask2Former ({})...".format(_M2F_DEVICE), end="", flush=True)
    _M2F_PROCESSOR = AutoImageProcessor.from_pretrained(MID)
    _M2F_MODEL = Mask2FormerForUniversalSegmentation.from_pretrained(MID)
    _M2F_MODEL = _M2F_MODEL.to(_M2F_DEVICE).eval()
    print(" done")

def run_mask2former(img_path):
    import torch
    from PIL import Image as PILImage
    _load_m2f()
    image = PILImage.open(img_path).convert("RGB")
    w, h = image.size
    inputs = _M2F_PROCESSOR(images=image, return_tensors="pt")
    inputs = {k: v.to(_M2F_DEVICE) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = _M2F_MODEL(**inputs)
    seg_map = _M2F_PROCESSOR.post_process_semantic_segmentation(
        outputs, target_sizes=[(h, w)]
    )[0].cpu().numpy().astype(np.uint8)
    total = h * w
    pcts = {}
    for gn, cids in SEMANTIC_GROUPS.items():
        pcts[gn] = round(np.sum(np.isin(seg_map, cids)) / total * 100, 2)
    pcts["other"] = round(max(0, 100 - sum(pcts.values())), 2)
    return pcts, seg_map

# =============================================
#  LLM JSON → 精简特征
# =============================================
def load_llm_understanding(json_path):
    with open(json_path, "r", encoding="utf-8") as fp:
        raw = json.load(fp)
    f = {}
    report = {}

    info = raw.get("空间基本信息", {})
    f["space_type"] = info.get("space_type", "")

    dim = raw.get("空间绝对尺度", {})
    f["length_m"] = dim.get("length_m", dim.get("total_length_m", -1))
    f["width_m"] = dim.get("width_m", -1)
    f["ceiling_height_m"] = dim.get("ceiling_height_m", -1)
    f["net_area_m2"] = dim.get("net_floor_area_m2", -1)
    f["volume_m3"] = dim.get("volume_m3", -1)
    report["gross_area_m2"] = dim.get("gross_floor_area_m2", -1)

    enc = raw.get("围护结构", {})
    f["num_windows"] = enc.get("num_windows", 0)
    f["window_wall_ratio"] = enc.get("window_wall_ratio", -1)
    f["num_doors"] = enc.get("num_doors", 0)
    f["perimeter_m"] = enc.get("perimeter_m", -1)
    f["enclosure_ratio"] = enc.get("enclosure_ratio", -1)
    report["num_exterior_walls"] = enc.get("num_exterior_walls", enc.get("num_walls", -1))
    report["num_interior_walls"] = enc.get("num_interior_walls", 0)

    ratio = raw.get("空间比例", {})
    f["height_width_ratio"] = ratio.get("height_width_ratio", -1)
    f["length_width_ratio"] = ratio.get("length_width_ratio", -1)

    furn = raw.get("家具配置", {})
    f["total_seats"] = furn.get("total_seats", 0)
    f["furniture_density"] = furn.get("furniture_density", -1)
    f["seating_density_per_m2"] = furn.get("seating_density_per_m2", -1)
    report["total_furniture_footprint_m2"] = furn.get("total_furniture_footprint_m2", -1)
    report["furniture_types"] = ", ".join(
        g.get("type","") for g in furn.get("furniture_groups", []))

    color = raw.get("色彩与材质", {})
    f["color_temperature_K"] = color.get("color_temperature_K", -1)
    f["color_scheme"] = color.get("color_scheme", "")
    f["floor_material"] = color.get("primary_floor_material", "")
    f["wall_material"] = color.get("primary_wall_material", "")
    f["ceiling_material"] = color.get("primary_ceiling_material", "")
    dom_colors = color.get("dominant_colors", [])
    for i, dc in enumerate(dom_colors[:3]):
        f["color_{}_hex".format(i+1)] = dc.get("hex", "")
        f["color_{}_ral".format(i+1)] = dc.get("ral_approx", "")
        f["color_{}_pct".format(i+1)] = dc.get("area_pct", 0)
    for i, dc in enumerate(dom_colors[:6]):
        report["color_{}_name".format(i+1)] = dc.get("color_name", "")
        report["color_{}_hex".format(i+1)] = dc.get("hex", "")
        report["color_{}_pct".format(i+1)] = dc.get("area_pct", 0)

    light = raw.get("光环境", {})
    f["lighting_type"] = light.get("lighting_type", "")
    f["num_visible_lights"] = light.get("num_visible_lights", 0)
    f["estimated_illuminance_lux"] = light.get("estimated_illuminance_lux", -1)
    f["daylight_factor"] = light.get("daylight_factor_est", -1)

    perc = raw.get("空间感知指标", {})
    f["openness_score"] = perc.get("openness_score", -1)
    f["privacy_score"] = perc.get("privacy_score", -1)
    f["estimated_RT60_s"] = perc.get("estimated_RT60_s", -1)

    return f, report, raw

# =============================================
#  OpenCV 平面图分析
# =============================================
def analyze_plan_cv(img_path, output_dir=None):
    gray = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return {}
    h, w = gray.shape
    total_px = h * w
    f = {}

    _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
    contours_ext, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours_ext:
        mc = max(contours_ext, key=cv2.contourArea)
        area_px = cv2.contourArea(mc)
        peri_px = cv2.arcLength(mc, True)
    else:
        mc = None
        area_px = float(total_px)
        peri_px = float(2 * (h + w))

    if mc is not None and len(mc) >= 5:
        rect = cv2.minAreaRect(mc)
        rw, rh = rect[1]
        long_px, short_px = max(rw, rh), min(rw, rh)
        hull = cv2.convexHull(mc)
        hull_area = cv2.contourArea(hull)
    else:
        long_px, short_px = max(w, h), min(w, h)
        hull_area = area_px

    f["cv_compactness"] = round(4 * math.pi * area_px / max(peri_px ** 2, 1), 4)
    f["cv_rectangularity"] = round(area_px / max(long_px * short_px, 1), 4)
    f["cv_convexity"] = round(area_px / max(hull_area, 1), 4)
    f["cv_h_transparency"] = round(_scan_transparency(binary, "h"), 4)
    f["cv_v_transparency"] = round(_scan_transparency(binary, "v"), 4)

    # 保存二值化图片
    if output_dir:
        bin_rgb = cv2.cvtColor(binary, cv2.COLOR_GRAY2RGB)
        cv2.imwrite(os.path.join(output_dir, "plan_binary.png"), bin_rgb)

    return f

def _scan_transparency(binary, axis="h"):
    h, w = binary.shape
    if axis == "h":
        vals = [_max_consecutive((binary[r, :] == 0).astype(np.uint8)) / w for r in range(h)]
    else:
        vals = [_max_consecutive((binary[:, c] == 0).astype(np.uint8)) / h for c in range(w)]
    return np.mean(vals)

def _max_consecutive(arr):
    mx = cur = 0
    for v in arr:
        if v: cur += 1; mx = max(mx, cur)
        else: cur = 0
    return mx

# =============================================
#  Mask2Former 语义构成
# =============================================
def analyze_semantics(photo_paths, output_dir=None):
    if not photo_paths:
        return {}, None
    all_sem, first_seg = [], None
    first_photo_path = None
    for p in photo_paths:
        try:
            pcts, seg = run_mask2former(p)
            all_sem.append(pcts)
            if first_seg is None:
                first_seg = seg
                first_photo_path = p
        except Exception as e:
            print("    Warning: {}".format(e))
    if not all_sem:
        return {}, None

    f = {}
    for gn in list(SEMANTIC_GROUPS.keys()):
        vals = [s.get(gn, 0) for s in all_sem]
        f["sem_{}_pct".format(gn)] = round(np.mean(vals), 2)

    # 保存语义分割可视化图片
    if output_dir and first_seg is not None and first_photo_path:
        from PIL import Image as PILImage
        photo_arr = np.array(PILImage.open(first_photo_path).convert("RGB"))
        seg_color = np.zeros_like(photo_arr)
        for cid in np.unique(first_seg):
            gn = _CID_TO_GROUP.get(cid, "other")
            seg_color[first_seg == cid] = GROUP_PALETTE.get(gn, (140,140,140))
        overlay = (photo_arr * 0.35 + seg_color * 0.65).astype(np.uint8)
        cv2.imwrite(os.path.join(output_dir, "seg_semantic.png"),
                    cv2.cvtColor(seg_color, cv2.COLOR_RGB2BGR))
        cv2.imwrite(os.path.join(output_dir, "seg_overlay.png"),
                    cv2.cvtColor(overlay, cv2.COLOR_RGB2BGR))

    return f, first_seg

# =============================================
#  OpenCV 透视照感知分析
# =============================================
def _hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def _nearest_ral(r, g, b):
    best, best_d = "RAL 9010", 999
    for code, (hex_val, _) in RAL_COLORS.items():
        rr, rg, rb = _hex_to_rgb(hex_val)
        d = math.sqrt((r-rr)**2 + (g-rg)**2 + (b-rb)**2)
        if d < best_d:
            best_d = d
            best = code
    return best, RAL_COLORS[best][1]

def analyze_photo_perception(img_path):
    img = cv2.imread(img_path)
    if img is None:
        return {}
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, w = gray.shape
    total = h * w
    h_ch, s_ch, v_ch = cv2.split(hsv)
    f = {}

    f["cv_brightness"] = round(float(np.mean(v_ch)), 1)
    f["cv_contrast"] = round(float(np.std(v_ch.astype(float))), 1)

    b_m = float(np.mean(img[:,:,0]))
    r_m = float(np.mean(img[:,:,2]))
    rb_ratio = r_m / max(b_m, 1)
    cct = int(6500 / max(rb_ratio, 0.3))
    cct = max(2000, min(12000, cct))
    f["cv_color_temperature_K"] = cct

    warm = ((h_ch < 30) | (h_ch > 150)) & (s_ch > 30)
    cool = ((h_ch > 75) & (h_ch < 135)) & (s_ch > 30)
    warm_pct = round(np.sum(warm) / total * 100, 1)
    cool_pct = round(np.sum(cool) / total * 100, 1)
    f["cv_warmth_index"] = round(warm_pct - cool_pct, 1)

    f["cv_saturation"] = round(float(np.mean(s_ch)), 1)

    mid_y = h // 2
    sobelx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    grad = np.sqrt(sobelx**2 + sobely**2)
    f["cv_depth_cue"] = round(np.mean(grad[mid_y:]) / max(np.mean(grad[:mid_y]), 1), 4)

    return f

# =============================================
#  主管线
# =============================================
def run(plan_path, photo_paths, case_name, output_dir, llm_json=None, gen_report=False):
    os.makedirs(output_dir, exist_ok=True)

    if not case_name:
        case_name = os.path.basename(output_dir)

    print("")
    print("=" * 65)
    print("  Space Analyzer v7 (Skill)")
    print("  Case: {}".format(case_name))
    print("=" * 65)

    row = {"case_name": case_name}
    report = {}
    llm_raw = None

    # Step 1: LLM JSON
    if llm_json and os.path.exists(llm_json):
        print("\n  [Step 1/4] LLM understanding: {}".format(os.path.basename(llm_json)))
        llm_feat, llm_report, llm_raw = load_llm_understanding(llm_json)
        row.update(llm_feat)
        report.update(llm_report)
        print("    {}m x {}m, H={}m, Area={}m², Seats={}".format(
            row.get('length_m'), row.get('width_m'), row.get('ceiling_height_m'),
            row.get('net_area_m2'), row.get('total_seats')))
    else:
        print("\n  [Step 1/4] LLM JSON not provided, skipping")

    # Step 2: OpenCV plan
    print("\n  [Step 2/4] OpenCV plan analysis")
    plan_f = analyze_plan_cv(plan_path, output_dir)
    row.update(plan_f)
    if plan_f:
        print("    plan_binary.png saved")
        print("    Compactness={}, Rectangularity={}".format(
            plan_f.get('cv_compactness'), plan_f.get('cv_rectangularity')))

    # Step 3: Mask2Former
    seg_map = None
    if photo_paths:
        print("\n  [Step 3/4] Mask2Former segmentation")
        sem_f, seg_map = analyze_semantics(photo_paths, output_dir)
        row.update(sem_f)
        if sem_f:
            print("    seg_semantic.png + seg_overlay.png saved")
            top3 = sorted(sem_f.items(), key=lambda x: -x[1])[:3]
            for k, v in top3:
                gn = k.replace("sem_","").replace("_pct","")
                print("    {:12s} {:6.2f}%".format(GROUP_CN.get(gn,gn), v))

        # Step 4: OpenCV perception
        print("\n  [Step 4/4] OpenCV perception")
        perc_results = []
        for p in photo_paths:
            pf = analyze_photo_perception(p)
            if pf:
                perc_results.append(pf)
        if perc_results:
            for k in perc_results[0]:
                vals = [r[k] for r in perc_results if k in r and isinstance(r[k], (int, float))]
                if vals:
                    row[k] = round(np.mean(vals), 4) if isinstance(vals[0], float) else int(np.mean(vals))
            print("    Brightness={}, CCT={}K, Warmth={}".format(
                row.get('cv_brightness'), row.get('cv_color_temperature_K'),
                row.get('cv_warmth_index')))
    else:
        print("\n  [Step 3/4] No photos, skipping Mask2Former + perception")

    # Save outputs
    feat_count = len([k for k in row if k != "case_name"])
    print("\n  Total features: {}".format(feat_count))

    # JSON（英文 key，便于程序读取）
    json_path = os.path.join(output_dir, "features.json")
    with open(json_path, "w", encoding="utf-8") as fp:
        json.dump(row, fp, indent=2, ensure_ascii=False,
                  default=lambda o: int(o) if isinstance(o, np.integer)
                  else float(o) if isinstance(o, np.floating) else str(o))
    print("  -> {}".format(json_path))

    # JSON 中文版（中文 key + 单位，便于人类阅读）
    row_cn = {}
    for k, v in row.items():
        cn_key = FIELD_CN.get(k, k)
        row_cn[cn_key] = v
    json_cn_path = os.path.join(output_dir, "features_cn.json")
    with open(json_cn_path, "w", encoding="utf-8") as fp:
        json.dump(row_cn, fp, indent=2, ensure_ascii=False,
                  default=lambda o: int(o) if isinstance(o, np.integer)
                  else float(o) if isinstance(o, np.floating) else str(o))
    print("  -> {}".format(json_cn_path))

    # CSV（中文列头，Excel 友好）
    csv_path = os.path.join(output_dir, "features.csv")
    en_keys = list(row.keys())
    cn_headers = [FIELD_CN.get(k, k) for k in en_keys]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as fp:
        writer = csv.writer(fp)
        writer.writerow(cn_headers)
        writer.writerow([row[k] for k in en_keys])
    print("  -> {}".format(csv_path))

    # HTML report (optional)
    if gen_report and photo_paths:
        print("  -> report.html (generating...)")
        # import the HTML generator from the old codebase if needed
        # for now, just note it
        print("     [HTML report generation requires the full template - skipped in skill v7]")

    print("\n" + "=" * 65)
    print("  Done! Output: {}".format(output_dir))
    print("=" * 65)
    return row


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Space Analyzer v7 — 共享办公空间特征提取 (阶段B)")
    parser.add_argument("--plan", required=True, help="平面图路径")
    parser.add_argument("--photos", nargs="+", default=[], help="透视照路径 (可多张)")
    parser.add_argument("--llm-json", default=None, help="LLM 空间理解 JSON 路径")
    parser.add_argument("--name", default=None, help="案例名称")
    parser.add_argument("--out", required=True, help="输出目录")
    parser.add_argument("--report", action="store_true", help="生成 HTML 报告")
    args = parser.parse_args()
    run(args.plan, args.photos, args.name, args.out,
        llm_json=args.llm_json, gen_report=args.report)
