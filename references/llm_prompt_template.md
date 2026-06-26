# LLM 多模态空间理解 — Prompt 模板

## 使用方式

当需要执行阶段 A 时，你（LLM）同时查看用户提供的平面图和透视照，然后按照下面的 JSON Schema 输出结构化空间数据。输出的 JSON 直接保存为 `llm_understanding.json`。

## 核心方法：家具标定法

由于平面图通常没有标注尺寸，需要通过图中可识别的标准尺寸家具来反推比例尺：

1. 在平面图中找到至少 2 个可识别的标准家具（如单人椅、双人沙发、办公桌等）
2. 测量该家具在图中的像素宽度
3. 查阅标准尺寸，计算 m/px 比例
4. 用另一个家具交叉验证（误差应 < 15%）
5. 用该比例尺推算空间整体尺寸

常见家具标准尺寸参考：
- 单人休闲椅：座宽 0.65-0.75m
- 双人沙发：总长 1.4-1.6m
- 三人沙发：总长 2.0-2.4m
- 标准办公桌：1.2-1.6m × 0.6-0.8m
- 会议桌（6人）：1.8-2.4m × 0.9-1.0m
- 茶几：1.0-1.5m × 0.5-0.6m
- 标准门宽：0.9m（单扇）/ 1.2-1.5m（双扇）

## JSON Schema

输出必须严格遵循以下结构。所有物理量使用真实单位（米、平方米、K、lux 等）。不确定的值填 -1。

```json
{
  "_meta": {
    "source": "多模态LLM空间理解",
    "method": "家具标定法：识别 [具体家具] 作为标尺，反推比例尺",
    "scale_calibration": {
      "reference_object": "标定物名称",
      "reference_real_size_m": 0.72,
      "reference_pixel_size_avg": 88,
      "scale_m_per_px": 0.0082,
      "cross_validation": ["验证物1 XXpx → X.Xm (标准X.X-X.Xm ✓)"]
    },
    "confidence_note": "精度说明",
    "timestamp": "YYYY-MM-DD"
  },

  "空间基本信息": {
    "space_name": "空间完整名称",
    "space_type": "共享办公子类型（如：休闲协作区、独立工位区、会议室、多功能厅）",
    "space_type_en": "kebab-case英文（如coworking-lounge）"
  },

  "空间绝对尺度": {
    "length_m": 0.0,
    "width_m": 0.0,
    "ceiling_height_m": 0.0,
    "net_floor_area_m2": 0.0,
    "volume_m3": 0.0
  },

  "围护结构": {
    "num_windows": 0,
    "window_wall_ratio": 0.0,
    "num_doors": 0,
    "perimeter_m": 0.0,
    "enclosure_ratio": 0.0
  },

  "空间比例": {
    "height_width_ratio": 0.0,
    "length_width_ratio": 0.0
  },

  "家具配置": {
    "furniture_groups": [
      {
        "type": "家具类型",
        "material": "材质",
        "count": 1,
        "dimensions_m": "长×宽",
        "footprint_m2": 0.0,
        "seats": 0
      }
    ],
    "total_furniture_footprint_m2": 0.0,
    "total_seats": 0,
    "furniture_density": 0.0,
    "seating_density_per_m2": 0.0
  },

  "色彩与材质": {
    "dominant_colors": [
      {
        "rank": 1,
        "color_name": "颜色中文名",
        "hex": "#RRGGBB",
        "pantone_approx": "Pantone XXXX C",
        "ral_approx": "RAL XXXX",
        "area_pct": 0,
        "location": "出现位置"
      }
    ],
    "color_temperature_K": 4000,
    "color_scheme": "色调方案描述",
    "primary_floor_material": "地面材质",
    "primary_wall_material": "墙面材质",
    "primary_ceiling_material": "天花材质"
  },

  "光环境": {
    "lighting_type": "灯具类型",
    "num_visible_lights": 0,
    "estimated_illuminance_lux": 0,
    "daylight_factor_est": 0.0
  },

  "空间感知指标": {
    "openness_score": 0.0,
    "privacy_score": 0.0,
    "estimated_RT60_s": 0.0
  }
}
```

## 各字段填写指南

### 空间类型 (space_type)
常见分类：共享办公-开放工位区、共享办公-休闲协作区、共享办公-会议室、共享办公-电话亭、共享办公-多功能厅、共享办公-前台/接待区、共享办公-咖啡吧/茶水间

### 围护结构
- `window_wall_ratio`：窗面积 / 围护面总面积。住宅 0.15-0.25，办公 0.30-0.50，商业 0.50-0.70
- `enclosure_ratio`：0 = 完全开放（如广场），0.5 = 半开放（三面墙），1 = 完全封闭（四面墙+门关上）
- `perimeter_m`：(长+宽) × 2

### 家具
- `furniture_density`：家具总投影面积 / 净地面积。0.2 = 宽松，0.3-0.4 = 适中，> 0.5 = 密集
- `seating_density_per_m2`：总座位数 / 净面积。人均 > 3m² = 宽松，2-3m² = 标准，< 2m² = 拥挤

### 色彩
- `dominant_colors` 提供 6 个主色，按面积占比排序
- `color_temperature_K`：2700K = 暖白（家居），4000K = 中性白（办公），5000K = 冷白，6500K = 日光白
- `color_scheme`：如"暖中性色调"、"工业冷灰"、"北欧原木"、"撞色活力"

### 光环境
- `estimated_illuminance_lux`：100 = 走廊/通道，300 = 休闲区，500 = 办公区，750 = 精细工作
- `daylight_factor_est`：采光系数 ≈ 窗面积/地面积 × 玻璃透射率 × 修正系数。0.02 最低，0.035 良好，> 0.05 优秀

### 感知指标
- `openness_score`：0.3 = 封闭小间，0.5 = 标准办公室，0.7 = 开放大厅，0.9 = 中庭/挑高
- `privacy_score`：0 = 完全开放，0.3 = 有低矮隔断，0.5 = 高隔断，0.8 = 半封闭，1 = 独立房间
- `estimated_RT60_s`：混响时间。0.4 = 录音室，0.6-0.8 = 办公推荐，1.0 = 普通房间，> 1.5 = 体育馆

## 输出要求

1. 所有数值使用真实物理单位，不要归一化
2. 不确定的值填 -1，不要猜测
3. `_meta` 中必须记录标定方法和交叉验证结果
4. `dominant_colors` 至少 3 个，最多 6 个
5. 整个 JSON 必须可被 Python `json.load()` 直接解析
