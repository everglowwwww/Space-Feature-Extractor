#!/usr/bin/env python3
"""
平面图拆分器 — 将复合共享办公平面图拆分为独立空间单元
================================================================
预处理工具，在主体 Space-Feature-Extractor 流程之前使用。

工作流：
  1. 用户提供一张整体平面图
  2. LLM/AI 分析后生成 split_plan.json（空间单元清单 + 裁切坐标）
  3. 本脚本读取 JSON，自动裁切图片并创建 input 子目录结构

用法:
  # 第一步：生成分析模板（供 LLM 填写）
  python3 plan_splitter.py analyze --image full_plan.png --output split_plan.json

  # 第二步：根据 LLM 填写的 JSON 执行裁切
  python3 plan_splitter.py split --config split_plan.json --input-dir ../input

  # 可选：预览裁切区域（在原图上画框，不实际裁切）
  python3 plan_splitter.py preview --config split_plan.json --output preview.png

split_plan.json 格式:
{
  "source_image": "full_plan.png",
  "case_prefix": "WeWork北京国贸",
  "floor_info": {
    "building": "国贸三期B座",
    "floor": "12F",
    "ceiling_height_m": 3.2,
    "total_area_m2": 850
  },
  "units": [
    {
      "id": "A",
      "type": "开放休闲区",
      "type_en": "open-lounge",
      "description": "左侧大面积开放区域，含沙发、吧台、散座",
      "bbox": [x1, y1, x2, y2],     // 像素坐标 (左上角, 右下角)
      "count": 1,                     // 该类型在整层出现的总数
      "is_representative": true,      // 是否为该类型的代表（选了就裁切）
      "estimated_area_m2": 200,
      "enclosure": "开放"
    },
    ...
  ]
}
"""

import os
import sys
import json
import argparse
from PIL import Image, ImageDraw, ImageFont

# ── 颜色常量 ──────────────────────────────────────
# 每种空间类型一种颜色，用于预览标注
TYPE_COLORS = [
    (230, 76, 60),    # 红
    (46, 134, 193),   # 蓝
    (39, 174, 96),    # 绿
    (241, 196, 15),   # 黄
    (155, 89, 182),   # 紫
    (230, 126, 34),   # 橙
    (52, 73, 94),     # 深蓝灰
    (22, 160, 133),   # 青
]

# ── 字体 ──────────────────────────────────────────
def _find_font():
    """找一个能显示中文的字体"""
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None

_FONT_PATH = _find_font()

def get_font(size):
    if _FONT_PATH:
        return ImageFont.truetype(_FONT_PATH, size, index=0)
    return ImageFont.load_default()


# =============================================
#  analyze: 生成分析模板 JSON
# =============================================
def cmd_analyze(args):
    """生成空的 split_plan.json 模板，供 LLM 填写"""
    image_path = os.path.abspath(args.image)

    if not os.path.isfile(image_path):
        print("错误: 图片文件不存在 — {}".format(image_path))
        sys.exit(1)

    # 获取图片尺寸
    img = Image.open(image_path)
    w, h = img.size

    template = {
        "_instructions": (
            "请 LLM 分析整体平面图，识别出所有功能不同的空间单元，"
            "填写以下字段。bbox 为像素坐标 [x1, y1, x2, y2]，"
            "其中 (x1,y1) 是左上角，(x2,y2) 是右下角。"
            "图片尺寸: {}×{}px。"
            "同质性空间只需选一个代表（is_representative=true），"
            "其他的设为 false。核心筒/交通空间可以不列入。"
        ).format(w, h),
        "source_image": image_path,
        "image_size": [w, h],
        "case_prefix": "案例名前缀（如 WeWork北京国贸）",
        "floor_info": {
            "building": "建筑名称",
            "floor": "楼层",
            "ceiling_height_m": -1,
            "total_area_m2": -1,
        },
        "units": [
            {
                "id": "A",
                "type": "空间类型（中文）",
                "type_en": "space-type-en",
                "description": "空间描述",
                "bbox": [0, 0, 100, 100],
                "count": 1,
                "is_representative": True,
                "estimated_area_m2": -1,
                "enclosure": "开放/半围合/围合/封闭",
            }
        ],
    }

    output_path = args.output or "split_plan.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(template, f, indent=2, ensure_ascii=False)

    print("模板已生成: {}".format(output_path))
    print("图片尺寸: {}×{}px".format(w, h))
    print("")
    print("下一步: 让 LLM 查看平面图并填写 units 列表中的空间单元信息。")
    print("填写完成后运行: python3 plan_splitter.py preview --config {}".format(output_path))


# =============================================
#  preview: 在原图上画裁切框预览
# =============================================
def cmd_preview(args):
    """在原图上画出裁切区域和标签，用于确认"""
    config_path = args.config
    if not os.path.isfile(config_path):
        print("错误: 配置文件不存在 — {}".format(config_path))
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    image_path = config["source_image"]
    if not os.path.isfile(image_path):
        print("错误: 源图片不存在 — {}".format(image_path))
        sys.exit(1)

    img = Image.open(image_path).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    units = config.get("units", [])
    f_label = get_font(max(16, img.width // 50))
    f_small = get_font(max(12, img.width // 70))

    for i, unit in enumerate(units):
        bbox = unit.get("bbox", [0, 0, 100, 100])
        if len(bbox) != 4:
            continue

        x1, y1, x2, y2 = bbox
        color = TYPE_COLORS[i % len(TYPE_COLORS)]
        is_rep = unit.get("is_representative", False)

        # 半透明填充
        fill_alpha = 50 if is_rep else 25
        draw.rectangle([x1, y1, x2, y2], fill=color + (fill_alpha,))

        # 边框（代表性单元用粗线）
        border_w = 4 if is_rep else 2
        draw.rectangle([x1, y1, x2, y2], outline=color + (200,), width=border_w)

        # 标签背景
        uid = unit.get("id", str(i))
        utype = unit.get("type", "未知")
        count = unit.get("count", 1)
        rep_mark = " ★" if is_rep else ""
        label = "{}: {} (×{}){}".format(uid, utype, count, rep_mark)

        lbbox = draw.textbbox((0, 0), label, font=f_label)
        lw = lbbox[2] - lbbox[0]
        lh = lbbox[3] - lbbox[1]
        pad = 4

        # 标签位置（在框内顶部）
        lx = x1 + pad
        ly = y1 + pad

        draw.rectangle(
            [lx - 2, ly - 2, lx + lw + pad, ly + lh + pad],
            fill=color + (180,)
        )
        draw.text((lx, ly), label, fill=(255, 255, 255, 240), font=f_label)

        # 面积估算
        area_text = unit.get("description", "")
        if area_text:
            draw.text((x1 + pad, y2 - f_small.size - pad * 2),
                      area_text[:30], fill=color + (180,), font=f_small)

    # 合成
    result = Image.alpha_composite(img, overlay).convert("RGB")

    output_path = args.output or "split_preview.png"
    result.save(output_path, quality=95)
    print("预览图已生成: {}".format(output_path))

    # 打印摘要
    reps = [u for u in units if u.get("is_representative", False)]
    total = sum(u.get("count", 1) for u in units)
    print("")
    print("空间单元总数: {} 类, 共计 {} 个".format(len(units), total))
    print("将裁切的代表性单元: {} 个".format(len(reps)))
    for u in reps:
        bbox = u.get("bbox", [])
        print("  {} [{}]: {} — bbox={}".format(
            u.get("id", "?"), u.get("type", "?"),
            u.get("description", "")[:40], bbox))


# =============================================
#  split: 执行裁切并生成 input 目录结构
# =============================================
def cmd_split(args):
    """根据配置裁切图片，生成 input 子目录"""
    config_path = args.config
    if not os.path.isfile(config_path):
        print("错误: 配置文件不存在 — {}".format(config_path))
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    image_path = config["source_image"]
    if not os.path.isfile(image_path):
        print("错误: 源图片不存在 — {}".format(image_path))
        sys.exit(1)

    img = Image.open(image_path).convert("RGB")
    iw, ih = img.size

    input_dir = os.path.abspath(args.input_dir)
    os.makedirs(input_dir, exist_ok=True)

    prefix = config.get("case_prefix", "案例")
    floor_info = config.get("floor_info", {})
    ceiling_h = floor_info.get("ceiling_height_m", -1)

    units = config.get("units", [])
    reps = [u for u in units if u.get("is_representative", True)]

    if not reps:
        print("没有标记为 is_representative=true 的空间单元，无内容可裁切。")
        return

    print("")
    print("=" * 60)
    print("  平面图拆分器 — 裁切 {} 个代表性空间单元".format(len(reps)))
    print("=" * 60)

    created = []

    for unit in reps:
        uid = unit.get("id", "X")
        utype = unit.get("type", "未知")
        utype_en = unit.get("type_en", "unknown")
        bbox = unit.get("bbox", [0, 0, iw, ih])

        if len(bbox) != 4:
            print("  [SKIP] {}: bbox 格式不正确".format(uid))
            continue

        x1, y1, x2, y2 = bbox

        # 边界检查和修正
        x1 = max(0, min(x1, iw))
        y1 = max(0, min(y1, ih))
        x2 = max(0, min(x2, iw))
        y2 = max(0, min(y2, ih))

        if x2 <= x1 or y2 <= y1:
            print("  [SKIP] {}: bbox 面积为 0".format(uid))
            continue

        # 加一点边距（5%），让裁切图有上下文
        margin_x = int((x2 - x1) * 0.05)
        margin_y = int((y2 - y1) * 0.05)
        x1m = max(0, x1 - margin_x)
        y1m = max(0, y1 - margin_y)
        x2m = min(iw, x2 + margin_x)
        y2m = min(ih, y2 + margin_y)

        # 裁切
        cropped = img.crop((x1m, y1m, x2m, y2m))

        # 目录名
        folder_name = "{}_{}_{}".format(prefix, uid, utype)
        # 清理文件名中的特殊字符
        folder_name = folder_name.replace("/", "-").replace("\\", "-")
        case_dir = os.path.join(input_dir, folder_name)
        os.makedirs(case_dir, exist_ok=True)

        # 保存裁切后的平面图
        plan_path = os.path.join(case_dir, "plan.png")
        cropped.save(plan_path, quality=95)

        # 生成单元信息文件（预填层高等共享信息）
        unit_info = {
            "_source": "plan_splitter 自动生成",
            "source_plan": os.path.basename(image_path),
            "unit_id": uid,
            "unit_type": utype,
            "unit_type_en": utype_en,
            "description": unit.get("description", ""),
            "bbox_in_source": bbox,
            "count_in_floor": unit.get("count", 1),
            "estimated_area_m2": unit.get("estimated_area_m2", -1),
            "enclosure": unit.get("enclosure", ""),
            "ceiling_height_m": ceiling_h,
            "floor_info": floor_info,
        }
        info_path = os.path.join(case_dir, "unit_info.json")
        with open(info_path, "w", encoding="utf-8") as f:
            json.dump(unit_info, f, indent=2, ensure_ascii=False)

        print("  [OK] {} → {}".format(uid, folder_name))
        print("       plan.png: {}×{}px, unit_info.json".format(
            cropped.width, cropped.height))
        created.append(folder_name)

    # 保存整体平面图的副本（供参考）
    full_plan_dest = os.path.join(input_dir, "_整体平面图_{}.png".format(prefix))
    if not os.path.isfile(full_plan_dest):
        img.save(full_plan_dest, quality=95)
        print("\n  整体平面图副本: {}".format(os.path.basename(full_plan_dest)))

    print("\n" + "=" * 60)
    print("  完成! 已创建 {} 个案例目录:".format(len(created)))
    for name in created:
        print("    input/{}/".format(name))
    print("")
    print("  下一步:")
    print("  1. 给每个目录补充对应的人视角透视照 (photo_01.png)")
    print("  2. 运行主体分析流程:")
    print("     python3 batch_analyze.py --input-dir {} --output-dir ../output".format(
        input_dir))
    print("=" * 60)


# =============================================
#  主入口
# =============================================
def main():
    parser = argparse.ArgumentParser(
        description="平面图拆分器 — 将复合平面图拆分为独立空间单元",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 1. 生成分析模板
  python3 plan_splitter.py analyze --image full_plan.png

  # 2. LLM 填写 split_plan.json 后，预览裁切区域
  python3 plan_splitter.py preview --config split_plan.json

  # 3. 确认后执行裁切
  python3 plan_splitter.py split --config split_plan.json --input-dir ../input
        """)
    sub = parser.add_subparsers(dest="command")

    # analyze
    p_analyze = sub.add_parser("analyze", help="生成分析模板 JSON")
    p_analyze.add_argument("--image", required=True, help="整体平面图路径")
    p_analyze.add_argument("--output", default="split_plan.json", help="输出 JSON 路径")

    # preview
    p_preview = sub.add_parser("preview", help="预览裁切区域")
    p_preview.add_argument("--config", required=True, help="split_plan.json 路径")
    p_preview.add_argument("--output", default="split_preview.png", help="预览图输出路径")

    # split
    p_split = sub.add_parser("split", help="执行裁切，生成 input 目录结构")
    p_split.add_argument("--config", required=True, help="split_plan.json 路径")
    p_split.add_argument("--input-dir", required=True, help="input 目录路径")

    args = parser.parse_args()

    if args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "preview":
        cmd_preview(args)
    elif args.command == "split":
        cmd_split(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
