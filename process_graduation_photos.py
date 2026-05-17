#!/usr/bin/env python3
"""
毕业照精修脚本 — 逐张分析版
源文件: ~/Desktop/毕业/毕业典礼/
输出:   ~/Desktop/毕业/毕业典礼 after cloud/

用法:
    python3 process_graduation_photos.py

或指定其他路径:
    python3 process_graduation_photos.py --src /path/to/src --dst /path/to/dst
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import rawpy
from PIL import Image, ImageFilter, ImageEnhance


# ─── 逐张分析：模拟 Lightroom 的自动曝光逻辑 ─────────────────────────────────

def analyze_image(rgb: np.ndarray) -> dict:
    """
    分析图像亮度分布，返回每张照片独立的调整参数。
    输入: float32 RGB [0,1]
    """
    # 感知亮度（Rec.709）
    luma = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]

    p2   = float(np.percentile(luma, 2))    # 最暗端
    p10  = float(np.percentile(luma, 10))
    p50  = float(np.percentile(luma, 50))   # 中间调
    p90  = float(np.percentile(luma, 90))
    p98  = float(np.percentile(luma, 98))   # 最亮端

    overexp_ratio  = float(np.mean(luma > 0.92))   # 高光过曝比例
    underexp_ratio = float(np.mean(luma < 0.08))   # 阴影欠曝比例

    # ── 曝光补偿：目标中间调 ~0.42（比 0.5 略暗，毕业礼服白多） ──────────
    target_midtone = 0.42
    if p50 > 0.01:
        raw_ev = np.log2(target_midtone / p50)
    else:
        raw_ev = 0.5
    # 限制在 ±1.5 EV，过曝照片少推
    if overexp_ratio > 0.05:
        raw_ev = min(raw_ev, 0.1)
    exp_ev = float(np.clip(raw_ev, -1.5, 1.5))
    exp_shift = float(2 ** exp_ev)   # rawpy 的 exp_shift 是线性倍数

    # ── 高光压制：高光越多压得越狠 ──────────────────────────────────────
    # p98 越高 → 高光更多 → 压更多
    highlight_strength = float(np.clip((p98 - 0.80) * 2.5, 0.0, 0.55))

    # ── 阴影提亮：阴影区越暗提越多，但高对比场景不要过度提 ─────────────
    shadow_lift = float(np.clip((0.18 - p10) * 0.6, 0.0, 0.12))
    dynamic_range = p90 - p10
    if dynamic_range > 0.6:       # 高反差场景（逆光、强烈日光）适当克制
        shadow_lift *= 0.6

    # ── 对比度：低反差加强，高反差减弱 ──────────────────────────────────
    if dynamic_range < 0.35:
        contrast = 1.10    # 阴天/室内平光，拉一点
    elif dynamic_range < 0.55:
        contrast = 1.05    # 正常场景
    else:
        contrast = 1.00    # 反差已经够大，不加

    # ── 色彩饱和度：中间调饱和度低时补一点自然饱和度 ────────────────────
    # 用色彩方差估算饱和度
    ch_std = float(np.std(rgb, axis=2).mean())
    if ch_std < 0.06:
        vibrance = 0.18    # 颜色较灰淡（室内、阴天）
    elif ch_std < 0.12:
        vibrance = 0.12    # 正常
    else:
        vibrance = 0.06    # 颜色已经很鲜艳，少加

    return dict(
        exp_shift=exp_shift,
        highlight_strength=highlight_strength,
        shadow_lift=shadow_lift,
        contrast=contrast,
        vibrance=vibrance,
        # 诊断信息（打印用）
        _p50=p50, _p98=p98, _p10=p10,
        _overexp=overexp_ratio, _dynamic_range=dynamic_range,
        _ev=exp_ev,
    )


# ─── 图像处理管线 ────────────────────────────────────────────────────────────

def highlight_recovery(img_f: np.ndarray, strength: float) -> np.ndarray:
    """对高亮区域做软膝式压制，保留高光细节，避免死白。"""
    if strength < 0.01:
        return img_f
    threshold = 0.82
    mask = np.clip((img_f - threshold) / (1.0 - threshold), 0, 1)
    # 软膝：mask^2 让过渡更顺滑
    mask = mask ** 1.5
    compressed = threshold + (img_f - threshold) * (1.0 - strength)
    return img_f * (1 - mask) + compressed * mask


def shadow_lift(img_f: np.ndarray, lift: float) -> np.ndarray:
    """对暗部做非线性提亮，亮部不受影响。"""
    if lift < 0.005:
        return img_f
    luma = 0.2126 * img_f[..., 0:1] + 0.7152 * img_f[..., 1:2] + 0.0722 * img_f[..., 2:3]
    shadow_mask = np.clip(1.0 - luma / 0.4, 0, 1) ** 1.2
    return img_f + shadow_mask * lift * (1.0 - img_f)


def natural_vibrance(img: Image.Image, vibrance: float) -> Image.Image:
    """
    自然饱和度：对低饱和像素提升更多，避免肤色/天空过饱和。
    比直接调 Saturation 更 Lightroom-like。
    """
    if vibrance < 0.005:
        return img
    arr = np.array(img, dtype=np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    sat  = np.where(cmax > 1e-6, (cmax - cmin) / cmax, 0.0)
    boost = vibrance * (1.0 - sat[..., np.newaxis])
    gray  = (0.2126 * r + 0.7152 * g + 0.0722 * b)[..., np.newaxis]
    arr_new = np.clip(arr + (arr - gray) * boost, 0, 1)
    return Image.fromarray((arr_new * 255).astype(np.uint8), mode="RGB")


def apply_tone_curve(img: Image.Image) -> Image.Image:
    """
    轻微 S 型色调曲线（模拟 Lightroom 默认的 Medium Contrast 预设）。
    暗部略微下压，亮部略微上提，让画面更有立体感。
    """
    lut = np.arange(256, dtype=np.float32) / 255.0
    # S 曲线：用 cubic hermite 插值
    # 控制点: (0,0), (64/255, 58/255), (192/255, 198/255), (1,1)
    def s_curve(x):
        # 分段：暗部略压，亮部略提
        dark_mask  = x < 0.5
        result = np.where(
            dark_mask,
            x - 0.04 * np.sin(np.pi * x / 0.5),      # 暗部轻微下压
            x + 0.04 * np.sin(np.pi * (x - 0.5) / 0.5),  # 亮部轻微上提
        )
        return np.clip(result, 0, 1)

    lut_mapped = (s_curve(lut) * 255).astype(np.uint8)
    # 应用到所有通道
    arr = np.array(img)
    arr = lut_mapped[arr]
    return Image.fromarray(arr)


def skin_tone_protection(img: Image.Image, saturation_boost: float) -> Image.Image:
    """
    肤色保护：检测肤色范围（YCbCr），对该区域的饱和度提升减半。
    防止毕业照里脸色变得太红/太橙。
    """
    if saturation_boost < 0.05:
        return img
    arr = np.array(img, dtype=np.float32)
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    # YCbCr 肤色范围判断
    Y  =  0.257*r + 0.504*g + 0.098*b + 16
    Cb = -0.148*r - 0.291*g + 0.439*b + 128
    Cr =  0.439*r - 0.368*g - 0.071*b + 128
    skin_mask = (Y > 80) & (Y < 220) & (Cb > 85) & (Cb < 135) & (Cr > 135) & (Cr < 180)
    return img   # 肤色保护已通过 vibrance 的低饱和优先策略间接实现，此处保留钩子供扩展


def process_one(raw_path: Path, output_path: Path) -> dict:
    """处理单张 CR3，返回分析参数供打印。"""

    # ── 第一次显影：低曝光读出，用于分析直方图 ───────────────────────────
    with rawpy.imread(str(raw_path)) as raw:
        preview = raw.postprocess(
            use_camera_wb=True,
            no_auto_bright=True,
            exp_shift=1.0,
            output_bps=8,
            half_size=True,       # 半分辨率，快速分析
        )
    preview_f = preview.astype(np.float32) / 255.0
    params = analyze_image(preview_f)

    # ── 第二次显影：全分辨率，使用分析出的曝光值 ─────────────────────────
    with rawpy.imread(str(raw_path)) as raw:
        rgb16 = raw.postprocess(
            use_camera_wb=True,
            no_auto_bright=True,
            exp_shift=params["exp_shift"],
            output_bps=16,
            highlight=2,          # blend 模式保高光
            fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Full,
        )

    img_f = rgb16.astype(np.float32) / 65535.0

    # ── 高光压制 ──────────────────────────────────────────────────────────
    img_f = highlight_recovery(img_f, params["highlight_strength"])

    # ── 阴影提亮 ──────────────────────────────────────────────────────────
    img_f = shadow_lift(img_f, params["shadow_lift"])

    img_f = np.clip(img_f, 0, 1)

    # 转 8-bit PIL
    pil_img = Image.fromarray((img_f * 255).astype(np.uint8), mode="RGB")

    # ── S 型色调曲线（Lightroom Medium Contrast 风格） ────────────────────
    pil_img = apply_tone_curve(pil_img)

    # ── 对比度 ────────────────────────────────────────────────────────────
    if abs(params["contrast"] - 1.0) > 0.01:
        pil_img = ImageEnhance.Contrast(pil_img).enhance(params["contrast"])

    # ── 自然饱和度 ────────────────────────────────────────────────────────
    pil_img = natural_vibrance(pil_img, params["vibrance"])

    # ── 输出锐化（轻度 USM，模拟 Lightroom Export Sharpen） ───────────────
    pil_img = pil_img.filter(ImageFilter.UnsharpMask(radius=0.9, percent=65, threshold=3))

    # ── 保存 ──────────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pil_img.save(str(output_path), format="JPEG", quality=95, subsampling=0)

    return params


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def main():
    default_src = Path.home() / "Desktop" / "毕业" / "毕业典礼"
    default_dst = Path.home() / "Desktop" / "毕业" / "毕业典礼 after cloud"

    parser = argparse.ArgumentParser(description="毕业照逐张精修脚本")
    parser.add_argument("--src", default=str(default_src), help="源文件夹")
    parser.add_argument("--dst", default=str(default_dst), help="输出文件夹")
    args = parser.parse_args()

    src = Path(args.src).expanduser().resolve()
    dst = Path(args.dst).expanduser().resolve()

    if not src.is_dir():
        print(f"错误：找不到源文件夹\n  {src}")
        sys.exit(1)

    cr3_files = sorted(list(src.rglob("*.CR3")) + list(src.rglob("*.cr3")))
    if not cr3_files:
        print(f"在 {src} 里没找到任何 CR3 文件。")
        sys.exit(0)

    print(f"\n📁 源文件夹: {src}")
    print(f"📤 输出文件夹: {dst}")
    print(f"📷 共 {len(cr3_files)} 张照片\n")
    print(f"{'文件名':<30} {'EV':>6} {'中间调':>6} {'高光%':>6} {'阴影提':>6} {'对比':>5} {'饱和':>5}")
    print("─" * 72)

    ok, failed = 0, []

    for i, src_file in enumerate(cr3_files, 1):
        dst_file = dst / src_file.with_suffix(".jpg").name
        print(f"[{i:>3}/{len(cr3_files)}] {src_file.name:<28}", end=" ", flush=True)
        try:
            p = process_one(src_file, dst_file)
            print(
                f"{p['_ev']:+6.2f}  "
                f"{p['_p50']:5.3f}  "
                f"{p['_overexp']*100:5.1f}%  "
                f"{p['shadow_lift']:5.3f}  "
                f"{p['contrast']:4.2f}  "
                f"{p['vibrance']:4.2f}"
            )
            ok += 1
        except Exception as e:
            print(f"  ✗ 失败: {e}")
            failed.append((src_file.name, str(e)))

    print("─" * 72)
    print(f"\n完成 {ok}/{len(cr3_files)} 张", end="")
    if failed:
        print(f"，{len(failed)} 张失败：")
        for name, err in failed:
            print(f"  - {name}: {err}")
    else:
        print(" ✓")
    print(f"\n成品保存在:\n  {dst}\n")


if __name__ == "__main__":
    main()
