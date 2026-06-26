#!/usr/bin/env python3
"""
案例分析卡片生成器 v3 — 空间名片风格
==========================================
每张卡片像一张建筑杂志的空间介绍页 / 一张名片：
  - 浅色背景，利用空间自身主色做配色
  - 杂志式排版，不用"科技感深色"模板
  - 大图为主，数据为辅
  - 2x 分辨率渲染（Retina 清晰度）

产出：
  1. seg_overlay_legend.png  — 语义叠加图 + 图例
  2. seg_semantic_legend.png — 纯语义色块图 + 图例
  3. plan_annotated.png      — 平面图标注几何指标
  4. case_card.png           — 汇总名片（2400x3200 @2x → 1200x1600 逻辑像素）
"""

import os, json, math
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── 分辨率 ────────────────────────────────────────────
SCALE = 2  # Retina 2x

def S(v):
    """按 SCALE 缩放像素值"""
    return int(v * SCALE)

# ── 字体 ──────────────────────────────────────────────
_FONT_CACHE = {}

def _find_fonts():
    """返回 (regular_path, bold_path)"""
    regular_candidates = [
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    bold_candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    reg = None
    for p in regular_candidates:
        if os.path.isfile(p):
            reg = p
            break
    bold = None
    for p in bold_candidates:
        if os.path.isfile(p):
            bold = p
            break
    return reg or bold, bold or reg

_FONT_REG, _FONT_BOLD = _find_fonts()

def font(size, bold=False):
    """获取指定大小的字体（已按 SCALE 缩放）"""
    real_size = S(size)
    key = (real_size, bold)
    if key not in _FONT_CACHE:
        fp = _FONT_BOLD if bold else _FONT_REG
        if fp:
            _FONT_CACHE[key] = ImageFont.truetype(fp, real_size, index=0)
        else:
            _FONT_CACHE[key] = ImageFont.load_default()
    return _FONT_CACHE[key]


# ── 颜色工具 ─────────────────────────────────────────
def hex_to_rgb(h):
    h = h.lstrip("#")
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except:
        return (160, 160, 160)

def rgb_luminance(r, g, b):
    return 0.299 * r + 0.587 * g + 0.114 * b

def lighten(color, amount=0.85):
    """将颜色向白色混合"""
    return tuple(int(c + (255 - c) * amount) for c in color)

def darken(color, amount=0.3):
    """将颜色向黑色混合"""
    return tuple(int(c * (1 - amount)) for c in color)

def with_alpha(color, alpha):
    return color + (alpha,)

def text_right(draw, x_right, y, text, fill, f):
    bbox = draw.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    draw.text((x_right - tw, y), text, fill=fill, font=f)

def text_center(draw, cx, y, text, fill, f):
    bbox = draw.textbbox((0, 0), text, font=f)
    tw = bbox[2] - bbox[0]
    draw.text((cx - tw // 2, y), text, fill=fill, font=f)

def rr(draw, bbox, radius, **kw):
    """圆角矩形，兼容旧版 Pillow"""
    try:
        draw.rounded_rectangle(bbox, radius=radius, **kw)
    except AttributeError:
        draw.rectangle(bbox, **kw)

def round_corners(img, radius):
    """给图片加圆角遮罩（返回 RGBA）"""
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([0, 0, w, h], radius=radius, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask)
    return out

# ── 语义分组配色 ─────────────────────────────────────
GROUP_PALETTE = {
    "shell": (160, 170, 210), "floor": (210, 175, 120),
    "window_door": (100, 190, 255), "seating": (255, 140, 30),
    "work_surface": (255, 210, 50), "storage": (160, 82, 45),
    "plant_deco": (30, 160, 60), "lighting": (255, 255, 80),
    "other": (150, 150, 150),
}
GROUP_CN = {
    "shell": "围护壳体", "floor": "地面", "window_door": "门窗",
    "seating": "座椅", "work_surface": "工作台面", "storage": "储物",
    "plant_deco": "植物装饰", "lighting": "照明", "other": "其他",
}


# =============================================
#  1. 语义分割图 + 图例 (2x 渲染)
# =============================================
def add_legend_to_segmentation(img_path, output_path, sem_pcts):
    img = Image.open(img_path).convert("RGB")
    iw, ih = img.size

    legend_w = S(200)
    padding = S(16)
    item_h = S(36)
    title_h = S(44)

    sorted_groups = sorted(sem_pcts.items(), key=lambda x: -x[1])
    sorted_groups = [(k, v) for k, v in sorted_groups if v > 0.05]

    content_h = title_h + len(sorted_groups) * item_h + padding * 2
    canvas_h = max(ih, content_h)

    # 浅色背景图例
    bg_color = (245, 245, 248)
    canvas = Image.new("RGB", (iw + legend_w, canvas_h), bg_color)
    canvas.paste(img, (0, (canvas_h - ih) // 2))

    draw = ImageDraw.Draw(canvas)
    lx = iw
    ly = (canvas_h - content_h) // 2 + padding

    # 图例区背景
    draw.rectangle([lx, 0, lx + legend_w, canvas_h], fill=bg_color)
    # 左侧细线
    draw.rectangle([lx, 0, lx + S(1), canvas_h], fill=(200, 200, 205))

    f_title = font(13, bold=True)
    f_name = font(11)
    f_pct = font(10)

    ink = (40, 40, 50)
    ink_light = (110, 115, 125)

    draw.text((lx + padding, ly), "语义构成", fill=ink, font=f_title)
    ly += title_h

    bar_w = legend_w - padding * 2 - S(28)

    for gn, pct in sorted_groups:
        color = GROUP_PALETTE.get(gn, (150, 150, 150))
        cn = GROUP_CN.get(gn, gn)
        cx = lx + padding
        cy = ly

        # 色块
        rr(draw, [cx, cy + S(2), cx + S(16), cy + S(16)], radius=S(3), fill=color)

        # 名称
        draw.text((cx + S(22), cy), cn, fill=ink, font=f_name)

        # 百分比右对齐
        text_right(draw, lx + legend_w - padding, cy, "{:.1f}%".format(pct),
                   ink_light, f_pct)

        # 进度条
        by = cy + S(22)
        bh = S(5)
        rr(draw, [cx + S(22), by, cx + S(22) + bar_w - S(40), by + bh],
           radius=S(2), fill=(225, 225, 230))
        fill_w = max(S(2), int((bar_w - S(40)) * pct / 100))
        if fill_w > S(2):
            rr(draw, [cx + S(22), by, cx + S(22) + fill_w, by + bh],
               radius=S(2), fill=color)

        ly += item_h

    canvas.save(output_path, quality=95)
    return output_path


# =============================================
#  2. 平面图增强标注 (2x 渲染, 保留原图风格)
# =============================================
def generate_plan_annotated(plan_path, output_path, features):
    gray = cv2.imread(plan_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return None
    h, w = gray.shape

    # 判断原图是白底还是黑底（看平均亮度）
    mean_val = np.mean(gray)
    is_dark_bg = mean_val < 128

    # 2x 缩放原图
    h2, w2 = h * SCALE, w * SCALE
    gray2 = cv2.resize(gray, (w2, h2), interpolation=cv2.INTER_CUBIC)

    pad = S(24)
    bottom_h = S(80)
    cw = w2 + pad * 2
    ch = h2 + pad + bottom_h + S(16)

    bg_color = (248, 248, 250)

    # 用 PIL 全流程，避免 BGR/RGB 混乱
    pil_plan = Image.fromarray(gray2).convert("RGB")

    if is_dark_bg:
        # 黑底白线 → 转为白底灰线
        plan_arr = np.array(pil_plan)
        # 反转：白变灰线，黑变白底
        inverted = 255 - plan_arr
        # 稍微加深线条
        inverted = np.clip(inverted * 0.7 + 60, 60, 252).astype(np.uint8)
        pil_plan = Image.fromarray(inverted)

    canvas = Image.new("RGB", (cw, ch), bg_color)
    canvas.paste(pil_plan, (pad, S(12)))

    # 轮廓分析 — 用 OpenCV 计算，用 PIL 绘制
    # 二值化用于找轮廓（在原始尺寸上做）
    if is_dark_bg:
        _, binary_small = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY)
    else:
        _, binary_small = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY_INV)
    contours_ext, _ = cv2.findContours(binary_small, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    draw = ImageDraw.Draw(canvas)

    if contours_ext:
        mc = max(contours_ext, key=cv2.contourArea)

        # 缩放+偏移到画布坐标
        def to_canvas_pts(pts):
            return [(int(p[0][0] * SCALE + pad), int(p[0][1] * SCALE + S(12))) for p in pts]

        # 凸包
        hull = cv2.convexHull(mc)
        hull_pts = to_canvas_pts(hull)
        if len(hull_pts) > 2:
            draw.polygon(hull_pts, outline=(140, 200, 160))

        # 外接矩
        rect = cv2.minAreaRect(mc)
        box = cv2.boxPoints(rect)
        box_pts = [(int(p[0] * SCALE + pad), int(p[1] * SCALE + S(12))) for p in box]
        if len(box_pts) == 4:
            draw.polygon(box_pts, outline=(160, 180, 210))

        # 主轮廓 — 画成一系列线段
        mc_pts = to_canvas_pts(mc)
        if len(mc_pts) > 2:
            draw.polygon(mc_pts, outline=(60, 120, 200))

    # 分割线
    line_y = h2 + S(20)
    draw.rectangle([pad, line_y, cw - pad, line_y + 1], fill=(210, 210, 215))

    metrics = [
        ("紧凑度", features.get("cv_compactness", "—")),
        ("矩形度", features.get("cv_rectangularity", "—")),
        ("凸性", features.get("cv_convexity", "—")),
        ("水平通透", features.get("cv_h_transparency", "—")),
        ("垂直通透", features.get("cv_v_transparency", "—")),
    ]

    f_lbl = font(10)
    f_val = font(14, bold=True)
    f_leg = font(9)

    ink = (50, 55, 65)
    ink2 = (100, 105, 115)
    accent = (60, 120, 200)

    cell_w = (cw - pad * 2) // len(metrics)
    my = line_y + S(12)

    for i, (label, val) in enumerate(metrics):
        cx = pad + i * cell_w + cell_w // 2
        val_str = "{:.3f}".format(val) if isinstance(val, float) else str(val)
        text_center(draw, cx, my, label, ink2, f_lbl)
        text_center(draw, cx, my + S(18), val_str, accent, f_val)

    # 图例
    leg_y = my + S(44)
    items = [((60, 120, 200), "主轮廓"), ((160, 180, 210), "外接矩"), ((140, 200, 160), "凸包")]
    lx = pad
    for c, t in items:
        draw.rectangle([lx, leg_y + S(2), lx + S(16), leg_y + S(8)], fill=c)
        draw.text((lx + S(22), leg_y - S(2)), t, fill=ink2, font=f_leg)
        lx += S(90)

    canvas.save(output_path, quality=95)
    return output_path


# =============================================
#  3. 案例名片卡 v3 — 杂志风格
# =============================================
def generate_case_card(output_dir, features, case_name=None):
    if case_name is None:
        case_name = features.get("case_name", "未命名案例")

    # 从空间主色中提取配色
    primary_hex = features.get("color_1_hex", "#a0a0a0")
    secondary_hex = features.get("color_2_hex", "#c0c0c0")
    primary = hex_to_rgb(primary_hex)
    secondary = hex_to_rgb(secondary_hex)

    # 计算卡片配色：用空间主色的极浅色调做背景
    bg_base = lighten(primary, 0.92)
    # 确保背景足够浅
    if rgb_luminance(*bg_base) < 230:
        bg_base = lighten(primary, 0.95)

    accent = darken(primary, 0.15)
    ink = (35, 35, 42)
    ink2 = (90, 95, 105)
    ink3 = (140, 142, 150)

    # 卡片尺寸 (逻辑像素 1200 x auto, 2x 渲染)
    CW = S(1200)
    pad = S(40)
    inner = CW - pad * 2

    # 预留足够高度 (RGBA for compositing rounded images)
    card = Image.new("RGBA", (CW, S(2200)), bg_base + (255,))
    draw = ImageDraw.Draw(card)

    # 字体
    f_case = font(32, bold=True)
    f_type = font(14)
    f_section = font(13, bold=True)
    f_label = font(10)
    f_value = font(20, bold=True)
    f_unit = font(10)
    f_small = font(9)
    f_bar = font(10)
    f_tag = font(8)
    f_num = font(36, bold=True)

    y = S(0)

    # ── 顶部色带 ──
    # 用主色做一条渐变色带
    band_h = S(6)
    for i in range(band_h):
        t = i / band_h
        r = int(primary[0] * (1 - t) + secondary[0] * t)
        g = int(primary[1] * (1 - t) + secondary[1] * t)
        b = int(primary[2] * (1 - t) + secondary[2] * t)
        draw.rectangle([0, i, CW, i + 1], fill=(r, g, b))
    y = band_h + S(36)

    # ── 案例名（大字） ──
    draw.text((pad, y), case_name, fill=ink, font=f_case)
    y += S(44)

    # 空间类型
    space_type = features.get("space_type", "")
    if space_type:
        draw.text((pad, y), space_type, fill=ink2, font=f_type)
        y += S(24)

    # 细分割线
    y += S(8)
    draw.rectangle([pad, y, pad + S(60), y + S(2)], fill=accent)
    y += S(24)

    # ── 核心指标行：大数字排列 ──
    key_metrics = []
    area = features.get("net_area_m2")
    if area and area > 0:
        key_metrics.append(("{:.0f}".format(area), "m²", "面积"))
    height = features.get("ceiling_height_m")
    if height and height > 0:
        key_metrics.append(("{:.1f}".format(height), "m", "层高"))
    seats = features.get("total_seats")
    if seats and seats > 0:
        key_metrics.append(("{}".format(int(seats)), "席", "座位"))

    if key_metrics:
        col_w = inner // max(len(key_metrics), 1)
        for i, (val, unit, label) in enumerate(key_metrics):
            mx = pad + i * col_w

            # 大数字
            draw.text((mx, y), val, fill=ink, font=f_num)
            # 单位 (紧跟数字右侧)
            vbbox = draw.textbbox((mx, y), val, font=f_num)
            draw.text((vbbox[2] + S(4), y + S(20)), unit, fill=ink2, font=f_type)

            # 标签
            draw.text((mx, y + S(52)), label, fill=ink3, font=f_label)

            # 竖分隔（非最后一个）
            if i < len(key_metrics) - 1:
                sx = pad + (i + 1) * col_w - S(20)
                draw.rectangle([sx, y + S(8), sx + S(1), y + S(50)], fill=(210, 210, 215))

        y += S(76)

    # ── 空间参数：胶囊标签流式布局 ──
    param_items = []
    for label, key, fmt in [
        ("围合度", "enclosure_ratio", "pct"),
        ("窗墙比", "window_wall_ratio", "pct"),
        ("开阔感", "openness_score", "f2"),
        ("亮度", "cv_brightness", "int"),
        ("色温", "cv_color_temperature_K", "intK"),
        ("私密性", "privacy_score", "f2"),
    ]:
        v = features.get(key, features.get(key.replace("cv_", ""), None))
        if v is None or v == -1:
            continue
        if fmt == "pct":
            vs = "{:.0f}%".format(v * 100 if v <= 1 else v)
        elif fmt == "f2":
            vs = "{:.2f}".format(v)
        elif fmt == "int":
            vs = str(int(v))
        elif fmt == "intK":
            vs = "{}K".format(int(v))
        else:
            vs = str(v)
        param_items.append((label, vs))

    if param_items:
        f_pill_label = font(9)
        f_pill_val = font(11, bold=True)
        pill_h = S(28)
        pill_gap = S(10)
        pill_pad_x = S(12)
        pill_bg = lighten(primary, 0.85)  # 主色极浅底
        if rgb_luminance(*pill_bg) < 220:
            pill_bg = lighten(primary, 0.90)

        # 计算每个胶囊宽度（预测量文本）
        pill_data = []
        for label, val in param_items:
            txt = "{}  {}".format(label, val)
            bbox = draw.textbbox((0, 0), txt, font=f_pill_val)
            tw = bbox[2] - bbox[0]
            pill_data.append((label, val, tw + pill_pad_x * 2))

        # 流式排列（自动换行）
        cx = pad
        row_y = y
        for label, val, pw in pill_data:
            if cx + pw > CW - pad:  # 换行
                cx = pad
                row_y += pill_h + S(6)
            # 胶囊背景
            rr(draw, [cx, row_y, cx + pw, row_y + pill_h],
               radius=S(14), fill=pill_bg)
            # 标签 + 数值
            lbl_bbox = draw.textbbox((0, 0), label, font=f_pill_label)
            lbl_w = lbl_bbox[2] - lbl_bbox[0]
            draw.text((cx + pill_pad_x, row_y + S(8)), label,
                      fill=ink3, font=f_pill_label)
            draw.text((cx + pill_pad_x + lbl_w + S(6), row_y + S(6)), val,
                      fill=ink, font=f_pill_val)
            cx += pw + pill_gap

        y = row_y + pill_h + S(16)

    # ── 色彩条 ──
    draw.rectangle([pad, y, CW - pad, y + S(1)], fill=(215, 215, 220))
    y += S(16)

    draw.text((pad, y), "色彩构成", fill=ink, font=f_section)
    y += S(24)

    color_data = []
    for ci in range(1, 4):
        hx = features.get("color_{}_hex".format(ci), "")
        ral = features.get("color_{}_ral".format(ci), "")
        pct = features.get("color_{}_pct".format(ci), 0)
        if hx:
            color_data.append((hx, ral, pct))

    if color_data:
        # 色彩圆点 + 标签行
        dot_r = S(12)
        gap = inner // len(color_data)
        for i, (hx, ral, pct) in enumerate(color_data):
            c = hex_to_rgb(hx)
            dx = pad + i * gap
            # 圆点
            draw.ellipse([dx, y, dx + dot_r * 2, y + dot_r * 2], fill=c)
            # 标签
            tag = ral if ral else hx
            draw.text((dx + dot_r * 2 + S(8), y + S(1)),
                      "{} {}%".format(tag, int(pct)), fill=ink2, font=f_small)
        y += dot_r * 2 + S(8)

        # 色彩条
        bar_h = S(12)
        bx = pad
        for i, (hx, ral, pct) in enumerate(color_data):
            seg = int(inner * pct / 100)
            if i == len(color_data) - 1:
                seg = pad + inner - bx
            c = hex_to_rgb(hx)
            draw.rectangle([bx, y, bx + seg, y + bar_h], fill=c)
            bx += seg
        y += bar_h + S(16)

    # ── 语义构成 ──
    sem_pcts = {}
    for k, v in features.items():
        if k.startswith("sem_") and k.endswith("_pct"):
            sem_pcts[k[4:-4]] = v

    if sem_pcts:
        draw.rectangle([pad, y, CW - pad, y + S(1)], fill=(215, 215, 220))
        y += S(16)
        draw.text((pad, y), "语义构成", fill=ink, font=f_section)
        y += S(24)

        sorted_sem = sorted(sem_pcts.items(), key=lambda x: -x[1])
        sorted_sem = [(k, v) for k, v in sorted_sem if v >= 0.5]  # 隐藏极小项
        total_sem = sum(v for _, v in sorted_sem) if sorted_sem else 1
        row_h = S(28)
        bar_max = inner - S(130)  # 留名字和百分比的空间

        for gn, pct in sorted_sem:
            color = GROUP_PALETTE.get(gn, (150, 150, 150))
            cn = GROUP_CN.get(gn, gn)

            # 名字
            draw.text((pad, y + S(4)), cn, fill=ink2, font=f_bar)
            # 横条 — 无底条，仅彩色填充，按总占比缩放
            bx = pad + S(70)
            bw = max(S(6), int(bar_max * pct / max(total_sem, 1)))
            rr(draw, [bx, y + S(5), bx + bw, y + S(15)],
               radius=S(5), fill=color)
            # 百分比紧跟条后
            draw.text((bx + bw + S(8), y + S(3)),
                      "{:.1f}%".format(pct), fill=ink3, font=f_small)
            y += row_h

        y += S(8)

    # ── 图片区 ──
    draw.rectangle([pad, y, CW - pad, y + S(1)], fill=(215, 215, 220))
    y += S(16)

    imgs = [
        ("seg_overlay.png", "语义分析"),
        ("plan_annotated.png", "平面几何"),
    ]

    img_radius = S(10)  # 图片圆角半径

    for fname, label in imgs:
        fpath = os.path.join(output_dir, fname)
        if not os.path.isfile(fpath):
            continue

        draw.text((pad, y), label, fill=ink3, font=f_label)
        y += S(18)

        thumb = Image.open(fpath).convert("RGB")
        max_w = inner
        max_h = S(260)  # 更紧凑
        ratio = min(max_w / thumb.width, max_h / thumb.height)
        # 宽图优先撑满
        if thumb.width > thumb.height * 1.3:
            ratio = max_w / thumb.width
            if int(thumb.height * ratio) > max_h:
                ratio = max_h / thumb.height

        nw = int(thumb.width * ratio)
        nh = int(thumb.height * ratio)
        thumb = thumb.resize((nw, nh), Image.LANCZOS)

        tx = pad + (inner - nw) // 2

        # 圆角图片 + 淡阴影
        rounded_thumb = round_corners(thumb, img_radius)

        # 画阴影（略偏移的半透明圆角矩形）
        shadow_layer = Image.new("RGBA", card.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow_layer)
        so = S(4)
        sd.rounded_rectangle(
            [tx + so, y + so, tx + nw + so, y + nh + so],
            radius=img_radius, fill=(0, 0, 0, 18))
        card = Image.alpha_composite(card, shadow_layer)
        draw = ImageDraw.Draw(card)  # 需要重新获取 draw

        card.paste(rounded_thumb, (tx, y), rounded_thumb)
        y += nh + S(20)

    # ── 底部 ──
    y += S(4)
    draw.rectangle([pad, y, CW - pad, y + S(1)], fill=(215, 215, 220))
    y += S(12)

    footer = "Space Feature Extractor  ·  {} features".format(
        len([k for k in features if k != "case_name"]))
    draw.text((pad, y), footer, fill=ink3, font=f_tag)

    # 主色小色块作为签名
    for ci, (hx, _, _) in enumerate(color_data[:3]):
        c = hex_to_rgb(hx)
        sx = CW - pad - (3 - ci) * S(18)
        draw.rectangle([sx, y + S(1), sx + S(12), y + S(9)], fill=c)

    y += S(24)

    # 底部色带
    for i in range(band_h):
        t = i / band_h
        r = int(secondary[0] * (1 - t) + primary[0] * t)
        g = int(secondary[1] * (1 - t) + primary[1] * t)
        b = int(secondary[2] * (1 - t) + primary[2] * t)
        draw.rectangle([0, y + i, CW, y + i + 1], fill=(r, g, b))
    y += band_h

    # 裁剪并转回 RGB 保存
    card = card.crop((0, 0, CW, y))
    card_rgb = Image.new("RGB", card.size, bg_base)
    card_rgb.paste(card, mask=card.split()[3] if card.mode == "RGBA" else None)

    card_path = os.path.join(output_dir, "case_card.png")
    card_rgb.save(card_path, quality=95)
    return card_path


# =============================================
#  主入口
# =============================================
def generate_all_visuals(output_dir):
    json_path = os.path.join(output_dir, "features.json")
    if not os.path.isfile(json_path):
        print("  [SKIP] features.json not found in {}".format(output_dir))
        return

    with open(json_path, "r", encoding="utf-8") as fp:
        features = json.load(fp)

    case_name = features.get("case_name", os.path.basename(output_dir))
    print("\n  [Card] Generating visuals for: {}".format(case_name))

    # 1. 语义图 + 图例
    sem_pcts = {}
    for k, v in features.items():
        if k.startswith("sem_") and k.endswith("_pct"):
            sem_pcts[k[4:-4]] = v

    for src, dst in [("seg_overlay.png", "seg_overlay_legend.png"),
                     ("seg_semantic.png", "seg_semantic_legend.png")]:
        src_p = os.path.join(output_dir, src)
        dst_p = os.path.join(output_dir, dst)
        if sem_pcts and os.path.isfile(src_p):
            add_legend_to_segmentation(src_p, dst_p, sem_pcts)
            print("    -> {}".format(dst))

    # 2. 平面图增强
    input_dir = output_dir.replace("/output/", "/input/")
    plan_src = None
    for ext in ["png", "jpg", "jpeg"]:
        p = os.path.join(input_dir, "plan.{}".format(ext))
        if os.path.isfile(p):
            plan_src = p
            break
    if plan_src is None:
        plan_src = os.path.join(output_dir, "plan_binary.png")

    if os.path.isfile(plan_src):
        out = generate_plan_annotated(
            plan_src, os.path.join(output_dir, "plan_annotated.png"), features)
        if out:
            print("    -> plan_annotated.png")

    # 3. 案例卡片
    card = generate_case_card(output_dir, features, case_name)
    if card:
        print("    -> case_card.png")

    print("  [Card] Done: {}".format(case_name))


def batch_generate_cards(output_root):
    if not os.path.isdir(output_root):
        print("Output directory not found: {}".format(output_root))
        return

    cases = [os.path.join(output_root, n) for n in sorted(os.listdir(output_root))
             if os.path.isdir(os.path.join(output_root, n))
             and os.path.isfile(os.path.join(output_root, n, "features.json"))]

    if not cases:
        print("No cases found.")
        return

    print("\n" + "#" * 65)
    print("  Card Generator v3 — {} case(s)".format(len(cases)))
    print("#" * 65)

    for i, d in enumerate(cases):
        print("\n>>> [{}/{}] {}".format(i + 1, len(cases), os.path.basename(d)))
        try:
            generate_all_visuals(d)
        except Exception as e:
            print("  [ERROR] {}".format(e))
            import traceback; traceback.print_exc()

    print("\n" + "#" * 65)
    print("  All cards generated!")
    print("#" * 65)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="案例分析卡片生成器 v3")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--case", default=None)
    args = parser.parse_args()

    target = args.output_dir
    if args.case:
        target = os.path.join(args.output_dir, args.case)

    if os.path.isfile(os.path.join(target, "features.json")):
        generate_all_visuals(target)
    else:
        batch_generate_cards(target)
