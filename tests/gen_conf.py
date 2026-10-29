#!/usr/bin/env python3
# gen_conf.py - 生成 DOSBox 自动化测试环境（扁平化版）
# 策略：
#   1. 独立 ASCII 临时目录规避中文挂载问题，每次运行保留独立证据
#   2. 扁平结构：运行根直接放 ASM/BAT，去掉 _tmp_extract 长目录名
#      （DOS shell 对 >8 字符长目录名 cd 不稳定，见 M0 调试记录）
#   3. autoexec 只留 mount + CALL RUNALL.BAT，全部逻辑进 BAT
#      （autoexec 多行链存在竞态，cd 后命令可能丢失）
#   4. 无头模式（默认）：surface 后端配合 SDL_VIDEODRIVER=dummy，
#      屏幕内容靠 DUMP.BIN 转 PNG（dump2png.py）核对
# 用法：gen_conf.py [--window]   （--window 才弹窗，供人工查看仪表盘）
# 产出：
#   系统临时目录/hwscope-* - 运行根（BAT、四 ASM、tools/、src/、logs/）
#   运行根/test.conf
#   tests/env.json - 主机侧路径信息
import json
import os
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
RUN = None
MASM_TOOLS = pathlib.Path(os.environ.get("HWSCOPE_MASM_DIR", r"D:\masm-tools"))

HEADLESS = "--window" not in sys.argv


def copy_tree() -> None:
    global RUN
    tools = {}
    for name in ("MASM.EXE", "LINK.EXE"):
        path = MASM_TOOLS / name
        if not path.is_file():
            sys.exit(f"ERROR: {path} 缺失，请设置 HWSCOPE_MASM_DIR 为工具链目录")
        tools[name] = path
    base = pathlib.Path(os.environ.get("HWSCOPE_RUN_BASE", tempfile.gettempdir())).resolve()
    if not str(base).isascii():
        sys.exit("ERROR: 请通过 HWSCOPE_RUN_BASE 指定 ASCII 临时目录")
    base.mkdir(parents=True, exist_ok=True)
    RUN = pathlib.Path(tempfile.mkdtemp(prefix="hwscope-", dir=base))
    (RUN / "tools").mkdir()
    for name, path in tools.items():
        shutil.copy2(path, RUN / "tools" / name)
    # 主源码（提交版）
    shutil.copy2(ROOT / "src" / "HWSCOPE.ASM", RUN / "HWSCOPE.ASM")
    # 变体源码（mkvariants 已生成）
    for name in ("HWV.ASM", "HWD.ASM"):
        shutil.copy2(ROOT / "_tmp_extract" / name, RUN / name)
    # 冒烟加载器（INT 16H 钩 + EXEC，无头驱动提交版交互主循环）
    shutil.copy2(TESTS / "KEYHOOK.ASM", RUN / "KEYHOOK.ASM")
    # DOS 侧批处理（LF -> CRLF：DOSBox COMMAND 解析 LF-only BAT 会错乱）
    bat = (TESTS / "RUNALL.BAT").read_bytes()
    bat = bat.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    (RUN / "RUNALL.BAT").write_bytes(bat)


def write_conf() -> None:
    conf = RUN / "test.conf"
    lines = [
        "[sdl]",
    ]
    if HEADLESS:
        # 无头：无需 OpenGL 上下文，画面由显存转储检查
        lines += ["output=surface"]
    else:
        lines += ["output=opengl", "windowresolution=1024x640"]
    lines += [
        "",
        "[dosbox]",
        "memsize=16",
        "",
        "[cpu]",
        "core=normal",
        "cycles=auto",
        "fpu=true",
        "",
        "[autoexec]",
        f'mount c "{RUN / "tools"}"',
        f'mount d "{RUN}"',
        "call d:\\runall.bat",
        "exit",
        "",
    ]
    conf.write_text("\n".join(lines), encoding="ascii")
    print(f"[gen_conf] conf={conf} headless={HEADLESS}")


def write_env() -> None:
    env = {
        "mode": "flat",
        "headless": HEADLESS,
        "run_root": str(RUN),
        "src_dir": str(RUN / "src"),
        "logs_dir": str(RUN / "logs"),
    }
    (TESTS / "env.json").write_text(
        json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[gen_conf] run_root={RUN}")


if __name__ == "__main__":
    copy_tree()
    write_conf()
    write_env()
