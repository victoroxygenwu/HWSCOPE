@echo off
rem HWSCOPE M0: build three variants and run (called by DOSBox autoexec)
rem workdir: D: (mount root of the run tree, flat layout)
rem order: HWV first, then HWD -- HWDONE.$$$ must not appear before
rem       DUMP.BIN is written, otherwise the host harness may read it early
d:
path=%path%;c:\
if not exist logs\nul md logs
if not exist src\nul md src
copy HWSCOPE.ASM src\HWSCOPE.ASM >nul
copy HWV.ASM src\HWV.ASM >nul
copy HWD.ASM src\HWD.ASM >nul
copy KEYHOOK.ASM src\KEYHOOK.ASM >nul
cd src
echo BUILD > ..\logs\STAGE.TXT
masm HWSCOPE; > ..\logs\build_s.log
link HWSCOPE; >> ..\logs\build_s.log
masm HWV; > ..\logs\build_v.log
link HWV; >> ..\logs\build_v.log
masm HWD; > ..\logs\build_d.log
link HWD; >> ..\logs\build_d.log
masm KEYHOOK; > ..\logs\build_k.log
link KEYHOOK; >> ..\logs\build_k.log
cd ..
echo HWV > logs\STAGE.TXT
if exist src\HWV.EXE src\HWV.EXE > logs\hwv.log
echo HWD > logs\STAGE.TXT
if exist src\HWD.EXE src\HWD.EXE > logs\hwd.log
rem ---- 提交版冒烟（M7 审核缺口：提交版此前只构建不执行）----
rem KEYHOOK 钩住 INT 16H 后 EXEC 提交版 HWSCOPE.EXE，注入键表：
rem   X remeasures once, ESC exits. The host verifies two measurement lines.
rem   smoke.log 恰含两行 MEASURING...；DISK.BIN 已被测量子程序自删。
echo SMOKE-START > logs\smoke.log
echo SMOKE > logs\STAGE.TXT
if exist src\HWSCOPE.EXE if exist src\KEYHOOK.EXE src\KEYHOOK.EXE >> logs\smoke.log
if errorlevel 1 goto SMOKE_FAIL
echo SMOKE-DONE >> logs\smoke.log
goto FINISHED
:SMOKE_FAIL
echo SMOKE-FAIL >> logs\smoke.log
:FINISHED
echo DONE > logs\STAGE.TXT
echo RUNALL-COMPLETE > logs\RUNALL.OK
