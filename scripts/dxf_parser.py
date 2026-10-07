# -*- coding: utf-8 -*-
"""
dxf_parser.py — 阶段A的几何权威解析器
======================================

定位
----
在空间特征提取管线（Space-Feature-Extractor）中，
阶段A由 LLM 多模态理解负责"语义数据"（色彩/材质/光环境/感知评分），
本脚本负责"几何数据"（空间长宽、净面积、周长、围合度、家具尺寸与数量）。

当案例提供 DXF 文件时，DXF 是尺度数据的权威来源（误差±0），
LLM 纯粹基于图像的"家具标定法"估算容易产生 ±10~22% 的偏差
（实测 DeepSeek 视觉模型将该案例面积低估 22%）。

依赖
----
- 必需：ezdxf（+ Python 标准库）。
- 可选：numpy + opencv（含 cv2）。用于"围合墙体内净面积"的计算（栅格化 + 轮廓）。
  若缺 opencv，净面积回退为外包矩形面积（精度降级，但仍可运行）。

设计要点
--------
1. 从 DXF 图层语义分类几何体：墙体 / 桌子 / 椅子 / 柜子 / 虚线(开放边界)。
2. 墙体层按"最小外接矩形 OBB"的较长边求和 => 墙总长（用于围合度）。
3. 支撑面：外包矩形 => 长宽 / 周长；净面积采用"内圈孔洞多边形面积"
   （排除 L 形凹口与墙厚），开放空间回退外圈轮廓面积（见 compute_enclosed_area）。
4. 家具层逐件 OBB 提取尺寸，按 "短边×长边" 聚类分组，输出 count/尺寸/占地。
5. 合并进 llm_understanding.json：覆盖几何字段，保留 LLM 语义字段。

用法
----
# 单文件：解析 DXF，仅打印指标（不写文件）
python dxf_parser.py --dxf "DXF 北京 盈科中心-5.dxf" --verbose

# 合并：解析 DXF 并把几何字段覆盖进 llm_understanding.json
python dxf_parser.py --dxf "DXF 北京 盈科中心-5.dxf" \
    --llm-json "llm_understanding.json" --out "llm_understanding.json"

# 预览合并效果（dry-run，不写文件）
python dxf_parser.py --dxf "dxf.dxf" --llm-json "llm.json" --dry-run --verbose
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

try:
    import ezdxf
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "[dxf_parser] 需要 ezdxf 库。请先安装：pip install ezdxf\n"
    )
    raise

# ---------------------------------------------------------------------------
# 常量与配置
# ---------------------------------------------------------------------------

# 图层关键词 -> 语义类别
# 顺序即优先级；匹配用"图层名包含关键词"。
LAYER_RULES: List[Tuple[str, str]] = [
    ("墙", "wall"),
    ("柜", "cabinet"),
    ("桌", "table"),
    ("椅", "chair"),
    ("虚线", "virtual"),      # 开放/虚拟边界（非实体墙）
    ("虚", "virtual"),
    ("窗", "window"),
    ("门", "door"),
]

# 楼层默认单位假设（米）
METERS_UNIT = 6

# 家具尺寸聚类容差（米）：在 ±tol 内视为同一组
SIZE_CLUSTER_TOL = 0.02

# 默认墙体厚度（仅当墙体未如实表达厚度时用于净面积估算，供参考）
DEFAULT_WALL_THICKNESS_M = 0.20

Point = Tuple[float, float]


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class DxfMetrics:
    """DXF 解析出的几何指标。"""
    unit: int = METERS_UNIT                          # $INSUNITS
    unit_name: str = "Meters"
    layer_summary: dict = field(default_factory=dict)   # {图层中文: 实体数}
    # 空间外包（长边 / 短边 均取外包矩形：长边=length，短边=width）
    length_m: float = 0.0
    width_m: float = 0.0
    outer_area_m2: float = 0.0
    perimeter_m: float = 0.0
    # 墙体
    wall_total_length_m: float = 0.0
    wall_segments: int = 0
    wall_area_m2: float = 0.0
    enclosure_ratio: float = 0.0
    # 围合墙体内净面积（内圈孔洞多边形面积；开放空间则回退外圈轮廓面积）
    net_area_m2: float = 0.0
    area_method: str = ""        # 'enclosed' | 'outer' | ''(回退外包矩形)
    # 开放（虚拟）边界
    virtual_edge_length_m: float = 0.0
    virtual_bbox_length_m: float = 0.0   # 虚线段 OBB 长边（与墙体一致口径，用于围合度）
    # 家具
    furniture: List[dict] = field(default_factory=list)  # 见 make_furniture_group
    furniture_count: int = 0
    furniture_footprint_m2: float = 0.0

    def dict(self) -> dict:
        return {
            "unit": self.unit,
            "unit_name": self.unit_name,
            "layer_summary": self.layer_summary,
            "length_m": round(self.length_m, 3),
            "width_m": round(self.width_m, 3),
            "outer_area_m2": round(self.outer_area_m2, 3),
            "net_area_m2": round(self.net_area_m2, 3),
            "area_method": self.area_method,
            "perimeter_m": round(self.perimeter_m, 3),
            "wall_total_length_m": round(self.wall_total_length_m, 3),
            "wall_segments": self.wall_segments,
            "wall_area_m2": round(self.wall_area_m2, 3),
            "enclosure_ratio": round(self.enclosure_ratio, 4),
            "virtual_edge_length_m": round(self.virtual_edge_length_m, 3),
            "virtual_bbox_length_m": round(self.virtual_bbox_length_m, 3),
            "furniture_count": self.furniture_count,
            "furniture_footprint_m2": round(self.furniture_footprint_m2, 3),
            "furniture": self.furniture,
        }


# ---------------------------------------------------------------------------
# 纯几何工具（仅标准库 + math）
# ---------------------------------------------------------------------------

def cross(o: Point, a: Point, b: Point) -> float:
    """二维叉积 (a-o)×(b-o)。"""
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def convex_hull(points: Sequence[Point]) -> List[Point]:
    """Andrew's monotone chain 凸包（返回逆时针边界，不含共线中间点）。"""
    pts = sorted({(round(x, 6), round(y, 6)) for x, y in points})
    if len(pts) <= 1:
        return pts
    lower: List[Point] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: List[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def min_area_rect(points: Sequence[Point]) -> Tuple[float, float, float, float]:
    """
    计算点集的最小外接矩形 (short, long, area, angle_rad)。

    short/long 为矩形短边/长边；area 为矩形面积；angle 为长轴与X轴夹角。
    对任意朝向的多边形（含倾斜家具/墙体）都有效。
    """
    hull = convex_hull(points)
    n = len(hull)
    if n == 0:
        return 0.0, 0.0, 0.0, 0.0
    if n < 3:
        xs = [p[0] for p in hull]
        ys = [p[1] for p in hull]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        s, l = sorted((w, h))
        return s, l, s * l, 0.0

    best: Optional[Tuple[float, float, float, float]] = None
    for i in range(n):
        p1 = hull[i]
        p2 = hull[(i + 1) % n]
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        ang = math.atan2(dy, dx)
        ca = math.cos(-ang)
        sa = math.sin(-ang)
        minx = miny = float("inf")
        maxx = maxy = float("-inf")
        for x, y in hull:
            rx = x * ca - y * sa
            ry = x * sa + y * ca
            if rx < minx:
                minx = rx
            if rx > maxx:
                maxx = rx
            if ry < miny:
                miny = ry
            if ry > maxy:
                maxy = ry
        w = maxx - minx
        h = maxy - miny
        area = w * h
        if best is None or area < best[2]:
            best = (w, h, area, ang)

    w, h, area, ang = best  # type: ignore[misc]
    short, long = sorted((w, h))
    return short, long, area, ang


def polygon_length(pts: List[Point]) -> float:
    """顺序点列的总边长（首尾闭合）。"""
    if len(pts) < 2:
        return 0.0
    total = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        total += math.hypot(x2 - x1, y2 - y1)
    return total


def bbox_of_points(pts: Iterable[Point]) -> Tuple[float, float, float, float]:
    """(w, h, minx, miny) 轴对齐包围盒。"""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    return maxx - minx, maxy - miny, minx, miny


# ---------------------------------------------------------------------------
# DXF 读取与实体提取
# ---------------------------------------------------------------------------

def classify_layer(layer_name: str) -> Optional[str]:
    """根据图层名返回语义类别，匹配不到返回 None。"""
    ln = (layer_name or "").lower()
    for kw, cat in LAYER_RULES:
        if kw in ln:
            return cat
    return None


def polyline_vertices(e) -> List[Point]:
    """提取 POLYLINE / LWPOLYLINE 顶点（msp 实体）。"""
    pts: List[Point] = []
    t = e.dxftype()
    if t == "LWPOLYLINE":
        for item in e.get_points():
            pts.append((float(item[0]), float(item[1])))
    elif t == "POLYLINE":
        for v in e.vertices:
            loc = v.dxf.location
            pts.append((float(loc.x), float(loc.y)))
    elif t == "LINE":
        s = e.dxf.start
        en = e.dxf.end
        pts = [(float(s.x), float(s.y)), (float(en.x), float(en.y))]
    return pts


def load_dxf(path: str):
    """读取 DXF 并返回 (doc, msp)。带单位警告。"""
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    return doc, msp


def get_unit_name(unit: int) -> str:
    if unit == METERS_UNIT:
        return "Meters"
    if unit == 4:
        return "Millimeters"
    if unit == 1:
        return "Inches"
    if unit == 2:
        return "Feet"
    return f"UNKNOWN({unit})"


# ---------------------------------------------------------------------------
# 指标计算
# ---------------------------------------------------------------------------

def make_furniture_group(layer: str, count: int,
                         short: float, long: float) -> dict:
    """构造单组家具条目。footprint 为单件占地。"""
    return {
        "type": f"{layer} {short:.2f}×{long:.2f}",
        "layer": layer,
        "count": count,
        "dimensions_m": f"{short:.2f}×{long:.2f}",
        "footprint_m2": round(short * long, 3),
        "seats": 0,              # 语义字段，DXF 无法得知，交由 LLM/mapper 填充
        "material": "",          # 语义字段
    }


def cluster_furniture(items: List[Tuple[float, float, str]]) -> List[dict]:
    """
    家具聚类：按 (short, long) 在容差内归为同一组。
    items: [(short, long, layer)]，逐件 OBB 结果。
    """
    groups: dict = {}
    for short, long, layer in items:
        key = (round(short / SIZE_CLUSTER_TOL), round(long / SIZE_CLUSTER_TOL))
        groups.setdefault(key, {"layer": layer, "count": 0,
                                "s_sum": 0.0, "l_sum": 0.0})
        g = groups[key]
        g["count"] += 1
        g["s_sum"] += short
        g["l_sum"] += long

    out: List[dict] = []
    for g in groups.values():
        short = g["s_sum"] / g["count"]
        long = g["l_sum"] / g["count"]
        out.append(make_furniture_group(g["layer"], g["count"], short, long))
    return out


def compute_metrics(doc, msp) -> DxfMetrics:
    """从 modelspace 计算全部几何指标。"""
    unit = int(doc.header.get("$INSUNITS", METERS_UNIT))
    m = DxfMetrics(unit=unit, unit_name=get_unit_name(unit))

    walls: List[List[Point]] = []
    virtual_edges: List[List[Point]] = []
    furniture_items: List[Tuple[float, float, str]] = []
    furniture_count_total = 0

    # 按语义类别收集
    for e in msp:
        t = e.dxftype()
        if t not in ("POLYLINE", "LWPOLYLINE", "LINE"):
            continue
        try:
            layer_name = e.dxf.get("layer", "")
        except Exception:
            layer_name = ""
        cat = classify_layer(layer_name)
        pts = polyline_vertices(e)
        if not pts:
            continue
        m.layer_summary[layer_name] = m.layer_summary.get(layer_name, 0) + 1

        if cat == "wall":
            walls.append(pts)
        elif cat == "virtual":
            virtual_edges.append(pts)
        elif cat in ("table", "chair", "cabinet"):
            short, long, area, _ = min_area_rect(pts)
            furniture_items.append((short, long, layer_name))
            furniture_count_total += 1

    m.wall_segments = len(walls)

    # --- 墙体总长：每段墙 OBB 的"较长边"之和 ---
    wall_total = 0.0
    wall_area = 0.0
    all_wall_pts: List[Point] = []
    for pts in walls:
        short, long, area, _ = min_area_rect(pts)
        wall_total += long                      # 长边 = 墙的走向长度
        wall_area += short * long               # 墙带面积
        all_wall_pts.extend(pts)
    m.wall_total_length_m = wall_total
    m.wall_area_m2 = wall_area

    # --- 外包矩形（用墙体顶点为主，缺失时回退到全部实体顶点）---
    extent_pts = list(all_wall_pts)
    if not extent_pts:
        for e in msp:
            if e.dxftype() in ("POLYLINE", "LWPOLYLINE", "LINE"):
                extent_pts.extend(polyline_vertices(e))

    if extent_pts:
        w, h, _, _ = bbox_of_points(extent_pts)
        length, width = sorted((w, h), reverse=True)
        m.length_m = length
        m.width_m = width
        m.outer_area_m2 = length * width
        m.perimeter_m = 2.0 * (length + width)

    # --- 开放边界（虚线）长度：OBB 长边口径（与墙体一致），用于围合度 ---
    virtual_bbox = 0.0
    for pts in virtual_edges:
        vs, vl, _va, _ang = min_area_rect(pts)
        virtual_bbox += vl
    m.virtual_bbox_length_m = virtual_bbox
    m.virtual_edge_length_m = sum(polygon_length(p) for p in virtual_edges)

    # --- 围合度 = 墙长 / (墙长 + 虚线长)，恒 ∈ [0,1] ---
    denom = wall_total + virtual_bbox
    if denom > 0:
        m.enclosure_ratio = wall_total / denom

    # --- 家具 ---
    m.furniture = cluster_furniture(furniture_items)
    m.furniture_count = furniture_count_total
    m.furniture_footprint_m2 = round(
        sum(g["count"] * g["footprint_m2"] for g in m.furniture), 3
    )

    # --- 围合墙体内净面积（主算法：内圈孔洞多边形；开放空间回退外圈轮廓）---
    m.net_area_m2, m.area_method = compute_enclosed_area(walls, virtual_edges)
    if m.area_method == "":
        m.net_area_m2 = m.outer_area_m2   # 无法用轮廓时回退到外包矩形

    # --- 安全网：净面积不可能小于家具占地（否则面积明显算错）→ 退回外包矩形作保守足迹 ---
    if m.net_area_m2 > 0 and m.furniture_footprint_m2 > 0 and m.net_area_m2 < m.furniture_footprint_m2:
        m.net_area_m2 = round(m.outer_area_m2, 2)
        m.area_method = "bbox"   # 标记：退回外包矩形（近似足迹，需人工复核）

    return m


def compute_enclosed_area(wall_polys, virtual_polys, px_per_m=120.0):
    """计算"围合墙体内净面积"。

    思路：栅格化 墙体 + 虚线(开放边界) 带多边形 → 形态学闭运算桥接小缺口 →
          RETR_CCOMP 找"内部孔洞"（墙带围出的封闭区域）→ 取最大孔洞的多边形面积。
    - 有孔洞（封闭房间）  => 面积 = 孔洞多边形面积（自动排除 L 形凹口与墙厚），method='enclosed'
    - 无孔洞（开放空间）  => 回退外圈轮廓面积，method='outer'
    - 无几何/缺 cv2       => (0, '')，调用方回退到外包矩形
    """
    try:
        import numpy as np
        import cv2
    except ImportError:
        return 0.0, ""

    polys = list(wall_polys or []) + list(virtual_polys or [])
    pts = [pt for poly in polys for pt in poly]
    if not pts:
        return 0.0, ""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if max(x1 - x0, y1 - y0) <= 0:
        return 0.0, ""

    scale = px_per_m / max(x1 - x0, y1 - y0)          # 像素/米
    W = int(round((x1 - x0) * scale)) + 40
    H = int(round((y1 - y0) * scale)) + 40

    def to_px(x, y):
        return int(round((x - x0) * scale)) + 20, int(round((y1 - y) * scale)) + 20

    canvas = np.zeros((H, W), np.uint8)
    for poly in polys:
        arr = np.array([to_px(x, y) for x, y in poly], np.int32)
        cv2.fillPoly(canvas, [arr], 255)

    # 闭运算桥接虚线/小缺口（约 0.8m）
    k = max(3, int(round(0.8 * scale)))
    if k % 2 == 0:
        k += 1
    closed = cv2.morphologyEx(canvas, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))

    cnts, hier = cv2.findContours(closed, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    m2_per_px2 = (1.0 / scale) * (1.0 / scale)

    holes = []
    if hier is not None:
        for i, c in enumerate(cnts):
            if hier[0][i][3] != -1 and cv2.contourArea(c) > 0:   # 子轮廓 = 孔洞
                holes.append(c)
    hole_area = 0.0
    if holes:
        best = max(holes, key=cv2.contourArea)
        hole_area = cv2.contourArea(best) * m2_per_px2
    bbox_area = (x1 - x0) * (y1 - y0)
    # 合理性校验：封闭房间的封闭区应接近其外包（通常 ≥ 外包的 30~40%）。
    # 若封闭区远小于外包（≤ 外包 30%），说明房间大概率未闭合/泄漏，圈到的只是小的家具内腔
    # （如 互联网金融中心-03 被误算成 3.91㎡），此时应回退到外圈足迹，而不是误标 enclosed。
    if hole_area > 0 and bbox_area > 0 and hole_area >= 0.3 * bbox_area:
        return hole_area, "enclosed"

    # 兜底：开放空间（无闭合孔洞，或封闭区过小不可信）。用逐步加大的桥接核把零散墙段连成外圈，
    # 取最大的外圈填充面积作为"房间足迹"近似（尽量接近外轮廓，避免退化成小团）。
    best_outer = 0.0
    for bridge in (1.5, 2.5, 4.0):
        k = max(3, int(round(bridge * scale)))
        if k % 2 == 0:
            k += 1
        closed2 = cv2.morphologyEx(canvas, cv2.MORPH_CLOSE, np.ones((k, k), np.uint8))
        cnts2, _ = cv2.findContours(closed2, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts2:
            big = max(cnts2, key=cv2.contourArea)
            mask = np.zeros_like(closed2)
            cv2.drawContours(mask, [big], -1, 255, -1)
            best_outer = max(best_outer, int((mask > 0).sum()) * m2_per_px2)
    if best_outer > 0:
        return best_outer, "outer"

    return 0.0, ""


# ---------------------------------------------------------------------------
# 合并进 llm_understanding.json
# ---------------------------------------------------------------------------

def parse_dims_str(s) -> Optional[Tuple[float, float]]:
    """从 "1.00×2.00" / "直径1.2" / "半径0.6" 解析出 (short, long)。无法解析返回 None（不崩溃）。"""
    if not s:
        return None
    s = str(s).strip().replace("×", "x").replace("X", "x").replace("*", "x").replace("，", "x")
    # 圆桌/圆形：直径1.2 / D1.2 / dia=1.2 / 半径0.6 / r0.6 → (d, d) 或 (2r, 2r)
    m = re.match(r"^\s*(?:直径|直径\s*[:=]?|半径|d|dia\.?|r)\s*([\d.]+)\s*(?:m|米)?$", s, re.I)
    if m:
        val = float(m.group(1))
        if s.lower().startswith(("半", "半径", "r")):
            return round(val * 2, 3), round(val * 2, 3)
        return val, val
    parts = []
    for p in s.split("x"):
        p = p.strip()
        if not p:
            continue
        try:
            parts.append(float(p))
        except ValueError:
            return None
    if len(parts) != 2:
        return None
    a, b = sorted(parts)
    return a, b


def match_llm_furniture(llm_groups: List[dict],
                        dxf_groups: List[dict],
                        tol: float = 0.06) -> dict:
    """
    返回 {dxf_index: llm_group} 映射：把 DXF 组与 LLM 组按尺寸匹配，
    以便借用 LLM 的语义字段（type/material/seats）。
    """
    used_llm = set()
    mapping: dict = {}
    for di, dg in enumerate(dxf_groups):
        try:
            ds = float(dg["dimensions_m"].split("×")[0])
            dl = float(dg["dimensions_m"].split("×")[1])
        except Exception:
            continue
        for li, lg in enumerate(llm_groups):
            if li in used_llm:
                continue
            pair = parse_dims_str(lg.get("dimensions_m"))
            if pair is None:
                continue
            if abs(pair[0] - ds) <= tol and abs(pair[1] - dl) <= tol:
                mapping[di] = lg
                used_llm.add(li)
                break
    return mapping


def merge_into_llm(llm: dict, m: DxfMetrics, apply_height: bool = True) -> dict:
    """
    把 DXF 几何字段合并进 llm_understanding.json，返回合并后的 dict。
    - 覆盖：空间绝对尺度 / 围护结构(perimeter,enclosure) / 空间比例 / 家具几何
    - 保留：色彩材质 / 光环境 / 感知评分 / 语义字段(num_windows等)
    """
    # --- _meta ---
    meta = llm.setdefault("_meta", {})
    meta["source"] = "DXF精确解析 + 多模态LLM空间理解"
    meta["method"] = (
        "尺度数据来自DXF精确解析（ezdxf, 单位=米, $INSUNITS=%d）；"
        "语义数据来自LLM视觉分析透视照" % m.unit
    )
    meta["scale_calibration"] = {
        "reference_object": "DXF文件（精确几何坐标，单位=米，$INSUNITS=%d）" % m.unit,
        "reference_real_size_m": None,
        "reference_pixel_size_avg": None,
        "scale_m_per_px": None,
        "cross_validation": [
            "DXF图层结构：%s" % "、".join(
                "%s(%s段)" % (k, v) for k, v in m.layer_summary.items()
            ),
            "空间尺寸 DXF=%.2f×%.2fm" % (m.length_m, m.width_m),
        ],
    }
    meta["confidence_note"] = (
        "尺度数据精度±0，来自DXF精确坐标。围合度基于DXF图层："
        "墙体层总长%.2fm/总周长%.2fm=%.2f。净面积采用%s（内圈孔洞多边形=排除凹口与墙厚；"
        "外圈轮廓=开放空间兜底）。语义数据来自LLM视觉分析，精度受图片质量影响。"
        % (m.wall_total_length_m, m.perimeter_m, m.enclosure_ratio, m.area_method)
    )
    meta["area_method"] = m.area_method

    # --- 空间绝对尺度 ---
    scale = llm.setdefault("空间绝对尺度", {})
    scale["length_m"] = round(m.length_m, 2)
    scale["width_m"] = round(m.width_m, 2)
    scale["net_floor_area_m2"] = round(m.net_area_m2, 2)
    # ceiling height 与 volume 是 LLM 语义字段，仅在缺失或 apply_height 时处理
    if not apply_height:
        ceiling = scale.get("ceiling_height_m", 2.9)
        scale["ceiling_height_m"] = ceiling
    if scale.get("ceiling_height_m") and scale.get("net_floor_area_m2"):
        scale["volume_m3"] = round(
            scale["ceiling_height_m"] * scale["net_floor_area_m2"], 2
        )

    # --- 围护结构 ---
    shell = llm.setdefault("围护结构", {})
    shell["perimeter_m"] = round(m.perimeter_m, 2)
    shell["enclosure_ratio"] = round(m.enclosure_ratio, 2)

    # --- 空间比例 ---
    ratio = llm.setdefault("空间比例", {})
    if scale.get("length_m") and scale.get("width_m"):
        ratio["length_width_ratio"] = round(
            scale["length_m"] / scale["width_m"], 2
        )
    if scale.get("ceiling_height_m") and scale.get("width_m"):
        ratio["height_width_ratio"] = round(
            scale["ceiling_height_m"] / scale["width_m"], 2
        )

    # --- 家具配置（DXF 权威几何 + 借用 LLM 语义）---
    furn = llm.setdefault("家具配置", {})
    llm_groups = furn.get("furniture_groups", []) or []
    mapping = match_llm_furniture(llm_groups, m.furniture)

    new_groups: List[dict] = []
    for di, dg in enumerate(m.furniture):
        newg = dict(dg)
        lg = mapping.get(di)
        if lg:
            # 借用 LLM 语义字段
            if lg.get("type"):
                newg["type"] = lg["type"]
            newg["material"] = lg.get("material", "")
            newg["seats"] = lg.get("seats", 0)
            if lg.get("material_zh"):
                newg["material_zh"] = lg["material_zh"]
        else:
            # 无法匹配，用 DXF 生成名，按图层推断 seats
            newg["seats"] = 1 if "椅" in dg.get("layer", "") else 0
        new_groups.append(newg)
    furn["furniture_groups"] = new_groups
    furn["total_furniture_footprint_m2"] = round(m.furniture_footprint_m2, 2)
    # 总座位保留 LLM 语义（若存在），否则按椅类 count 推断
    total_seats = furn.get("total_seats")
    if not total_seats:
        total_seats = sum(g.get("seats", 0) for g in new_groups)
    furn["total_seats"] = total_seats
    if scale.get("net_floor_area_m2"):
        furn["furniture_density"] = round(
            m.furniture_footprint_m2 / scale["net_floor_area_m2"], 2
        )
        if furn["total_seats"]:
            furn["seating_density_per_m2"] = round(
                furn["total_seats"] / scale["net_floor_area_m2"], 2
            )

    return llm


# ---------------------------------------------------------------------------
# 主流程 / CLI
# ---------------------------------------------------------------------------

def pipeline(dxf_path: str) -> DxfMetrics:
    """解析 DXF；文件非 DXF 或损坏时抛出带说明的异常。"""
    if not os.path.exists(dxf_path):
        raise FileNotFoundError("[dxf_parser] 找不到 DXF 文件：%s" % dxf_path)
    try:
        doc, msp = load_dxf(dxf_path)
    except IOError:
        raise ValueError(
            "[dxf_parser] '%s' 不是有效 DXF 文件。请确认是 .dxf 格式"
            "（DWG 是二进制私有格式，须先在 CAD 里'另存为 → DXF'）。" % dxf_path
        )
    return compute_metrics(doc, msp)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="DXF 空间几何解析")
    p.add_argument("--dxf", required=True, help="输入 DXF 文件路径")
    p.add_argument("--llm-json", "-J", default=None,
                   help="llm_understanding.json 路径（合并时使用）")
    p.add_argument("--out", "-o", default=None,
                   help="输出 JSON 路径（默认覆盖 llm_json；仅 dry-run 不写）")
    p.add_argument("--dry-run", action="store_true",
                   help="只打印合并预览，不写文件")
    p.add_argument("--verbose", "-v", action="store_true", help="打印详细指标")
    p.add_argument("--no-height", action="store_true",
                   help="不强制重算层高/体积（保留 LLM 语义层高）")
    args = p.parse_args(argv)

    m = pipeline(args.dxf)

    if args.verbose:
        d = m.dict()
        print("=== 单位 ===", m.unit_name, "(INSUNITS=%d)" % m.unit)
        print("=== 图层分布 ===")
        for k, v in m.layer_summary.items():
            print("   %s: %d" % (k, v))
        print("=== 空间几何 ===")
        print("   外包长×宽 = %.2f × %.2f m" % (m.length_m, m.width_m))
        print("   外包面积 = %.2f m²" % m.outer_area_m2)
        print("   外周长   = %.2f m" % m.perimeter_m)
        print("=== 墙体 ===")
        print("   墙段数   = %d，墙总长 = %.2f m" % (m.wall_segments, m.wall_total_length_m))
        print("   墙体面积 = %.2f m²" % m.wall_area_m2)
        print("   围合度   = %.2f" % m.enclosure_ratio)
        print("   开放边界长度 = %.2f m" % m.virtual_edge_length_m)
        print("=== 家具 ===")
        print("   总件数   = %d，总占地 = %.2f m²" % (m.furniture_count, m.furniture_footprint_m2))
        for g in m.furniture:
            print("   [%s] %s × %s  count=%d  footprint=%.3f"
                  % (g["layer"], g["dimensions_m"].split("×")[0],
                     g["dimensions_m"].split("×")[1], g["count"], g["footprint_m2"]))

    # 合并
    if args.llm_json:
        if not os.path.exists(args.llm_json):
            sys.stderr.write("[dxf_parser] 找不到 llm-json: %s\n" % args.llm_json)
            return 2
        with open(args.llm_json, "r", encoding="utf-8") as f:
            llm = json.load(f)
        merged = merge_into_llm(llm, m, apply_height=not args.no_height)

        if args.dry_run:
            print("=== 合并预览（dry-run）===")
            print(json.dumps(merged, ensure_ascii=False, indent=2))
        else:
            out = args.out or args.llm_json
            with open(out, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            print("[dxf_parser] 已合并几何字段 ->", out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
