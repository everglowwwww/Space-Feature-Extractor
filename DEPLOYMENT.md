# Space Feature Extractor — 全环境部署说明（跨机器复用版）

> 本文件用于在不同电脑上部署本工具。覆盖从零开始的前置环境、Python 依赖、模型缓存、API 密钥、以及各脚本的完整依赖闭环。**照着做即可在新机器上跑通。**
>
> 更新时间：2026-08-22
> 目标系统：Windows / macOS（已针对 Apple Silicon MPS 加速做兼容说明）

---

## 一、这个工具需要什么（总览）

本工具 = 两阶段管线，每阶段依赖不同：

| 阶段 | 谁执行 | 依赖类型 | 产出 |
|------|--------|----------|------|
| **阶段A-视觉** | DeepSeek 视觉模型（API） | 仅 Python 标准库 | `llm_understanding.json`（语义字段 + 估算尺度）|
| **阶段A-几何** | `dxf_parser.py`（ezdxf） | Python + `ezdxf` | DXF 精确尺度写入 `llm_understanding.json` |
| **阶段B** | `space_analyzer.py` | Python + OpenCV + torch + transformers | `features.json` 等 56 特征 + 可视化图 |

> 注意：**阶段A-视觉只调 DeepSeek 在线 API（需要网络 + API Key）**，不在本地跑大模型。只有**阶段B**需要在本地跑 Mask2Former 深度学习模型。

分两块列依赖：**前置环境**（所有机器都要装的基本工具）和 **Python 依赖**（各脚本具体用到的库）。

---

## 二、前置环境（所有机器必须先装）

### 2.1 Python（必需）

| 项目 | 说明 |
|------|------|
| 推荐版本 | **Python 3.10 ~ 3.12** |
| 最低版本 | 3.8+（脚本用了 f-string / pathlib / typing 等新语法）|
| 为什么不用 3.13 | `torch` / `transformers` 等深度学习包对 3.13 支持尚不完善，**3.10-3.12 最稳** |

验证：
```bash
python --version
# 应输出 Python 3.10/3.11/3.12
```

> ⚠️ 本机现在默认 3.13.14，但阶段B的 torch/transformers 建议在 3.10-3.12 的独立虚拟环境中跑，避免版本冲突。

### 2.2 虚拟环境管理（强烈推荐）

用 venv 隔离，避免污染系统 Python，也方便跨机器迁移：

```bash
# 创建（在 skill 目录外层或任意位置）
python -m venv .venv

# 激活
# Windows (Git Bash / cmd / PowerShell)
source .venv/Scripts/activate        # Git Bash
.venv\Scripts\activate               # cmd
.venv\Scripts\Activate.ps1           # PowerShell
# macOS / Linux
source .venv/bin/activate
```

验证激活：命令行前缀会显示 `(.venv)`。

### 2.3 Git（可选，用于版本管理）

```bash
git --version
```

### 2.4 网络（必需）

- 阶段A 调用 DeepSeek API：需可访问 `https://api.deepseek.com`
- 阶段B 首次运行 Mask2Former：需下载模型，可访问 HuggingFace
  - 有代理则设置 `HF_ENDPOINT=https://hf-mirror.com` 走镜像（国内推荐）

---

## 三、Python 依赖（完整清单）

### 3.1 所需包一览（按用途分组）

| 包名 | 用途 | 哪个脚本用 | 必须？ |
|------|------|-----------|:---:|
| `ezdxf` | 解析 DXF 图纸（阶段A几何，精确尺度）| `dxf_parser.py`（新增）| ✅ 有DXF则必须 |
| `numpy` | 数值计算 | `space_analyzer.py`、`card_generator.py` | ✅ |
| `opencv-python-headless` | 平面图二值化/轮廓 + 透视照感知 | `space_analyzer.py`、`card_generator.py` | ✅ |
| `torch` | Mask2Former 推理后端（阶段B）| `space_analyzer.py` | ✅ |
| `torchvision` | 图像预处理（配合 torch）| `space_analyzer.py` | ✅ |
| `transformers` | Mask2Former 模型加载 | `space_analyzer.py` | ✅ |
| `Pillow` | 图像读写 + 分割图绘制 | `space_analyzer.py`、`plan_splitter.py`、`card_generator.py` | ✅ |
| `Pillow`（含字体）| 中文字体渲染 | `card_generator.py` | ✅ |
| `pandas` | **仅当想用批量统计分析时**（可选）| （用途可选）| ❌ 可选 |

> **阶段A-视觉（`llm_phase_a.py`）零第三方依赖**——只用 `argparse`/`base64`/`json`/`urllib` 等标准库，不需要装任何包。

### 3.2 安装命令

**核心安装**（一条装齐阶段B + 阶段A几何所需）：

```bash
pip install ezdxf numpy opencv-python-headless torch torchvision transformers Pillow
```

> 其中 `torch` / `torchvision` 较大，建议按下方"3.4 关于 torch 的说明"选择合适版本。

### 3.3 若遇到 Pillow 中文乱码/字体缺失

Pillow 渲染中文需要系统字体。各系统已内置：
- **Windows**：`C:\Windows\Fonts\msyh.ttc`（微软雅黑）、`simhei.ttf`（黑体）
- **macOS**：`/System/Library/Fonts/PingFang.ttc`、`STHeiti Medium.ttc`
- **Linux**：`/usr/share/fonts/truetype/` 下需自己放

脚本已内置多路径探测（会依次找系统字体），无需额外安装，但 Windows 上若发现中文乱码，请把脚本里的字体路径改为 `C:\Windows\Fonts\msyh.ttc`。

### 3.4 关于 torch（阶段B关键，需注意）

torch 分 CPU / GPU / Apple-Silicon 三种，按机器选择：

| 场景 | 安装方式 |
|------|----------|
| **macOS Apple Silicon (M1/M2/M3/M4)** | 默认 `pip install torch` 即可（自动 MPS 加速，脚本已支持）|
| **Windows 有 NVIDIA 显卡** | `pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121` |
| **无 GPU（CPU）** | 默认 `pip install torch` 即可（脚本会回退 CPU）|

> 脚本 `space_analyzer.py` 会自动检测：`mps` 可用则用 MPS，否则回退 `cpu`。无需手动设置 device。

---

## 四、模型缓存（阶段B Mask2Former）

阶段B 的语义分割用 **Mask2Former**：

**模型 ID**：`facebook/mask2former-swin-tiny-ade-semantic`（约 200MB）

### 4.1 首次运行
- 需联网，自动从 **HuggingFace** 下载到本地缓存（`~/.cache/huggingface`）
- 无代理的国内环境可能失败，建议先设置镜像：
  ```bash
  export HF_ENDPOINT=https://hf-mirror.com
  ```
- 下载完成后走本地缓存，无需再次下载

### 4.2 离线 / 迁移缓存
若新机器无法联网，可直接拷贝旧机器的 HuggingFace 缓存：
```
~/.cache/huggingface/   →  新机器同路径
```

### 4.3 运行前必须设置的环境变量（重要！）

阶段B 运行前必须设这两个变量，**否则 HuggingFace 联网检查会拖到十几分钟**：

```bash
# Windows (Git Bash)
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# Windows (PowerShell)
$env:HF_HUB_OFFLINE="1"
$env:TRANSFORMERS_OFFLINE="1"

# macOS / Linux
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
```

> ⚠️ 这也是之前跑得慢（17分钟）的原因——没设置离线变量时，模型每次都在联网检查更新。

---

## 五、API 密钥（阶段A视觉）

阶段A 调 DeepSeek 视觉模型，需要 API key 和 base_url。

### 5.1 配置文件位置
`config/deepseek.json`（**已加入 .gitignore，不会提交**）

### 5.2 配置内容

```json
{
  "api_key": "sk-你的API密钥",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-v4-flash-vision-exp",
  "temperature": 0.2,
  "max_tokens": 16384,
  "timeout_s": 600,
  "image_detail": "original",
  "thinking_disabled": true,
  "reasoning_effort": null,
  "max_retries": 3
}
```

### 5.3 关键字段说明

| 字段 | 说明 |
|------|------|
| `api_key` | DeepSeek API 密钥（`sk-` 开头，从 deepseek 平台获取）|
| `model` | 固定 `deepseek-v4-flash-vision-exp`（实验版视觉模型）|
| `max_tokens` | **≥16384**（它是推理模型，思考耗 token，太小会没正文）|
| `image_detail` | `original`（保留原图；勿用 `low`，会缩到 512 丢细节）|
| `thinking_disabled` | **`true`**（务必开！否则推理耗光 token 输出被截断）|

### 5.4 密钥管理

- `config/deepseek.json` 已忽略，**不要提交 GitHub**
- 参考模板：`config/deepseek.example.json`（含占位 key，可提交）
- 复制 example 为真实配置：
  ```bash
  cp config/deepseek.example.json config/deepseek.json
  # 然后手动填入 api_key
  ```

### 5.5 若把 DeepSeek 也接入 WorkBuddy 作为自定义模型

WorkBuddy 的自定义模型配置在 `~/.workbuddy/models.json`（不是本 skill 的 config）。新增一个**支持图片**的条目，关键字段：
```json
{
  "id": "deepseek-v4-flash-vision-exp",
  "name": "DeepSeek-V4 Flash Vision",
  "url": "https://api.deepseek.com/chat/completions",
  "apiKey": "sk-...",
  "supportsImages": true
}
```
改完需重启 WorkBuddy 客户端（含后台进程）生效。

---

## 六、各脚本依赖闭环（快速自查）

| 脚本 | 作用 | 依赖 |
|------|------|------|
| `scripts/llm_phase_a.py` | 阶段A视觉：调 DeepSeek 看图 → JSON | 无（纯标准库）|
| `scripts/dxf_parser.py` | 阶段A几何：解析 DXF → 精确尺度写 JSON | `ezdxf` |
| `scripts/space_analyzer.py` | 阶段B：56 特征 + 可视化 | `cv2`、`numpy`、`torch`、`transformers`、`Pillow` |
| `scripts/batch_analyze.py` | 批量跑 stageB | 同上（调用 analyzer）|
| `scripts/plan_splitter.py` | 平面图拆分为独立空间单元 | `Pillow` |
| `scripts/card_generator.py` | 杂志风案例卡片 | `cv2`、`numpy`、`Pillow` |

---

## 七、从零部署完整流程（copy-paste 版）

### 步骤 1：装 Python（3.10~3.12）
Windows 从 python.org 下载，安装时勾选 **Add to PATH**。

### 步骤 2：建虚拟环境
```bash
python -m venv .venv
source .venv/Scripts/activate        # 依系统选对应激活命令
```

### 步骤 3：装 Python 依赖
```bash
pip install ezdxf numpy opencv-python-headless torch torchvision transformers Pillow
```

### 步骤 4：下载 Mask2Former 模型缓存（走镜像，一次到位）
```bash
export HF_ENDPOINT=https://hf-mirror.com
python -c "from transformers import AutoImageProcessor, Mask2FormerForUniversalSegmentation; AutoImageProcessor.from_pretrained('facebook/mask2former-swin-tiny-ade-semantic'); Mask2FormerForUniversalSegmentation.from_pretrained('facebook/mask2former-swin-tiny-ade-semantic')"
```
> 这一步会预下载约 200MB 模型到缓存，之后阶段B即可离线运行。

### 步骤 5：配置 DeepSeek key
```bash
cp config/deepseek.example.json config/deepseek.json
# 编辑 config/deepseek.json，填入你的 api_key
```

### 步骤 6：准备案例数据
```
input/案例名/
  ├── plan.png            (必填，平面图)
  ├── photo_01.jpg        (必填，透视照，可多张)
  ├── DX*案例名*.dxf      (选填，有则几何精确)
  └── llm_understanding.json (阶段A产出，见步骤7)
```

### 步骤 7：跑阶段A — 视觉（DeepSeek）
```bash
python scripts/llm_phase_a.py --case-dir "input/案例名"
```

### 步骤 8（选填）：跑阶段A — 几何（DXF，精确尺度覆盖）
```bash
python scripts/dxf_parser.py --dxf "input/案例名/DX*案例名*.dxf" \
  --llm-json "input/案例名/llm_understanding.json"
```

### 步骤 9：跑阶段B — CV 管线
```bash
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
python scripts/space_analyzer.py \
  --plan "input/案例名/plan.png" \
  --photos "input/案例名/photo_01.jpg" \
  --llm-json "input/案例名/llm_understanding.json" \
  --name "案例名" \
  --out "output/案例名/"
```

### 步骤 10：查看结果
`output/案例名/` 下生成 `features.json`、`features.csv`、`plan_binary.png`、`seg_*.png`。

---

## 八、Windows / macOS 差异速查

| 项 | Windows | macOS |
|----|---------|-------|
| 虚拟环境激活 | `.venv\Scripts\activate` | `source .venv/bin/activate` |
| 中文默认字体 | `C:\Windows\Fonts\msyh.ttc` | `/System/Library/Fonts/PingFang.ttc` |
| torch 加速 | CUDA（有N卡）或 CPU | MPS（自动）|
| 环境变量 | `set` / `$env:` | `export` |
| Skill 路径 | `E:\...\space-feature-extractor` | `~/.catpaw/skills/space-feature-extractor` |

> ⚠️ **注意**：README 里的 `~/.catpaw/skills/`（macOS 路径）与当前实际目录 `E:\毕业论文\2.案例调研与数据集\.codex\skills\`（Windows）不同。在 Windows 上请使用实际路径的绝对路径。

---

## 九、常见问题排查

**Q1：阶段B跑很久（十几分钟）？**
→ 没设离线变量。加 `HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1`。

**Q2：阶段A DeepSeek 输出全是 -1？**
→ 见 `config/deepseek.json` 是否 `thinking_disabled: true`。若不设，推理模型思考耗光 token 会输出退化结果。

**Q3：阶段A JSON 解析失败 / 输出被截断？**
→ `max_tokens` 至少 16384。
→ 检查 `image_detail` （应为 `original`）。

**Q4：中文乱码（卡片/分割图）？**
→ 检查脚本字体路径。Windows 用 `C:\Windows\Fonts\msyh.ttc`。

**Q5：没有 DXF 文件？**
→ 跳过步骤8，尺度改用阶段A视觉估算（精度较低，±10-20%，属正常）。

**Q6：py 文件路径含中文 / 空格？**
→ 可用绝对路径，但建议脚本放纯英文路径（如 `D:\skills\space-feature-extractor`）。

---

## 十、一键还原 CheckList

部署完成后，逐项打勾即可确认环境就绪：

- [ ] Python 3.10~3.12 可用（`python --version`）
- [ ] 虚拟环境已激活（命令行前缀 `(.venv)`）
- [ ] `pip show ezdxf numpy opencv-python-headless torch torchvision transformers Pillow` 全部有版本号
- [ ] Mask2Former 缓存已下载（`~/.cache/huggingface` 存在）
- [ ] `config/deepseek.json` 已填真实 api_key
- [ ] 阶段A ping 通过：`python scripts/llm_phase_a.py --ping`
- [ ] 阶段B 能在离线态跑通一个案例

---

*本文件随 skill 一起部署。如新增脚本或依赖，请同步更新本文档。*
