#!/usr/bin/env python3
# run_tests.py - 测试编排：构建 -> 运行 -> 断言 -> 截图 -> 报告
# 用法：D:\Python313\python.exe run_tests.py [--window]
#   默认无头（SDL dummy 驱动，不弹 DOSBox 窗口）；--window 弹窗并可截屏
#   无头模式下"截图"由 DUMP.BIN -> PNG（dump2png.py）替代，屏幕内容
#   断言全部走 DUMP.BIN 字节分析，与是否弹窗无关
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
PY = sys.executable
# 完整流程包含 HWV 一轮、HWD 五轮吞吐和提交版两轮测量。
TIMEOUT = float(os.environ.get("HWSCOPE_TIMEOUT", "360"))
HEADLESS = "--window" not in sys.argv

sys.path.insert(0, str(TESTS))
import check_dump  # noqa: E402
import check_font  # noqa: E402
import dump2png  # noqa: E402


def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, errors="replace")


def find_dosbox() -> pathlib.Path:
    configured = os.environ.get("HWSCOPE_DOSBOX")
    if configured:
        found = shutil.which(configured)
        if found:
            return pathlib.Path(found)
        raise FileNotFoundError(f"HWSCOPE_DOSBOX 不可执行：{configured}")
    for name in ("dosbox-x", "dosbox", "DOSBox.exe"):
        found = shutil.which(name)
        if found:
            return pathlib.Path(found)
    legacy = pathlib.Path(r"D:\dosbox\DOSBox.exe")
    if legacy.is_file():
        return legacy
    raise FileNotFoundError("未找到 DOSBox，请设置 HWSCOPE_DOSBOX 或加入 PATH")


def dosbox_running() -> bool:
    if sys.platform == "win32":
        r = sh(["tasklist", "/FO", "CSV", "/NH"])
        names = [line.split(',')[0].strip('"').lower() for line in r.stdout.splitlines()]
    else:
        r = sh(["ps", "-A", "-o", "comm="])
        names = [pathlib.Path(line.strip()).name.lower() for line in r.stdout.splitlines()]
    if r.returncode:
        raise RuntimeError("无法检查模拟器进程：" + r.stderr.strip())
    return any(n in ("dosbox", "dosbox-x", "dosbox.exe", "dosbox-x.exe") for n in names)


def dosbox_command(executable, conf):
    cmd = [str(executable)]
    if "dosbox-x" in executable.name.lower():
        cmd += ["-defaultconf", "-nopromptfolder"]
    return cmd + ["-conf", str(conf)]


def shoot(path: pathlib.Path) -> bool:
    try:
        import ctypes
        from PIL import ImageGrab
    except Exception as e:
        print(f"[shoot] import failed: {e}")
        return False
    try:
        if sys.platform == "win32":
            h = ctypes.windll.user32.FindWindowW("SDL_app", None)
            if h:
                ctypes.windll.user32.SetForegroundWindow(h)
                time.sleep(0.3)
        img = ImageGrab.grab()
        img.save(str(path))
        return True
    except Exception as e:
        print(f"[shoot] failed: {e}")
        return False


def report(outdir, checks):
    lines = []
    for name, ok, detail in checks:
        state = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        lines.append(f"{state:4}  {name}  {detail}")
    failed = [c for c in checks if c[1] is False]
    skipped = [c for c in checks if c[1] is None]
    text = "\n".join([
        "",
        "==== 测试汇总 ====",
        f"总计 {len(checks)} 项，通过 {len(checks) - len(failed) - len(skipped)} 项，"
        f"失败 {len(failed)} 项，跳过 {len(skipped)} 项",
        *lines,
    ])
    (outdir / "report.txt").write_text(text, encoding="utf-8")
    print(text)
    return 1 if failed else 0


def main() -> int:
    ts = time.strftime("%Y%m%d_%H%M%S")
    outdir = ROOT / "tests" / "out" / ts
    outdir.mkdir(parents=True, exist_ok=True)
    checks = []

    def log_ok(name, ok, detail=""):
        checks.append((name, bool(ok) if ok is not None else None, str(detail)))
        state = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
        print(f"[{state}] {name} {detail}")

    def log_skip(name, detail=""):
        checks.append((name, None, str(detail)))
        print(f"[SKIP] {name} {detail}")

    # 在生成运行目录前检查依赖与已有实例，不干扰其它测量。
    executable = find_dosbox()
    if not TIMEOUT > 0:
        raise ValueError("HWSCOPE_TIMEOUT 必须大于零")
    if dosbox_running():
        log_ok("dosbox_start", False, "已有 DOSBox 实例在运行，请先关闭再测")
        return report(outdir, checks)

    # 1. 生成变体与 DOSBox 环境
    r = sh([PY, str(TESTS / "mkvariants.py")])
    log_ok("mkvariants", r.returncode == 0, (r.stdout + r.stderr).strip())
    if r.returncode != 0:
        return report(outdir, checks)

    # 1.5 字体表结构完整性（源码级硬门，先于 90s 运行）：
    #     2026-10-23 实测 bug——字体表曾切取 8x16 上半 8 行，字母底横/底弧
    #     全丢（O 显示成 ∩、U 显示成 ||、E 与 F 同形），而只查"有像素"的
    #     屏幕断言全部漏过。此门从结构上封死：字母底行必须有内容、可打印
    #     字符不得重复（白名单除外）、E≠F、数字互异
    font = check_font.parse_font(ROOT / "src" / "HWSCOPE.ASM")
    fr = check_font.check_font(font)
    font_ok = (fr["entries_ok"] and fr["dups_ok"] and fr["ef_distinct"]
               and fr["letters_bottom_ok"] and fr["digits_ok"]
               and fr["colon_ok"] and fr["dot_ok"])
    log_ok("font_integrity", font_ok,
           f"entries={fr['entries']} dups={fr['dup_pairs']} "
           f"bottom_bad={fr['letters_bottom_bad']} "
           f"digits_bad={fr['digits_bad']} ef_distinct={fr['ef_distinct']}")
    if not font_ok:
        return report(outdir, checks)

    r = sh([PY, str(TESTS / "gen_conf.py")] +
           ([] if HEADLESS else ["--window"]))
    log_ok("gen_conf", r.returncode == 0, (r.stdout + r.stderr).strip())
    if r.returncode != 0:
        return report(outdir, checks)
    env = json.loads((TESTS / "env.json").read_text(encoding="utf-8"))
    run_dir = pathlib.Path(env["run_root"])

    # 2. 清理旧标记（含总完成标记）
    for m in ("HWDONE.$$$", "HWRENDER.$$$", "DUMP.BIN"):
        p = run_dir / m
        if p.exists():
            p.unlink()
    complete = run_dir / "logs" / "RUNALL.OK"
    if complete.exists():
        complete.unlink()

    # 3. 启动 DOSBox
    conf = run_dir / "test.conf"
    dosbox_env = dict(os.environ)
    if HEADLESS:
        # 无头：SDL dummy 驱动，全程不弹窗口（屏幕断言走 DUMP.BIN，不受影响）
        dosbox_env["SDL_VIDEODRIVER"] = "dummy"
        dosbox_env["SDL_AUDIODRIVER"] = "dummy"
    host_log = (outdir / "dosbox.log").open("w", encoding="utf-8")
    proc = subprocess.Popen(dosbox_command(executable, conf), env=dosbox_env,
                            cwd=run_dir, stdout=host_log, stderr=subprocess.STDOUT)
    log_ok("dosbox_start", True, f"pid={proc.pid} headless={HEADLESS}")

    # 4. 等待渲染标记 -> 截图；等待总完成标记（runall_complete.log）
    #    RUNALL.OK 由 RUNALL.BAT 在 HWV 转储 + HWD 运行完毕后写入，
    #    是唯一权威完成信号（HWDONE 只表示单个变体退出，不能作为整体完成依据）
    #    注意：文件名必须 <=8.3，DOS COMMAND 会把长名重定向目标截断
    rendered = run_dir / "HWRENDER.$$$"
    t0 = time.time()
    shot_done = False
    run_ok = False
    stages = []
    stage_path = run_dir / "logs" / "STAGE.TXT"
    while time.time() - t0 < TIMEOUT:
        if stage_path.exists():
            stage = stage_path.read_text(errors="replace").strip()
            if stage and (not stages or stage != stages[-1][0]):
                stages.append((stage, round(time.time() - t0, 2)))
                print(f"[stage] {stage} elapsed={stages[-1][1]}s", flush=True)
        if rendered.exists() and not shot_done and not HEADLESS:
            time.sleep(1.0)  # 等窗口绘制
            ok = shoot(outdir / "m0_pattern.png")
            log_ok("screenshot", ok,
                   str(outdir / "m0_pattern.png") if ok else "截图失败")
            shot_done = True
        if complete.exists():
            run_ok = True
            break
        if proc.poll() is not None:
            break  # DOSBox 提前退出
        time.sleep(0.5)
    log_ok("run_complete", run_ok,
           "RUNALL.OK 标记已生成" if run_ok else "超时或提前退出")

    # 4b. 屏幕图像证据：无头模式用 DUMP.BIN 渲染 PNG（等价"截图"）；
    #     弹窗模式两种都出（真截图 + 显存转储渲染，便于比对）
    dump = run_dir / "DUMP.BIN"
    png_dump = outdir / "m0_dump.png"
    ok = dump2png.render(dump, png_dump) if dump.exists() else False
    log_ok("dump_render", ok,
           str(png_dump) if ok else "DUMP.BIN 缺失或尺寸不符")
    if HEADLESS:
        log_ok("screenshot", ok,
               f"{png_dump}（无头：显存转储渲染）" if ok else "DUMP.BIN 缺失")

    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    host_log.close()
    (outdir / "run.json").write_text(json.dumps({
        "command": dosbox_command(executable, conf),
        "run_root": str(run_dir), "timeout": TIMEOUT,
        "elapsed_seconds": round(time.time() - t0, 2),
        "exit_code": proc.returncode, "stages": stages,
    }, indent=2), encoding="utf-8")

    # 5. 构建断言（EXE 存在 + 日志无 error）
    for variant, tag, exe in (("s", "HWSCOPE", "HWSCOPE.EXE"),
                              ("v", "HWV", "HWV.EXE"),
                              ("d", "HWD", "HWD.EXE"),
                              ("k", "KEYHOOK", "KEYHOOK.EXE")):
        logpath = run_dir / "logs" / f"build_{variant}.log"
        exe_ok = (run_dir / "src" / exe).exists()
        txt = logpath.read_text(errors="replace") if logpath.exists() else ""
        cleaned = "\n".join(
            l for l in txt.splitlines()
            if not re.match(r"\s*\d+\s+(Warning|Severe)\s+Errors\s*$", l, re.I)
        )
        no_err = "error" not in cleaned.lower()
        log_ok(f"build_{tag}", exe_ok and no_err,
               f"exe={'Y' if exe_ok else 'N'} log_err={'Y' if not no_err else 'N'}")

    # 6. HWD 调试日志断言
    hwd_log = run_dir / "logs" / "hwd.log"
    hwd_txt = hwd_log.read_text(errors="replace") if hwd_log.exists() else ""
    log_ok("hwd_trace", "[M0] pipeline=text-mode-debug-ok" in hwd_txt,
           hwd_txt.strip().replace("\r\n", " | ")[:120])

    # 6a. 提交版冒烟断言（KEYHOOK 钩 INT 16H + EXEC 驱动交互主循环）：
    #     smoke.log = SMOKE-START + 提交版 stdout + SMOKE-DONE。
    #     - smoke_done：BAT 收回到控制权（KEYHOOK 正常退出并透传退出码）
    #     - smoke_loop：恰两行 MEASURING...（首轮 + 'X' 触发的重测轮，
    #       随后 ESC 退出；少于 2 行说明按键注入/循环路径断，多于 2 行
    #       说明退出键失效——2026-10-23 审核缺口"提交版零运行时覆盖"的防线）
    #     - smoke_clean：DISK.BIN 被测量子程序自删（无临时文件残留）
    smoke_log = run_dir / "logs" / "smoke.log"
    smoke_txt = smoke_log.read_text(errors="replace") if smoke_log.exists() else ""
    log_ok("smoke_done", "SMOKE-DONE" in smoke_txt,
           smoke_txt.strip().replace("\r\n", " | ")[:120] or "smoke.log 缺失")
    meas_n = smoke_txt.count("MEASURING...")
    log_ok("smoke_loop", meas_n == 2, f"MEASURING count={meas_n} (expect 2)")
    disk_leftover = (run_dir / "DISK.BIN").exists()
    log_ok("smoke_clean", not disk_leftover,
           "DISK.BIN 残留" if disk_leftover else "无残留")

    # 7. DUMP 显存断言（传入字体表：附带屏幕标签端到端解码断言）
    dump = run_dir / "DUMP.BIN"
    res = (check_dump.check_dump(dump, font)
           if dump.exists() else {})
    log_ok("dump_size", res.get("size_ok"), f"size={res.get('size')}")
    log_ok("dump_nonblack", res.get("nonzero_ok"), f"nonzero={res.get('nonzero')}")
    log_ok("dump_colors", res.get("has_bars"), f"colors={res.get('colors_found')}")

    # 7a. 屏幕标签端到端断言（字体表反向解码逐字符比对；
    #     2026-10-23 字体缺半截 bug 的屏幕级防线，如 F 曾被渲染成 E）
    if res.get("screen_text_ok") is not None:
        log_ok("screen_text", res.get("screen_text_ok"),
               f"bad={res.get('screen_text_bad')}")

    # 7b. M1 文本与 32 位数字断言
    log_ok("m1_text", res.get("text_ok"),
           f"white={res.get('white_px')} zone_nz={res.get('text_zone_nz')}")
    log_ok("m1_dec32", res.get("num_ok"),
           f"yellow={res.get('yellow_px')} zone_nz={res.get('num_zone_nz')}")

    # 7b2. M2 CPU 基准屏幕区域断言
    log_ok("m2_cpu_zone", res.get("cpu_zone_ok"),
           f"cpu_zone_nz={res.get('cpu_zone_nz')}")

    # 7c. HWD 调试版 M1 trace
    log_ok("m1_hwd_trace", "[M1] font+text+dec32 pipeline=ok" in hwd_txt,
           "M1 trace missing" if "[M1]" not in hwd_txt else "ok")

    # 7d. M2 CPU 基准断言（值合理性：DOSBox 下约 1e6~1e8 ops/s）
    m = re.search(r"\[M2\] cpu_ops=(\d+)", hwd_txt)
    cpu_val = int(m.group(1)) if m else 0
    log_ok("m2_cpu_value", 1000 < cpu_val < 1_000_000_000,
           f"cpu_ops={cpu_val} ops/s")

    def spread(vals):
        return (max(vals) - min(vals)) / (sum(vals) / len(vals)) if vals else 1.0

    # 7d2. M4 FPU 基准断言（值合理性：DOSBox x87 软模拟约 1e5~1e8 FLOPS）
    m = re.search(r"\[M4\] fpu_flops=(\d+)", hwd_txt)
    fpu_val = int(m.group(1)) if m else 0
    log_ok("m4_fpu_value", 1000 < fpu_val < 1_000_000_000,
           f"fpu_flops={fpu_val} FLOPS")
    log_ok("m4_fpu_zone", res.get("fpu_zone_ok"),
           f"fpu_zone_nz={res.get('fpu_zone_nz')}")

    # 7d3. M5 磁盘顺序读断言（值合理性：DOSBox int 21h 读路径走宿主页缓存，
    #      量级 1e5~1e7 KB/s）+ 屏幕区域 + 5 轮波动（宿主 I/O 有抖动，
    #      阈值放宽到 15%）
    dsk_vals = [int(x) for x in re.findall(r"\[M5\] disk_kbs=(\d+)", hwd_txt)]
    log_ok("m5_disk_values",
           len(dsk_vals) == 5 and all(1000 < v < 10_000_000 for v in dsk_vals),
           f"disk_kbs={dsk_vals}")
    log_ok("m5_disk_zone", res.get("disk_zone_ok"),
           f"disk_zone_nz={res.get('disk_zone_nz')}")
    log_ok("m5_disk_stability",
           len(dsk_vals) == 5 and spread(dsk_vals) <= 0.15,
           f"disk_spread={spread(dsk_vals):.3f}")

    # 7e. M3 内存三项断言
    # mem_kb 精确值（DOSBox int 12h 恒 640，与 conf memsize 无关）
    m = re.search(r"\[M3\] mem_kb=(\d+)", hwd_txt)
    mem_val = int(m.group(1)) if m else 0
    log_ok("m3_mem_value", mem_val == 640, f"mem_kb={mem_val}")

    # 带宽 5 次测量：合理范围（主环境约 3000 KB/s，量程自适应后不应为 0
    # 或爆表；上限 1e6 覆盖 cycles=fixed 高速宿主）+ 波动 ≤10%
    ram_vals = [int(x) for x in re.findall(r"\[M3\] ram_bw=(\d+)", hwd_txt)]
    vram_vals = [int(x) for x in re.findall(r"\[M3\] vram_bw=(\d+)", hwd_txt)]
    log_ok("m3_rambw_values",
           len(ram_vals) == 5 and all(50 < v < 1_000_000 for v in ram_vals),
           f"ram_bw={ram_vals}")
    log_ok("m3_vrambw_values",
           len(vram_vals) == 5 and all(50 < v < 1_000_000 for v in vram_vals),
           f"vram_bw={vram_vals}")

    log_ok("m3_bw_stability",
           len(ram_vals) == 5 and len(vram_vals) == 5
           and spread(ram_vals) <= 0.10 and spread(vram_vals) <= 0.10,
           f"ram_spread={spread(ram_vals):.3f} vram_spread={spread(vram_vals):.3f}")

    # M3 屏幕数值区域
    log_ok("m3_zones",
           res.get("mem_zone_ok") and res.get("rambw_zone_ok") and res.get("vrambw_zone_ok"),
           f"mem={res.get('mem_zone_nz')} ram={res.get('rambw_zone_nz')} "
           f"vram={res.get('vrambw_zone_nz')}")

    # M3 条形端点与数值成比例（HWV trace 值与屏幕条严格同源）
    hwv_log = run_dir / "logs" / "hwv.log"
    hwv_txt = hwv_log.read_text(errors="replace") if hwv_log.exists() else ""
    for tag, key, pat in (("ram", "ram_bw", r"\[M3\] ram_bw=(\d+)"),
                          ("vram", "vram_bw", r"\[M3\] vram_bw=(\d+)")):
        m = re.search(pat, hwv_txt)
        val = int(m.group(1)) if m else 0
        exp_end = 55 + min(val >> 6, 257)   # M7r：条起点 x=56，顶格 257
        act_end = res.get(f"{tag}_bar_end", -1)
        log_ok(f"m3_bar_{tag}", abs(act_end - exp_end) <= 4,
               f"end={act_end} expect={exp_end} (val={val})")

    # 7f. M6 UI 外壳断言（边框像素 / 状态行 / 演示完成 trace / 高亮擦除）
    log_ok("m6_frame", res.get("frame_ok"),
           f"frame_px={res.get('frame_px')}")
    log_ok("m6_status", res.get("status_zone_ok"),
           f"status_zone_nz={res.get('status_zone_nz')}")
    log_ok("m6_demo_trace", "[M6] demo=ok" in hwv_txt,
           "M6 trace missing" if "[M6]" not in hwv_txt else "ok")
    log_ok("m6_demo_erased", res.get("demo_erased_ok"),
           f"demo_leftover={res.get('demo_leftover')}")

    # 8. 证据回传工作区
    if (run_dir / "logs").exists():
        shutil.copytree(run_dir / "logs", outdir / "logs", dirs_exist_ok=True)
    if dump.exists():
        shutil.copy2(dump, outdir / "DUMP.BIN")

    return report(outdir, checks)


if __name__ == "__main__":
    sys.exit(main())
