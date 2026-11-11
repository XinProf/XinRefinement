# -*- coding: utf-8 -*-
"""XinRefinement 品牌资产生成器（可复现）。

家族语言来源：``D:\\Project\\XRD\\XinMatch\\assets``。本生成器只做两件事：

1. **Logo** —— 以家族 ``logo.png`` 为底，像素级保留 χin 书法标记、圆角渐变
   底板与底部衍射峰，仅把 ``Match`` 换成 ``Refinement``，并把「科技蓝」
   整体略微加深。文字用家族同款 Segoe UI Bold（实测家族墨迹 696×181 与该
   字体 236px 的 700×178 吻合），长词按目标宽度自动缩放字号。
2. **Splash** —— 沿用家族 2730×1536 版式（左下 wordmark / 右下 logo plate），
   但把视觉隐喻从「物相匹配」换成「全谱拟合 / 结构精修」：
   指纹 → χ² 残差涟漪 + 收敛光核，衍射谱 → obs/calc/diff 三联拟合图。

用法（项目根目录）::

    python tools/compose_brand_assets.py logo     # logo + 图标族
    python tools/compose_brand_assets.py splash   # backdrop + splash + 安装向导图
    python tools/compose_brand_assets.py all

依赖：Pillow / numpy / scipy；字体取自 C:\\Windows\\Fonts。
生成的 ``assets/`` 完全自包含，之后不依赖家族仓库。
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy.ndimage import gaussian_filter1d, minimum_filter1d
from scipy.signal import find_peaks

# --------------------------------------------------------------------------
# 常量 / 品牌 token
# --------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
ICONS = ASSETS / "icons"
FAMILY = Path(r"D:\Project\XRD\XinMatch\assets")

FONT_DIR = Path(r"C:\Windows\Fonts")
FONT_BOLD = FONT_DIR / "segoeuib.ttf"
FONT_REG = FONT_DIR / "segoeui.ttf"
FONT_CJK = FONT_DIR / "msyh.ttc"

#: 科技蓝加深系数（逐通道）。家族原渐变 #256DE7 → #0E3BA1，
#: 经 #205CCB→#0C338E、#1C55C2→#0B2E87 两档后，本版再深一档至
#: #0D285C → #051640，仅比 splash 主题色（#0A2350/#04102A）略浅；
#: 白色图形通过软掩码保持不变。
BLUE_DEEPEN = (0.36, 0.37, 0.40)
BRAND_BLUE_TOP = "#0D285C"
BRAND_BLUE_BOTTOM = "#051640"
SPLASH_CENTER = "#0A2350"
SPLASH_EDGE = "#04102A"

#: 家族 logo 中 Match 的墨迹包围盒（实测），擦除时留 24px 余量。
ERASE_BOX = (655, 1263, 1402, 1502)
#: 家族文字墨迹中心（≈1027）；新文字略左移以放松右侧主峰峰尖间距。
WORD_CENTER = (1010.0, 1380.5)
#: Refinement 的目标墨迹宽度（底板内宽约 1671px 的 59%）。
TARGET_WORD_W = 990.0
BASE_FONT_PX = 236  # 家族 Match 字号

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
SPLASH_SIZE = (800, 600)
INSTALLER_SIZE = (164, 314)  # Inno Setup WizardImageFile

REFILL_X = 300  # 家族 logo 每行是纯水平渐变，取固定 x 即可重建擦除区


# --------------------------------------------------------------------------
# 通用工具
# --------------------------------------------------------------------------
def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if path.is_file():
        return ImageFont.truetype(str(path), size)
    return ImageFont.truetype("arial.ttf", size)


def _rgb(hexstr: str) -> tuple[int, int, int]:
    h = hexstr.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lerp(a, b, t):
    return a * (1 - t) + b * t


def _screen_composite(base: np.ndarray, light: np.ndarray) -> np.ndarray:
    """把 light 层（RGBA，发光）以滤色混合叠加到 base（RGB）。"""
    la = (light[:, :, 3:4].astype(np.float32) / 255.0)
    l = light[:, :, :3].astype(np.float32)
    b = base.astype(np.float32)
    out = 255.0 - (255.0 - b) * (255.0 - l * la) / 255.0
    return out.clip(0, 255).astype(np.uint8)


def _glow_layer(size, draw_fn, blur, color=(255, 255, 255), alpha=255):
    h, w = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    draw_fn(d)
    return layer.filter(ImageFilter.GaussianBlur(blur))


# --------------------------------------------------------------------------
# 1. Logo（像素级改造）
# --------------------------------------------------------------------------
def _deepen_blue(arr: np.ndarray) -> np.ndarray:
    """只加深蓝色底板：白色 χin / 衍射峰与抗锯齿边缘保持自然。

    软掩码 w 以 RGB 最小通道衡量「离白多远」：蓝底 R≈14..37 ⇒ w=1；
    白色图形 min≈252 ⇒ w=0；边缘过渡区线性混合，避免硬边。
    """
    rgb = arr[:, :, :3].astype(np.float32)
    lum_min = rgb.min(axis=2)
    w = np.clip((205.0 - lum_min) / (205.0 - 60.0), 0.0, 1.0)[:, :, None]
    fac = np.array(BLUE_DEEPEN, dtype=np.float32)[None, None, :]
    new = rgb * (1.0 - w * (1.0 - fac))
    out = arr.copy()
    out[:, :, :3] = new.clip(0, 255).astype(np.uint8)
    return out


def build_logo():
    src = Image.open(FAMILY / "logo.png").convert("RGBA")
    arr = np.array(src)
    deep = _deepen_blue(arr)
    x0, y0, x1, y1 = ERASE_BOX
    px = deep[y0:y1, REFILL_X, :3]
    for j, y in enumerate(range(y0, y1)):
        deep[y, x0:x1, :3] = px[j]
    img = Image.fromarray(deep, "RGBA")
    font0 = _font(FONT_BOLD, BASE_FONT_PX)
    w0 = font0.getbbox("Refinement")[2] - font0.getbbox("Refinement")[0]
    size = int(round(BASE_FONT_PX * TARGET_WORD_W / w0))
    font = _font(FONT_BOLD, size)
    bb = font.getbbox("Refinement")
    iw, ih = bb[2] - bb[0], bb[3] - bb[1]
    cx, cy = WORD_CENTER
    px_, py_ = cx - iw / 2 - bb[0], cy - ih / 2 - bb[1]
    ImageDraw.Draw(img).text((px_, py_), "Refinement", font=font,
                              fill=(255, 255, 255, 255))
    ASSETS.mkdir(parents=True, exist_ok=True)
    transparent = img.convert("RGBA")
    transparent.save(ASSETS / "logo.png", optimize=True)
    transparent.save(ASSETS / "logo_transparent.png", optimize=True)
    white = Image.new("RGBA", transparent.size, (255, 255, 255, 255))
    white.alpha_composite(transparent)
    white.convert("RGB").save(ASSETS / "logo_white_bg.png", optimize=True)
    transparent.resize((1024, 1024), Image.LANCZOS).save(
        ASSETS / "icon_1024.png", optimize=True)
    print(f"[logo] 字号 {size}px；科技蓝加深 {BRAND_BLUE_TOP} → {BRAND_BLUE_BOTTOM}")
    return transparent


def build_icons(logo_rgba: Image.Image):
    ICONS.mkdir(parents=True, exist_ok=True)
    # 标记版：裁剪到 χin，用于小尺寸（<=64）保证可读性，另存供 favicon/头像
    mark = logo_rgba.crop((467, 210, 1587, 1330)).resize((512, 512), Image.LANCZOS)
    mark.save(ASSETS / "logo_mark.png", optimize=True)
    out_files, ico_imgs = [], []
    for s in ICON_SIZES:
        src = mark if s <= 64 else logo_rgba
        im = src.resize((s, s), Image.LANCZOS)
        im.save(ICONS / f"logo_{s}.png", optimize=True)
        out_files.append(ICONS / f"logo_{s}.png")
        ico_imgs.append(im)
    ico = ICONS / "logo.ico"
    ico_imgs[0].save(ico, sizes=[(s, s) for s in ICON_SIZES],
                     append_images=ico_imgs[1:])
    out_files.append(ico)
    print(f"[icons] {len(out_files)} 文件 → {ICONS}")
    return out_files


# --------------------------------------------------------------------------
# 2. Splash 背景（全谱拟合 / 结构精修 隐喻）
# --------------------------------------------------------------------------
def _sphere_sprite(radius: int, inner, outer):
    """径向渐变球（用于晶胞原子）。"""
    r = radius
    arr = np.zeros((2 * r, 2 * r, 4), np.float32)
    yy, xx = np.mgrid[-r:r, -r:r]
    d = np.sqrt(xx ** 2 + yy ** 2) / r
    m = d <= 1.0
    t = d[m]
    col = np.array(_lerp(np.array(inner, np.float32), np.array(outer, np.float32), t[:, None]))
    arr[m, :3] = col
    arr[m, 3] = 255 * (1 - t * 0.12)
    # 高光
    hr = r * 0.42
    hd = np.sqrt((xx + r * 0.32) ** 2 + (yy + r * 0.34) ** 2) / hr
    hm = hd <= 1.0
    k = hd[hm][:, None]
    arr[hm, :3] = np.array([255, 255, 255], np.float32) * (1 - k) + arr[hm, :3] * k
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def _draw_cell(size, cx, cy):
    """2×2×2 发光立方晶格（家族识别元素，表达「晶体结构」）。"""
    h, w = size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    unit = h * 0.052
    c30 = math.cos(math.radians(30))
    k0 = unit * 1.7

    def proj(i, j, kk):
        x, y, z = i - 1, j - 1, kk - 1
        return (cx + (x - z) * c30 * k0, cy + ((x + z) * 0.5 - y) * k0)

    nodes = [(i, j, kk) for i in range(3) for j in range(3) for kk in range(3)]
    edges = []
    for (i, j, kk) in nodes:
        for di, dj, dk in ((1, 0, 0), (0, 1, 0), (0, 0, 1)):
            ni, nj, nk = i + di, j + dj, kk + dk
            if 0 <= ni < 3 and 0 <= nj < 3 and 0 <= nk < 3:
                edges.append(((i, j, kk), (ni, nj, nk)))
    # 棍：发光底层 + 锐利芯线
    gb = _glow_layer(size, lambda d: [d.line([proj(*a), proj(*b)],
                              fill=(110, 190, 255, 120), width=12) for a, b in edges],
                     blur=6, color=(110, 190, 255))
    layer = Image.alpha_composite(layer, gb)
    d = ImageDraw.Draw(layer)
    for a, b in edges:
        d.line([proj(*a), proj(*b)], fill=(205, 234, 255, 255), width=4)
    # 原子：按深度（远→近）绘制，保证遮挡正确
    for p in sorted(nodes, key=lambda p: (p[0] + p[2], p[1])):
        u, v = proj(*p)
        r = int(unit * 0.30)
        spr = _sphere_sprite(r, (240, 252, 255), (58, 138, 222))
        gl = _sphere_sprite(int(r * 1.3), (110, 190, 255), (110, 190, 255))
        gl = gl.filter(ImageFilter.GaussianBlur(r * 0.3))
        tmp = Image.new("RGBA", layer.size, (0, 0, 0, 0))
        tmp.alpha_composite(gl, (int(u - r * 1.3), int(v - r * 1.3)))
        layer = Image.alpha_composite(layer, tmp)
        layer.alpha_composite(spr, (int(u - r), int(v - r)))
    return layer


def _build_fitting_plot(W, H, data_path: Path):
    """底部 obs/calc/diff 三联拟合图（透明层）。"""
    pts = np.loadtxt(str(data_path), comments="#")
    t = pts[:, 0]
    obs = pts[:, 1].astype(np.float64)
    calc = gaussian_filter1d(obs, 1.4)
    bg = gaussian_filter1d(minimum_filter1d(obs, size=240), 20)
    diff = obs - calc

    x0, x1 = int(W * 0.05), int(W * 0.95)
    y_base, y_top = int(H * 0.96), int(H * 0.77)
    y_mid, y_amp = int(H * 0.973), max(2, int(H * 0.014))
    Imax = calc.max() * 1.06
    dmax = max(np.abs(diff).max() * 1.25, 1.0)
    tmin, tmax = float(t.min()), float(t.max())

    def X(tt):
        return x0 + (tt - tmin) / (tmax - tmin) * (x1 - x0)

    def Y(I):
        return y_base - (I / Imax) * (y_base - y_top)

    def Yd(dv):
        return y_mid - (dv / dmax) * y_amp

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.line([(x0, y_base), (x1, y_base)], fill=(120, 140, 175, 150), width=2)
    for deg in range(10, 91, 10):
        if deg < tmin or deg > tmax:
            continue
        xv = X(deg)
        d.line([(xv, y_base), (xv, y_base + 10)], fill=(150, 170, 200, 170), width=2)
    for k in range(len(t) - 1):
        if k % 3 == 0:
            d.line([(X(t[k]), Y(bg[k])), (X(t[k + 1]), Y(bg[k + 1]))],
                   fill=(140, 155, 175, 140), width=2)
    pk, _ = find_peaks(calc, prominence=Imax * 0.04)
    for p in pk:
        xv = X(t[p])
        d.line([(xv, y_base + 5), (xv, y_base + 22)], fill=(60, 200, 110, 235), width=2)
    for k in range(len(t) - 1):
        d.line([(X(t[k]), Y(calc[k])), (X(t[k + 1]), Y(calc[k + 1]))],
               fill=(225, 245, 255, 255), width=3)
    step = max(1, len(t) // 680)
    for k in range(0, len(t), step):
        xv, yv = X(t[k]), Y(obs[k])
        d.line([(xv - 5, yv - 5), (xv + 5, yv + 5)], fill=(90, 180, 255, 240), width=3)
        d.line([(xv - 5, yv + 5), (xv + 5, yv - 5)], fill=(90, 180, 255, 240), width=3)
    for k in range(len(t) - 1):
        d.line([(X(t[k]), Yd(diff[k])), (X(t[k + 1]), Yd(diff[k + 1]))],
               fill=(214, 39, 40, 235), width=2)
    return layer, (x0, x1, y_top, y_base, y_mid, tmin, tmax)


def build_splash():
    W, H = SPLASH_SIZE
    cx, cy = W * 0.5, H * 0.40
    yy, xx = np.mgrid[0:H, 0:W]
    rr = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / math.hypot(cx, cy)
    base = np.zeros((H, W, 3), np.float32)
    for ch, (c0, c1) in enumerate(zip(_rgb(SPLASH_CENTER), _rgb(SPLASH_EDGE))):
        base[:, :, ch] = _lerp(c0, c1, rr)

    # χ² 残差涟漪（替代家族指纹，语义=最小二乘收敛；平滑正弦带，无硬环）
    ang = math.radians(26)
    ca, sa = math.cos(ang), math.sin(ang)
    ex = (xx - cx) * ca + (yy - cy) * sa
    ey = -(xx - cx) * sa + (yy - cy) * ca
    a = (ex / (W * 0.185)) ** 2 + (ey / (H * 0.245)) ** 2
    falloff = np.clip(1.0 - a * 0.55, 0.0, 1.0)
    ripple = (0.5 + 0.5 * np.sin(a * 7.0)) * falloff
    carr = np.zeros((H, W, 4), np.uint8)
    carr[:, :, 0], carr[:, :, 1], carr[:, :, 2] = 90, 170, 255
    carr[:, :, 3] = (ripple * 140).astype(np.uint8)
    base = _screen_composite(base, np.array(
        Image.fromarray(carr, "RGBA").filter(ImageFilter.GaussianBlur(6))))

    # 收敛光核（中心 = 全局最小）
    core = _glow_layer((H, W),
                       lambda d: d.ellipse([cx - 11, cy - 11, cx + 11, cy + 11],
                                           fill=(185, 235, 255, 255)),
                       blur=12, color=(185, 235, 255))
    base = _screen_composite(base, np.array(core))

    # 发光晶格
    base = _screen_composite(base, np.array(_draw_cell((H, W), cx, cy - H * 0.02)))

    # 底部全谱拟合三联图
    fplot, _ = _build_fitting_plot(W, H,
                                   ROOT / "tests" / "data" / "virtual_b" / "v50_wide.xy")
    base = _screen_composite(base, np.array(fplot.convert("RGBA")))

    # 暗角
    vig = 1.0 - np.clip((rr - 0.45) / 0.55, 0, 1) * 0.55
    base = (base * vig[:, :, None]).clip(0, 255).astype(np.uint8)
    img = Image.fromarray(base, "RGB")

    ASSETS.mkdir(parents=True, exist_ok=True)
    img.save(ASSETS / "splash_backdrop.png", optimize=True)  # 纯背景
    final = _compose_splash_text(img, cx, cy)
    final.save(ASSETS / "splash.png", optimize=True)         # 带文字成品
    print("[splash] splash_backdrop.png / splash.png")
    return final


def _compose_splash_text(img: Image.Image, cx, cy):
    W, H = img.size
    base = img.convert("RGBA")
    scrim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(scrim).ellipse(
        (int(W * 0.005), int(H * 0.50), int(W * 0.50), int(H * 1.06)),
        fill=(2, 10, 29, 160))
    base = Image.alpha_composite(base, scrim.filter(ImageFilter.GaussianBlur(H * 0.045)))

    draw = ImageDraw.Draw(base)
    size_name, size_ver, size_tag, size_cjk = (int(H * 0.090), int(H * 0.046),
                                              int(H * 0.030), int(H * 0.034))
    x = int(W * 0.055)
    y_name = int(H * 0.615)
    draw.text((x, y_name), "XinRefinement", font=_font(FONT_BOLD, size_name),
              fill=(255, 255, 255, 250))
    y_ver = y_name + int(size_name * 1.34)  # 拉开主标题与细横线间距
    draw.line([(x + 2, y_ver - int(size_ver * 0.55)),
               (x + 2 + int(W * 0.052), y_ver - int(size_ver * 0.55))],
              fill=(120, 190, 255, 230), width=max(2, H // 400))
    draw.text((x + 2, y_ver + int(size_ver * 1.6)),
              "Whole-pattern fitting · Rietveld refinement",
              font=_font(FONT_REG, size_tag), fill=(176, 205, 232, 240))
    draw.text((x + 2, y_ver + int(size_ver * 3.1)),
              "全谱拟合 · 结构精修", font=_font(FONT_CJK, size_cjk),
              fill=(170, 200, 230, 240))
    # 右下 logo plate（带辉光）
    logo = Image.open(ASSETS / "logo_transparent.png").convert("RGBA")
    psize = int(H * 0.30)
    plate = logo.resize((psize, psize), Image.LANCZOS)
    pad = int(psize * 0.22)
    canvas = Image.new("RGBA", (psize + 2 * pad, psize + 2 * pad), (0, 0, 0, 0))
    glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    glow.paste((255, 255, 255, 110), (pad, pad, pad + psize, pad + psize),
               plate.getchannel("A"))
    glow = glow.filter(ImageFilter.GaussianBlur(psize * 0.10))
    canvas = Image.alpha_composite(canvas, glow)
    canvas.paste(plate, (pad, pad), plate)
    margin = int(H * 0.075)
    base.alpha_composite(canvas, (W - canvas.width - margin, H - canvas.height - margin))
    return base.convert("RGB")


def build_installer_image():
    """Inno Setup 安装向导侧栏图 164×314（竖版 splash 摘要）。"""
    img = Image.open(ASSETS / "splash.png").convert("RGB")
    ASSETS.mkdir(parents=True, exist_ok=True)
    img.resize(INSTALLER_SIZE, Image.LANCZOS).save(ASSETS / "splash_installer.bmp", "BMP")
    print("[splash] splash_installer.bmp (Inno Setup WizardImageFile)")


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["logo", "splash", "all"], default="all", nargs="?")
    args = ap.parse_args()
    if args.stage in ("logo", "all"):
        build_icons(build_logo())
    if args.stage in ("splash", "all"):
        build_splash()
        build_installer_image()


if __name__ == "__main__":
    main()
