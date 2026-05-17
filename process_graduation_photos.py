#!/usr/bin/env python3
"""
毕业照批量处理脚本
处理带有 Mac Finder 红色或黄色标签的 Canon CR3 RAW 文件
用法: python3 process_graduation_photos.py /path/to/your/photos
"""

import sys
import os
import subprocess
import struct
import argparse
from pathlib import Path

import rawpy
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance


# ─── Finder 标签读取 ─────────────────────────────────────────────────────────

def get_finder_label_color(filepath: Path) -> int:
    """
    读取 Mac Finder 颜色标签（旧式数字标签）。
    返回值对应 Finder 标签: 0=无, 1=灰, 2=绿, 3=紫, 4=蓝, 5=黄, 6=红, 7=橙
    """
    try:
        result = subprocess.run(
            ["mdls", "-name", "kMDItemFSLabel", "-raw", str(filepath)],
            capture_output=True, text=True, timeout=5
        )
        val = result.stdout.strip()
        if val and val != "(null)":
            return int(val)
    except Exception:
        pass
    return 0


def get_finder_tag_names(filepath: Path) -> list[str]:
    """
    读取 Mac Finder 新式标签名（字符串标签，如 "Red", "Yellow"）。
    macOS 10.9+ 引入的命名标签系统。
    """
    try:
        import xattr
        tags_raw = xattr.getxattr(str(filepath), "com.apple.metadata:_kMDItemUserTags")
        # plist 二进制格式，用 plistlib 解析
        import plistlib
        tags = plistlib.loads(tags_raw)
        return [t.split("\n")[0] for t in tags]  # 去掉可能的尾部换行+数字
    except Exception:
        pass

    # 降级方案：用 mdls 查询 kMDItemUserTags
    try:
        result = subprocess.run(
            ["mdls", "-name", "kMDItemUserTags", "-raw", str(filepath)],
            capture_output=True, text=True, timeout=5
        )
        raw = result.stdout.strip()
        if raw and raw != "(null)":
            # 格式如 ("Red","Yellow")
            tags = [t.strip().strip('"') for t in raw.strip("()").split(",")]
            return [t for t in tags if t]
    except Exception:
        pass

    return []


def has_red_or_yellow_label(filepath: Path) -> bool:
    """判断文件是否带有红色或黄色 Finder 标签。"""
    # 方法1：新式命名标签
    tag_names = get_finder_tag_names(filepath)
    color_map = {"Red", "Yellow", "红色", "黄色", "Orange", "橙色"}
    if any(t in color_map for t in tag_names):
        return True

    # 方法2：旧式数字标签 (5=黄, 6=红)
    label = get_finder_label_color(filepath)
    if label in (5, 6):
        return True

    return False


# ─── 图像处理 ────────────────────────────────────────────────────────────────

def process_raw(raw_path: Path, output_path: Path) -> None:
    """处理单个 CR3 RAW 文件并保存为 JPG。"""

    with rawpy.imread(str(raw_path)) as raw:
        # ── 基础 RAW 显影参数 ──────────────────────────────────────────────
        # use_camera_wb=True  自动白平衡（优先用相机元数据）
        # exp_shift=1.23      约 +0.3 EV (2^0.3 ≈ 1.23)
        # no_auto_bright=True 禁止 rawpy 自动提亮（我们手动控制）
        # output_bps=16       先用 16-bit 以保留最大动态范围，后续再处理
        rgb16 = raw.postprocess(
            use_camera_wb=True,
            no_auto_bright=True,
            exp_shift=1.23,          # +0.3 EV
            output_bps=16,
            bright=1.0,
            highlight=2,             # highlight=2 → "blend" 模式，保留高光细节
            fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Full,
        )

    # 转 float32 [0, 1] 便于数学操作
    img_f = rgb16.astype(np.float32) / 65535.0

    # ── 高光压制 ──────────────────────────────────────────────────────────
    # 对亮度高于 0.85 的区域做软压制，保留细节
    highlight_threshold = 0.85
    highlight_strength = 0.30        # 压制强度
    mask = np.clip((img_f - highlight_threshold) / (1.0 - highlight_threshold), 0, 1)
    img_f = img_f - mask * (img_f - highlight_threshold) * highlight_strength

    # ── 阴影提亮 ──────────────────────────────────────────────────────────
    # 对亮度低于 0.35 的区域做软提亮
    shadow_threshold = 0.35
    shadow_lift = 0.08               # 提亮幅度
    shadow_mask = np.clip(1.0 - img_f / shadow_threshold, 0, 1)
    img_f = img_f + shadow_mask * shadow_lift * (1.0 - img_f)

    img_f = np.clip(img_f, 0, 1)

    # 转 8-bit PIL Image 进行后续操作
    img8 = (img_f * 255.0).astype(np.uint8)
    pil_img = Image.fromarray(img8, mode="RGB")

    # ── 对比度 (+5%) ──────────────────────────────────────────────────────
    pil_img = ImageEnhance.Contrast(pil_img).enhance(1.05)

    # ── 自然饱和度（柔和提升，避免过饱和） ─────────────────────────────
    # 先转 HSV 做选择性饱和，低饱和区域提升更多
    pil_img = _natural_vibrance(pil_img, vibrance=0.12)

    # ── 输出锐化（轻度 USM） ─────────────────────────────────────────────
    # radius=0.8, percent=60, threshold=3 — 轻柔输出锐化
    pil_img = pil_img.filter(ImageFilter.UnsharpMask(radius=0.8, percent=60, threshold=3))

    # ── 保存 ──────────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pil_img.save(str(output_path), format="JPEG", quality=95, subsampling=0)


def _natural_vibrance(img: Image.Image, vibrance: float = 0.1) -> Image.Image:
    """
    自然饱和度：对低饱和像素提升更多，避免高饱和区域过饱和。
    vibrance: 0~1 之间，0.12 约等于 Lightroom 的 +20 自然饱和度
    """
    arr = np.array(img, dtype=np.float32) / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]

    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    saturation = np.where(cmax > 0, (cmax - cmin) / cmax, 0.0)

    # 饱和度越低，提升越多
    boost = vibrance * (1.0 - saturation)[..., np.newaxis]
    gray = (0.299 * r + 0.587 * g + 0.114 * b)[..., np.newaxis]
    arr_new = arr + (arr - gray) * boost

    arr_new = np.clip(arr_new, 0, 1)
    return Image.fromarray((arr_new * 255).astype(np.uint8), mode="RGB")


# ─── 主流程 ──────────────────────────────────────────────────────────────────

def scan_tagged_files(folder: Path) -> list[Path]:
    """递归扫描文件夹，找出带红色/黄色 Finder 标签的 CR3 文件。"""
    cr3_files = list(folder.rglob("*.CR3")) + list(folder.rglob("*.cr3"))
    print(f"  共发现 {len(cr3_files)} 个 CR3 文件，正在检查 Finder 标签...")

    tagged = []
    for f in cr3_files:
        if has_red_or_yellow_label(f):
            tagged.append(f)
            print(f"  ✓ 已标记: {f.name}")

    return tagged


def main():
    parser = argparse.ArgumentParser(description="批量处理带 Finder 标签的毕业照 CR3 文件")
    parser.add_argument("folder", help="照片所在文件夹路径")
    parser.add_argument(
        "--all", action="store_true",
        help="跳过标签检查，处理文件夹内所有 CR3 文件（用于测试）"
    )
    args = parser.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        print(f"错误：找不到文件夹 {folder}")
        sys.exit(1)

    output_dir = folder / "exported"
    print(f"\n📁 扫描文件夹: {folder}")
    print(f"📤 输出目录:   {output_dir}\n")

    if args.all:
        files = list(folder.rglob("*.CR3")) + list(folder.rglob("*.cr3"))
        print(f"  --all 模式：处理全部 {len(files)} 个 CR3 文件")
    else:
        files = scan_tagged_files(folder)

    if not files:
        print("\n未找到带红色/黄色 Finder 标签的 CR3 文件。")
        print("提示：如需处理全部文件，请添加 --all 参数。")
        sys.exit(0)

    print(f"\n共 {len(files)} 张照片待处理，开始转换...\n")
    ok, failed = 0, []

    for i, src in enumerate(files, 1):
        dest = output_dir / src.with_suffix(".jpg").name
        print(f"  [{i}/{len(files)}] {src.name} → exported/{dest.name} ", end="", flush=True)
        try:
            process_raw(src, dest)
            print("✓")
            ok += 1
        except Exception as e:
            print(f"✗ ({e})")
            failed.append((src.name, str(e)))

    print(f"\n完成：{ok} 张成功", end="")
    if failed:
        print(f"，{len(failed)} 张失败：")
        for name, err in failed:
            print(f"  - {name}: {err}")
    else:
        print()

    print(f"\n输出文件夹: {output_dir}")


if __name__ == "__main__":
    main()
