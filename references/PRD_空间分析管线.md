# 共享办公空间特征提取管线 — PRD 与技术路线图

> 版本: v2.0 | 日期: 2025-06-25 | 作者: lipeilin06
> 用途: 硕士论文《共享办公型室内空间陈设的脑认知与智能交互研究》的数据采集工具

---

## 一、项目背景与目标

本研究需要对 100+ 个共享办公空间进行标准化的空间特征提取，形成可用于统计建模和机器学习的结构化数据集。每个案例的输入为一张平面图和若干张人视角透视照片，输出为 56 个固定维度的特征数据。

核心诉求：将分析流程固化为可复用的 CatDesk Skill（`space-feature-extractor`），任何有视觉能力的 LLM 拿到图片后即可自动完成全流程，支持批量化处理。

---

## 二、整体架构

### 2.1 两阶段处理流程

```
输入图片 ──→ [阶段A: LLM多模态理解] ──→ [阶段B: 本地CV管线] ──→ 结构化特征输出
              (云端大模型看图)              (本地 Python 脚本)
```

**阶段 A — LLM 多模态理解（云端）**

LLM（如 Claude/GPT-4o）同时看平面图和透视照，通过视觉认知理解空间，按固定 JSON Schema 输出结构化空间数据。这一步提取的是需要"理解力"的信息：空间尺度（通过家具标定法反推真实物理单位）、围护结构、家具配置（类型/数量/材质/座位数）、色彩与材质（HEX/RAL/Pantone）、光环境、空间感知评分等。

阶段 A 产出 56 个特征中的 38 个 LLM 来源字段，保存为 `llm_understanding.json`。

**阶段 B — 本地 CV 管线（本地）**

用 Python 脚本在本地运行，读取同样的图片 + 阶段A的 JSON，用计算机视觉工具补充 LLM 做不了的像素级定量分析：

| 工具 | 输入 | 产出 | 特征数 |
|------|------|------|--------|
| OpenCV 几何分析 | 平面图 | 二值化轮廓 → 形状指标 | 5 个（紧凑度、矩形度、凸性、水平/垂直通透度）|
| Mask2Former (Swin-Tiny, ADE20K) | 透视照 | 语义分割 → 8 组面积占比 | 8 个（围护壳体、地面、门窗、座椅、工作台面、储物、植物装饰、照明）|
| OpenCV 感知分析 | 透视照 | 像素统计 → 感知指标 | 6 个（亮度、对比度、色温、冷暖指数、饱和度、纵深感）|

阶段 B 产出剩余 18 个 CV/Mask2Former 来源字段，以及可视化图片（二值化图、语义分割图、叠加图）。

### 2.2 特征总览（56 个）

按来源和维度分为 10 组：

| 组别 | 来源 | 字段数 | 包含内容 |
|------|------|--------|----------|
| 空间类型 | LLM | 1 | 共享办公子类型 |
| 空间尺度 | LLM | 5 | 长度、宽度、层高、净面积、体积 |
| 围护结构 | LLM | 5 | 窗户数、窗墙比、门数、周长、围合度 |
| 空间比例 | LLM | 2 | 高宽比、长宽比 |
| 家具配置 | LLM | 3 | 总座位、家具密度、座位密度 |
| 色彩与材质 | LLM | 15 | 色温、色调方案、三面材质、前3主色（HEX+RAL+占比）|
| 光环境与感知 | LLM | 7 | 灯具类型、灯具数、照度、采光系数、开阔感、私密性、RT60 |
| 平面几何 | OpenCV | 5 | 紧凑度、矩形度、凸性、水平/垂直通透度 |
| 语义构成 | Mask2Former | 8 | 8 组语义面积占比 |
| CV 感知 | OpenCV | 6 | 亮度、对比度、色温、冷暖、饱和度、纵深感 |

完整的字段中英文对照表见 `references/feature_dictionary.csv`。

---

## 三、输入输出规范

### 3.1 目录结构

所有数据（输入和产出）统一存放在 skill 目录下，换电脑时整个文件夹复制即可。已包含一个完整的 demo 示例 `案例01_WeWork`：

```
~/.catpaw/skills/space-feature-extractor/   ← Skill 根目录（代码+数据一体化）
├── SKILL.md                                ← Skill 入口文档
├── references/                             ← 参考文档
│   ├── PRD_空间分析管线.md                 ← 本文档（技术实现层面）
│   ├── 研究方法论.md                      ← 研究设计方法论（壳子陈设分离、聚类原型、边界定义）
│   ├── llm_prompt_template.md              ← 阶段A LLM提示词模板
│   ├── feature_dictionary.json             ← 56字段中英文对照表
│   └── feature_dictionary.csv              ← 同上CSV版
├── scripts/                                ← 脚本
│   ├── space_analyzer.py                   ← 阶段B核心分析脚本
│   ├── batch_analyze.py                    ← 批量处理脚本
│   ├── plan_splitter.py                    ← 平面图拆分预处理工具
│   └── card_generator.py                   ← 案例卡片可视化生成器
│
├── input/                                  ← 所有案例的输入素材
│   └── 案例01_WeWork/                      ← ✅ 示例案例（已填充真实数据）
│       ├── plan.png                        ← 平面图 (107KB)
│       ├── photo_01.png                    ← 透视照 (4.5MB)
│       └── llm_understanding.json          ← 阶段A LLM产出 (10KB, 261行)
│
└── output/                                 ← 所有案例的分析产出
    ├── 案例01_WeWork/                      ← ✅ 示例产出（已跑通全流程）
    │   ├── features.json                   ← 56个特征 (1.6KB)
    │   ├── features.csv                    ← 同上CSV版 (1.3KB)
    │   ├── plan_binary.png                 ← OpenCV二值化图 (20KB)
    │   ├── seg_semantic.png                ← 语义分割纯色图 (52KB)
    │   └── seg_overlay.png                 ← 语义分割叠加原图 (2.5MB)
    ├── batch_summary.json                  ← 批量处理汇总
    └── batch_summary.csv                   ← 批量处理汇总CSV
```

### 3.2 输入要求

每个案例文件夹必须包含：

| 文件 | 命名规范 | 要求 |
|------|----------|------|
| 平面图 | `plan.jpg` / `plan.png` | 必须，1 张，俯视平面图或 CAD 草图 |
| 透视照 | `photo_01.png`, `photo_02.jpg`, ... | 必须至少 1 张，人视角室内照片 |
| LLM JSON | `llm_understanding.json` | 可选，阶段A产出；若无则跳过LLM特征 |

案例文件夹命名建议：`案例{编号}_{空间名称}`，如 `案例01_WeWork`、`案例15_星巴克Reserve`。

### 3.3 输出说明

| 文件 | 格式 | 用途 |
|------|------|------|
| `features.json` | JSON | 核心产出，56 个特征，供代码读取和建模 |
| `features.csv` | CSV (UTF-8 BOM) | 同样数据的表格版，Excel 直接打开 |
| `plan_binary.png` | PNG | OpenCV 二值化结果，可视化验证用 |
| `seg_semantic.png` | PNG | Mask2Former 语义分割纯色图 |
| `seg_overlay.png` | PNG | 语义分割叠加原图，直观查看分割效果 |
| `report.html` | HTML | 自包含完整报告（可选，需加 `--report` 参数） |

### 3.4 示例输出（案例01_WeWork features.json）

```json
{
  "case_name": "案例01_WeWork",
  "space_type": "共享办公-休闲协作区",
  "length_m": 13.4,
  "width_m": 6.2,
  "ceiling_height_m": 3.8,
  "net_area_m2": 70.7,
  "volume_m3": 268.7,
  "num_windows": 2,
  "window_wall_ratio": 0.38,
  "num_doors": 2,
  "perimeter_m": 39.2,
  "enclosure_ratio": 0.65,
  "height_width_ratio": 0.61,
  "length_width_ratio": 2.16,
  "total_seats": 27,
  "furniture_density": 0.26,
  "seating_density_per_m2": 0.38,
  "color_temperature_K": 4200,
  "color_scheme": "暖中性色调 (warm neutral)",
  "floor_material": "浅色实木/复合木地板",
  "wall_material": "白色乳胶漆 + 局部装饰板",
  "ceiling_material": "裸露管线+白色喷涂",
  "color_1_hex": "#c8a86e",
  "color_1_ral": "RAL 1002",
  "color_1_pct": 35,
  "color_2_hex": "#c4a882",
  "color_2_ral": "RAL 1001",
  "color_2_pct": 25,
  "color_3_hex": "#e8e8e4",
  "color_3_ral": "RAL 9003",
  "color_3_pct": 25,
  "lighting_type": "球形吊灯 (pendant globe)",
  "num_visible_lights": 12,
  "estimated_illuminance_lux": 350,
  "daylight_factor": 0.04,
  "openness_score": 0.78,
  "privacy_score": 0.2,
  "estimated_RT60_s": 1.3,
  "cv_compactness": 0.4905,
  "cv_rectangularity": 0.8822,
  "cv_convexity": 0.9286,
  "cv_h_transparency": 0.5485,
  "cv_v_transparency": 0.4683,
  "sem_shell_pct": 46.04,
  "sem_floor_pct": 19.72,
  "sem_window_door_pct": 18.68,
  "sem_seating_pct": 9.39,
  "sem_work_surface_pct": 1.55,
  "sem_storage_pct": 0.32,
  "sem_plant_deco_pct": 2.56,
  "sem_lighting_pct": 0.09,
  "cv_brightness": 164.8,
  "cv_contrast": 61.4,
  "cv_color_temperature_K": 5896,
  "cv_warmth_index": 20.7,
  "cv_saturation": 52.9,
  "cv_depth_cue": 1.4138
}
```

### 3.5 示例批量汇总（batch_summary.json）

```json
[
  {
    "case": "案例01_WeWork",
    "status": "OK",
    "features": 56,
    "time_s": 8.0
  }
]
```

---

## 四、技术路线图

### 4.1 环境依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.9+ | 运行环境 |
| opencv-python-headless | 4.13+ | 平面图二值化/轮廓分析 + 透视照感知分析 |
| torch | 2.8+ | Mask2Former 推理后端 |
| torchvision | 0.23+ | 图像预处理 |
| transformers | 4.57+ | Mask2Former 模型加载 |
| numpy | 2.0+ | 数值计算 |
| Pillow | 11+ | 图像 I/O |

安装命令：
```bash
pip3 install opencv-python-headless torch torchvision transformers numpy Pillow
```

Mask2Former 模型（`facebook/mask2former-swin-tiny-ade-semantic`）首次运行会自动从 HuggingFace 下载（约 200MB），后续使用本地缓存。支持 Apple Silicon MPS 加速。

### 4.2 阶段 A 技术细节 — LLM 空间理解

LLM 需要同时看到平面图和透视照，按照预定义的 JSON Schema 输出结构化数据。Prompt 模板见 `references/llm_prompt_template.md`。

**家具标定法（核心创新点）**：

LLM 识别平面图中的标准尺寸家具（如单人休闲椅约 0.72m），测量其像素宽度，反推 px-to-meter 比例尺，再用该比例尺推算整个空间的真实物理尺寸。需要至少 2 个家具进行交叉验证。

以 demo 案例为例，LLM 的标定过程：
- 参考物：单人休闲椅（真实 0.72m，像素 88px）→ 比例尺 0.0082 m/px
- 交叉验证：L型沙发 255px → 2.09m（标准 2.0-2.4m ✓）、茶几 167px → 1.37m（标准 1.2-1.5m ✓）
- 空间推算：总长 1825px × 0.0082 ≈ 13.4m，宽 754px × 0.0082 ≈ 6.2m

LLM 按模板输出后保存为 `llm_understanding.json`（参考 `input/案例01_WeWork/llm_understanding.json` 示例，261 行），作为阶段 B 的输入。

### 4.3 阶段 B 技术细节 — 本地 CV 管线

**Step 1: LLM JSON 解析**
- 读入 `llm_understanding.json` → 提取 38 个 LLM 特征字段
- 字段映射：将 LLM 的嵌套 JSON 结构展平为扁平 key-value

**Step 2: OpenCV 平面图分析**
- 读入平面图 → 灰度化 → 二值化（阈值 180）→ 轮廓提取
- 最大外轮廓 → 计算面积、周长、最小外接矩形、凸包
- 产出 5 个形状指标 + `plan_binary.png`
- Demo 结果：Compactness=0.4905, Rectangularity=0.8822

**Step 3: Mask2Former 语义分割**
- 加载预训练模型（Swin-Tiny backbone, ADE20K 150类 → 合并为 8 组）
- 读入透视照 → 推理 → 产出 8 个面积占比 + `seg_semantic.png` + `seg_overlay.png`
- Demo 结果：围护壳体 46.04%、地面 19.72%、门窗 18.68%

**Step 4: OpenCV 感知分析**
- 读入透视照 → HSV 色彩空间
- V 通道 → 亮度(164.8)、对比度(61.4)；RGB 比值 → 色温(5896K)
- H/S 阈值 → 冷暖指数(20.7)；Sobel 梯度 → 纵深感(1.41)

### 4.4 命令行用法

```bash
# 设置 skill 路径变量
SKILL=~/.catpaw/skills/space-feature-extractor

# 单案例处理
python3 $SKILL/scripts/space_analyzer.py \
  --plan $SKILL/input/案例01_WeWork/plan.png \
  --photos $SKILL/input/案例01_WeWork/photo_01.png \
  --llm-json $SKILL/input/案例01_WeWork/llm_understanding.json \
  --name "案例01_WeWork" \
  --out $SKILL/output/案例01_WeWork/

# 批量处理所有案例
python3 $SKILL/scripts/batch_analyze.py \
  --input-dir $SKILL/input --output-dir $SKILL/output

# 只跑单个案例
python3 $SKILL/scripts/batch_analyze.py \
  --input-dir $SKILL/input --output-dir $SKILL/output --case 案例01_WeWork

# 带 HTML 报告
python3 $SKILL/scripts/batch_analyze.py \
  --input-dir $SKILL/input --output-dir $SKILL/output --report
```

---

## 五、Skill 设计

### 5.1 Skill 名称与目录结构

见上方「三、输入输出规范 § 3.1」的完整目录结构图，包含代码、文档、输入和产出全部在 `~/.catpaw/skills/space-feature-extractor/` 下统一管理。

### 5.2 触发场景

用户说"分析空间"、"提取空间特征"、"跑空间分析"、"空间特征提取"、"批量分析案例"、"共享办公分析"、"空间数据采集"、"space analysis"等。

### 5.3 工作流程

**单案例模式**：
1. 用户提供平面图 + 透视照路径
2. Skill 引导 LLM 看图，按 `llm_prompt_template.md` 中的 prompt 生成结构化 JSON（阶段 A）
3. LLM JSON 保存到 `input/{案例名}/llm_understanding.json`（与原始图片放在一起）
4. Skill 调用 `scripts/space_analyzer.py` 跑 CV 管线（阶段 B）
5. 产出到 `output/{案例名}/`（features.json + features.csv + 3张可视化图）

**批量模式**：
1. 用户指定 `input/` 文件夹路径
2. Skill 调用 `scripts/batch_analyze.py` 遍历 `input/` 下所有子文件夹
3. 对每个案例执行完整流程
4. 全部完成后在 `output/` 下生成 `batch_summary.json` + `batch_summary.csv`

---

## 六、新机器部署清单

在一台新电脑上从零开始的步骤：

1. **安装 Python 依赖**：`pip3 install opencv-python-headless torch torchvision transformers numpy Pillow`
2. **安装 CatDesk**（如使用 Skill 模式）
3. **复制 Skill 目录**：将 `~/.catpaw/skills/space-feature-extractor/` 整个文件夹复制到新机器同一位置，内含代码、文档、示例数据、以及 `input/` 和 `output/` 文件夹
4. **放入新案例**：将每个案例的平面图 (`plan.png`) 和透视照 (`photo_*.png`) 放入 `input/案例名/` 下，可参考已有的 `input/案例01_WeWork/` 示例
5. **跑阶段A**：用 LLM 看图生成 `llm_understanding.json`，保存到对应案例的 `input/` 文件夹
6. **跑阶段B**：`python3 ~/.catpaw/skills/space-feature-extractor/scripts/batch_analyze.py --input-dir ~/.catpaw/skills/space-feature-extractor/input --output-dir ~/.catpaw/skills/space-feature-extractor/output`
7. **查看结果**：每个案例的 `output/` 文件夹下有 features.json、features.csv、3张可视化图片

首次运行 Mask2Former 时会自动下载模型（约 200MB），后续走本地缓存。

---

## 七、里程碑

| 阶段 | 内容 | 状态 |
|------|------|------|
| M1 | Demo 验证：单案例跑通完整流程（案例01_WeWork, 56特征, 8秒） | ✅ 已完成 |
| M2 | 特征精简：142 → 56 个 | ✅ 已完成 |
| M3 | Skill 开发：封装为 CatDesk Skill + PRD + 示例数据 | ✅ 已完成 |
| M4 | 平面图拆分器：plan_splitter.py（分析→预览→裁切） | ✅ 已完成 |
| M5 | 方法论文档：研究方法论.md（壳子-陈设分离、聚类原型、边界定义） | ✅ 已完成 |
| M6 | 批量采集：~40 个空间单元案例数据采集 | ⏳ 待开始 |
| M7 | 壳子参数聚类分析，提取典型原型空间 | ⏳ 待开始 |
| M8 | 数据分析：统计建模与可视化 | ⏳ 待开始 |
