#!/usr/bin/env python3
# mkvariants.py - 从 src/HWSCOPE.ASM 同源生成验证/调试变体
# 只修改 VARIANT EQU 行，杜绝提交版与调试版行为漂移（风险 R10）
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "HWSCOPE.ASM"
OUTDIR = ROOT / "_tmp_extract"


def make(variant: int, name: str) -> None:
    text = SRC.read_text(encoding="utf-8")
    new, n = re.subn(
        r"(?m)^VARIANT\s+EQU\s+\d+\s*$",
        f"VARIANT EQU {variant}",
        text,
    )
    if n != 1:
        sys.exit(f"ERROR: VARIANT 行匹配失败 (n={n})，请检查 HWSCOPE.ASM 头部")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    # write_text 默认 UTF-8 无 BOM，符合 MASM 要求
    (OUTDIR / name).write_text(new, encoding="utf-8")
    print(f"[mkvariants] {name} <- HWSCOPE.ASM (VARIANT={variant})")


if __name__ == "__main__":
    make(1, "HWV.ASM")
    make(2, "HWD.ASM")
