# HWSCOPE — 汇编硬件透视仪

用 16 位 DOS 汇编（MASM 5.00 语法）编写的单文件硬件测量程序（1571 行 / 29 过程）。它在 DOSBox 虚拟机中对六项硬件指标进行定量测量，并以 VGA 13h（320×200×256 色）图形仪表盘展示结果，附带自动演示动画与按键交互（任意键重测一轮 / ESC 退出）。

> ⚠️ **测量语义**：全部数值是「DOSBox 模拟层 + 宿主计算机」的合成性能指标，不是裸金属硬件参数；宿主不同、`cycles` 设置不同，数字不可比。详见设计文档第 8 章。

## 测量指标

| 指标 | 显示标签 | 测量方法 |
|------|----------|----------|
| CPU 整数基准 | CPU OPS/S | 混合 ALU 指令循环，经 18.2 Hz tick 计时 |
| FPU 浮点基准 | FPU FLOPS | x87 浮点指令循环 |
| 常规内存容量 | MEM KB | INT 12H（DOS 结构上限恒 640 KB） |
| RAM 带宽 | RAM BW | 内存到内存块传送（REP MOVSW）吞吐 |
| 显存带宽 | VRAM BW | 内存到 A000 段写入吞吐 |
| 磁盘顺序读吞吐 | DISK KB/S | INT 21H 文件顺序读（自建自删 64 KB 临时文件） |

## 工程特性

- **测量与渲染彻底分离**：测量在文本模式完成、只写内存变量；渲染只读变量、直写显存。该分离是全部自动化断言的基础。
- **三变体同源**：源码只有一个 `VARIANT EQU` 行，由脚本生成提交版 / 验证版 / 调试版，提交版零测试代码，杜绝行为漂移。
- **无头测试基建**：SDL dummy 驱动下零窗口运行，经显存转储（DUMP.BIN）做逐像素断言、字体表结构断言、屏幕文本反向解码断言、trace 数值与屏幕条形端点同源断言，共 **40 项检查**。
- **提交版冒烟测试**：测试专用加载器钩住 INT 16H 向量注入按键，驱动提交版完整跑通「测量 → 渲染 → 演示 → 等键 → 重测 → ESC 退出」闭环。

## 环境要求

- DOSBox 0.74-3
- MASM 5.00 与 LINK 3.60（任意 DOS 可访问位置，挂载为 C 盘）

## 构建与运行

进入 DOSBox，挂载工具链与项目目录后：

```bat
C:\> masm HWSCOPE;
C:\> link HWSCOPE;
D:\> HWSCOPE
```

程序先以文本模式完成六项测量并打印 `MEASURING...`，随后切入图形界面：约 4 秒自动演示（依次高亮六个指标行，期间按任意键可跳过），之后进入交互——**任意键重测一轮，ESC 退出**。

## 目录结构

```
src/HWSCOPE.ASM          提交版源码（VARIANT=0，唯一事实源）
tests/                   自动化测试基建
  mkvariants.py            单行切 VARIANT 生成验证/调试变体
  gen_conf.py              生成 DOSBox 无头测试环境
  run_tests.py             一键全量：构建 → 运行 → 断言 → 报告
  check_dump.py            DUMP.BIN 逐像素 + 屏幕文本反向解码断言
  check_font.py            内置字体表源码级结构断言
  dump2png.py              显存转储渲染为 PNG
  gen_font.py + FONT16.BIN ROM 8x16 字体重采样为内置 8x8 字体表
  fix_testdisk.py          TEST_DISK 历史修复脚本（存档）
  KEYHOOK.ASM              INT 16H 钩子 + EXEC 冒烟加载器（测试专用）
  RUNALL.BAT               DOS 侧构建与运行编排
HWSCOPE使用说明.md        运行方法 / 屏幕布局 / 测试基建说明
HWSCOPE设计文档.md        架构 / 算法 / 布局常量 / 踩坑记录 / 测试方法论 / 扩展路线图
HWSCOPE运行截图.png       主环境运行效果
```

## 运行测试

设置 `HWSCOPE_MASM_DIR` 指向含 `MASM.EXE`、`LINK.EXE` 的目录，然后运行：

```bat
python tests/run_tests.py
```

脚本从 PATH 查找 `dosbox-x` 或 `dosbox`，也可通过 `HWSCOPE_DOSBOX` 指定可执行文件。工具链复制到每次独立创建的 ASCII 临时目录，项目路径可以包含中文；如果系统临时目录包含非 ASCII 字符，可用 `HWSCOPE_RUN_BASE` 指定一个 ASCII 父目录。运行目录与日志会保留，不会清空此前运行。

完整流程依次执行四构件构建、HWV、HWD 五轮吞吐测量，以及 KEYHOOK 注入 X／ESC 的提交版两轮测量，共 40 项检查。默认总时限为 360 秒，可通过 `HWSCOPE_TIMEOUT`（秒）调整；数值量程、稳定性和图形断言阈值不随总时限改变。DOSBox-X 自动使用默认配置并跳过启动目录选择提示，避免无头运行等待交互。

结果写入 `tests/out/<时间>/report.txt`，`run.json` 记录各阶段耗时和模拟器退出码，`dosbox.log` 保存模拟器日志；`tests/env.json` 指向本次独立运行目录。宿主侧启动与目录生成回归检查可单独运行 `python -m unittest discover -s tests -p test_harness.py`。
