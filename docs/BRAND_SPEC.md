# XinRefinement 品牌视觉规范（BRAND_SPEC）

> 版本：v0.1.0 ｜ 承接家族：XinMatch（`D:\Project\XRD\XinMatch\assets`）
> 复现：`python tools/compose_brand_assets.py all`

## 1. 设计定位

| 维度 | 说明 |
| --- | --- |
| 项目定位 | 通用粉末衍射**全谱拟合（Rietveld 结构精修 / 谱图精修）**桌面软件，承接 XinMatch 的精修职责 |
| 家族一致性 | 保留 XinMatch 的圆角渐变底板、χin 书法标记、底部衍射峰、左下 wordmark、右下 logo plate、深蓝 splash 版式 |
| 差异化 | ①主题色「科技蓝」整体**略微加深**；②splash 视觉隐喻从「物相匹配（指纹）」迁移为「最小二乘收敛（χ² 涟漪 + 发光晶格 + obs/calc/diff 拟合谱）」 |

## 2. 品牌色板 Token

### 2.1 科技蓝（Logo 主题色，整体加深）

| 区域 | 家族原值 | XinRefinement 现值 | 说明 |
| --- | --- | --- | --- |
| 渐变顶（圆角方顶部） | `#256DE7` | `#1C55C2` | 加深 ≈ 明度 −22%（第二档，更偏深蓝） |
| 渐变底（圆角方底部） | `#0E3BA1` | `#0B2E87` | 加深 ≈ 明度 −20%、蓝占比略升 |
| 白色图形 / χin / 衍射峰 | `#FFFFFF` | `#FFFFFF` | **保持不变**（软掩码保护，不加深） |

> 加深由 `tools/compose_brand_assets.py` 的 `BLUE_DEEPEN=(0.86,0.86,0.88)` 逐通道乘性缩放实现，白色元素经 RGB 最小通道软掩码自动排除。

### 2.2 Splash 深蓝（背景）

| 用途 | 色值 |
| --- | --- |
| 背景中心 | `#0A2350` |
| 背景边缘（径向衰减） | `#04102A` |
| 涟漪 / 收敛光核 | `#5AAAFF`（发光，叠加产生） |
| 文字细横线（强调） | `#78BEFF` |

### 2.3 谱图语义色（沿用 `core/palette.py`，界面 / 报告一致）

| 语义 | 色值 | 在 Splash 中的处理 |
| --- | --- | --- |
| 实测 obs | `#1f77b4` | 蓝色 × 散点（`#5AB4FF`，适配深底） |
| 计算 calc | `#000000` | 亮青白实线 `#E1F5FF`（深底改为亮色，语义不变：计算谱） |
| 残差 diff | `#d62728` | 红色细线 `#D62728` |
| 背景 bg | `#7f7f7f` | 灰色虚线 |
| 峰位 mark | `#2ca02c` | 绿色峰位棒 `#3CC86E` |

> 家族约定「界面里长什么样，报告里就长什么样」；Splash 仅因深底把 calc/obs 提亮，语义标签不变。

## 3. 字体与字号层级

| 文本 | 字体 | 字号（在各自画布） | 备注 |
| --- | --- | --- | --- |
| Logo 品名 `Refinement` | Segoe UI Bold | 181 px @2048 | 家族 `Match` 原 236 px；长词按目标墨迹宽度 990 px 等比缩放，墨迹中心 (1010, 1380) |
| Splash 主标题 `XinRefinement` | Segoe UI Bold | 0.090 H ≈ 138 px @1536 | 左对齐，绝对焦点 |
| Splash 版本 `v0.1.0` | Segoe UI Regular | 0.046 H ≈ 70 px | 紧贴细横线下方 |
| Splash 英文副标 | Segoe UI Regular | 0.030 H ≈ 46 px | `Whole-pattern fitting · Rietveld refinement` |
| Splash 中文副标 | 微软雅黑 | 0.034 H ≈ 52 px | `全谱拟合 · 结构精修` |

## 4. 交付清单（输出规格）

| 文件 | 尺寸 | 格式 | 用途 |
| --- | --- | --- | --- |
| `assets/logo.png` | 2048² | PNG RGBA 透明 | 主交付（家族兼容命名） |
| `assets/logo_transparent.png` | 2048² | PNG RGBA 透明 | 与 `logo.png` 同内容，splash 合成引用 |
| `assets/logo_white_bg.png` | 2048² | PNG RGB | 文档 / 网页白底引用 |
| `assets/icon_1024.png` | 1024² | PNG | 大图标 |
| `assets/logo_mark.png` | 512² | PNG | favicon / 头像（χin 标记版） |
| `assets/icons/logo_{16,24,32,48,64,128,256,512,1024}.png` | 多尺寸 | PNG | 系统图标；**≤64 px 用 χin 标记版**保证可读性 |
| `assets/icons/logo.ico` | 16–1024 多尺寸 | ICO | Windows 安装包 / 任务栏 |
| `assets/splash_backdrop.png` | 2730×1536 | PNG RGB | 纯背景（可复用，无文字） |
| `assets/splash.png` | 2730×1536 | PNG RGB | 启动画面成品（含文字，预加载/开机首屏用） |
| `assets/splash_installer.bmp` | 164×314 | BMP | Inno Setup 向导侧栏 `WizardImageFile` |

## 5. 安全区与最小尺寸

- **Logo**：χin 与品名整体置于画布中央 ≈88% 区域；文字最小可识别 ≈64 px，更小尺寸一律用 `logo_mark.png`（χin 标记）。
- **Splash 文字**：左下 `0.055W × 0.50H–1.06H` 暗角保护区，保证文字压在谱图之上仍可读；右下 logo plate 不侵入中央主视觉。

## 6. 家族一致性检查清单

- [x] 圆角渐变底板 + χin 书法标记保留
- [x] 底部衍射峰保留（家族识别元素）
- [x] 科技蓝整体加深（H/S 校验，白色元素豁免）
- [x] Logo 文字换为 `Refinement`，字号按宽度自适应、墨迹居中
- [x] Splash 版式沿用（左下 wordmark / 右下 logo plate）
- [x] Splash 语义正确迁移（物相匹配 → 全谱拟合 / 结构精修）
- [x] 多尺寸图标族 + ICO + 安装向导图齐备
- [ ] 拟合谱真值来源固定为 `tests/data/virtual_b/v50_wide.xy`（更换数据需重跑生成器）

## 7. 设计评审（专家式）

### 优点
1. 像素级复用家族 logo 几何（χin、渐变、峰形），品牌延续性 100%。
2. Splash 以「χ² 涟漪 + 发光晶格 + obs/calc/diff 三联图」精准翻译「全谱拟合 / 结构精修」，与 XinMatch 的「指纹 = 物相识别」形成清晰语义差异。
3. 谱图配色与 `core/palette.py` 同源，界面、报告、启动画面三重一致。

### 改进方向
1. 小尺寸（≤48 px）logo 的副细节（in / Refinement）不可读 → 已用 χin 标记版缓解，必要时提供纯符号 favicon。
2. Splash 中央辉光略偏左下，极致对称可再微调（当前属正常氛围光，不阻塞发布）。

### 具体建议
1. 后续若做品牌延展（官网 / 文档封面），优先复用 `splash_backdrop.png` 作底，保证视觉统一。
2. 安装包 `WizardImageFile` 已提供 164×314 竖版 BMP；若 Inno 需要位图非 BMP 再转格式（不改尺寸比例）。
3. 任何 logo / splash 变更只允许通过 `tools/compose_brand_assets.py` 重生成，**勿手改位图**，以保证家族资产可复现。

## 8. 复现命令

```bash
python tools/compose_brand_assets.py logo     # logo + 图标族
python tools/compose_brand_assets.py splash    # backdrop + splash + 安装向导图
python tools/compose_brand_assets.py all
```

依赖：Pillow / numpy / scipy；字体取自 `C:\Windows\Fonts`（Segoe UI / 微软雅黑）。
生成后 `assets/` 完全自包含，不再依赖家族仓库。
