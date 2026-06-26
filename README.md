# Space Feature Extractor — 共享办公空间特征提取工具

> 硕士论文《共享办公型室内空间陈设的脑认知与智能交互研究》的数据采集工具
>
> 输入一张平面图 + 若干透视照 → 输出 56 个标准化空间特征（含真实物理单位）

---

## 它能做什么

给它一个共享办公空间的平面图和室内照片，它会自动提取出 56 个量化特征，涵盖空间尺度（米）、围护结构、家具配置、色彩材质（HEX/RAL）、光环境（lux/K）、空间感知评分，以及基于计算机视觉的几何形态和语义构成分析。所有结果以 JSON + CSV 输出，可直接用于统计建模。

处理流程分两个阶段：

- **阶段 A**（LLM 看图）：多模态大模型同时看平面图和透视照，通过"家具标定法"反推空间真实尺寸，输出 38 个特征
- **阶段 B**（本地脚本）：OpenCV 分析平面图几何、Mask2Former 做语义分割、OpenCV 计算感知指标，输出 18 个特征 + 3 张可视化图

---

## 目录结构与文件说明

```
space-feature-extractor/
│
├── README.md                    ← 👈 你正在看的文件，项目总览和使用说明
├── SKILL.md                     ← CatDesk Skill 入口文件，AI 助手读这个来执行工作流
│
├── references/                  ← 参考文档（不需要修改，供查阅）
│   ├── PRD_空间分析管线.md      ← 完整的产品需求文档 + 技术路线图，换机器时的开发参考
│   ├── llm_prompt_template.md   ← 阶段A的 LLM 提示词模板，包含 JSON Schema 和家具标定法说明
│   ├── feature_dictionary.json  ← 56 个特征字段的中英文对照表（JSON 格式）
│   └── feature_dictionary.csv   ← 同上的 CSV 版本，Excel 可直接打开查看
│
├── scripts/                     ← 核心脚本（阶段B）
│   ├── space_analyzer.py        ← 单案例分析脚本：读取图片+LLM JSON → 跑 CV 管线 → 输出特征+图片
│   └── batch_analyze.py         ← 批量处理脚本：遍历 input/ 下所有案例，逐个调用 space_analyzer
│
├── input/                       ← 📂 输入数据（往这里放你的案例）
│   └── 案例01_WeWork/           ← 示例案例（已填充真实数据，可作为参考模板）
│       ├── plan.png             ← 平面图（必须，命名为 plan.*）
│       ├── photo_01.png         ← 透视照（必须至少1张，命名为 photo_*.*）
│       └── llm_understanding.json ← 阶段A产出（LLM 看图后生成的结构化 JSON）
│
└── output/                      ← 📂 输出结果（脚本自动生成，不需要手动创建）
    ├── 案例01_WeWork/           ← 示例案例的分析产出
    │   ├── features.json        ← ⭐ 核心产出：56 个特征值（JSON）
    │   ├── features.csv         ← 同样数据的表格版，Excel 直接打开
    │   ├── plan_binary.png      ← OpenCV 平面图二值化结果
    │   ├── seg_semantic.png     ← Mask2Former 语义分割纯色图（8种颜色对应8类空间元素）
    │   └── seg_overlay.png      ← 语义分割叠加在原图上的效果图
    ├── batch_summary.json       ← 批量处理汇总：每个案例的状态/特征数/耗时
    └── batch_summary.csv        ← 同上的 CSV 版本
```

---

## 快速开始

### 1. 安装依赖

```bash
pip3 install opencv-python-headless torch torchvision transformers numpy Pillow
```

Mask2Former 模型首次运行时会自动下载（约 200MB），之后走本地缓存。支持 Apple Silicon MPS 加速。

### 2. 准备案例数据

在 `input/` 下新建一个案例文件夹，放入平面图和透视照：

```bash
mkdir input/案例02_某空间
cp /你的图片路径/平面图.jpg  input/案例02_某空间/plan.jpg
cp /你的图片路径/室内照.png  input/案例02_某空间/photo_01.png
```

可以参考已有的 `input/案例01_WeWork/` 了解文件命名规范。

### 3. 跑阶段 A（LLM 看图）

用任何支持视觉的 LLM（Claude/GPT-4o 等），把平面图和透视照一起发给它，附上 `references/llm_prompt_template.md` 中的提示词。LLM 会输出一个结构化 JSON，保存为：

```
input/案例02_某空间/llm_understanding.json
```

如果在 CatDesk 中使用，说"帮我分析这个空间"即可自动完成这一步。

### 4. 跑阶段 B（本地 CV 管线）

```bash
# 设置路径变量（根据你的实际路径修改）
SKILL=~/.catpaw/skills/space-feature-extractor

# 批量处理 input/ 下所有案例
python3 $SKILL/scripts/batch_analyze.py \
  --input-dir $SKILL/input \
  --output-dir $SKILL/output

# 或者只跑单个案例
python3 $SKILL/scripts/batch_analyze.py \
  --input-dir $SKILL/input \
  --output-dir $SKILL/output \
  --case 案例02_某空间
```

### 5. 查看结果

处理完成后，在 `output/案例02_某空间/` 下会看到：

- `features.json` — 56 个特征值，核心产出
- `features.csv` — 同样的数据，Excel 直接打开
- `plan_binary.png` — 平面图二值化（验证用）
- `seg_semantic.png` — 语义分割图
- `seg_overlay.png` — 语义分割叠加原图

---

## 56 个特征速览

| 类别 | 数量 | 来源 | 举例 |
|------|------|------|------|
| 空间尺度 | 5 | LLM | 长 13.4m、宽 6.2m、层高 3.8m、面积 70.7m²、体积 268.7m³ |
| 围护结构 | 5 | LLM | 窗户 2 个、窗墙比 0.38、围合度 0.65 |
| 空间比例 | 2 | LLM | 高宽比 0.61、长宽比 2.16 |
| 家具配置 | 3 | LLM | 座位 27 个、家具密度 0.26、座位密度 0.38/m² |
| 色彩材质 | 15 | LLM | 色温 4200K、主色 #c8a86e (RAL 1002)、地板/墙/天花材质 |
| 光环境与感知 | 7 | LLM | 照度 350lux、开阔感 0.78、私密性 0.2、RT60 1.3s |
| 空间类型 | 1 | LLM | "共享办公-休闲协作区" |
| 平面几何 | 5 | OpenCV | 紧凑度 0.49、矩形度 0.88、通透度 |
| 语义构成 | 8 | Mask2Former | 围护壳体 46%、地面 20%、门窗 19%、座椅 9% |
| CV 感知 | 6 | OpenCV | 亮度 165、色温 5896K、冷暖指数 20.7 |

完整的中英文字段对照表见 `references/feature_dictionary.csv`。

---

## 换电脑部署

把整个 `space-feature-extractor/` 文件夹复制到新机器的 `~/.catpaw/skills/` 下（或任意位置），然后：

```bash
pip3 install opencv-python-headless torch torchvision transformers numpy Pillow
```

就可以直接跑了。代码、文档、示例数据全在一起，不需要额外配置。

---

## 更多信息

- 详细的技术路线和架构设计 → `references/PRD_空间分析管线.md`
- 56 个字段的定义和基准值 → `references/feature_dictionary.json`
- LLM 提示词和家具标定法 → `references/llm_prompt_template.md`
