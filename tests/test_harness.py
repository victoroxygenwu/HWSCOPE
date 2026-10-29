import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import gen_conf
import mkvariants
import run_tests


class HarnessTests(unittest.TestCase):
    def test_variants_create_missing_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            source = root / "source.asm"
            source.write_text("VARIANT EQU 0\nMOV AX, BX\n", encoding="utf-8")
            with patch.object(mkvariants, "SRC", source), patch.object(
                mkvariants, "OUTDIR", root / "missing"
            ):
                mkvariants.make(1, "HWV.ASM")
            self.assertEqual((root / "missing/HWV.ASM").read_text(),
                             "VARIANT EQU 1\nMOV AX, BX\n")

    def test_emulator_specific_startup_options(self):
        conf = pathlib.Path("/tmp/test.conf")
        for name in ("dosbox-x", "dosbox-x.exe"):
            cmd = run_tests.dosbox_command(pathlib.Path(name), conf)
            self.assertEqual(cmd[1:3], ["-defaultconf", "-nopromptfolder"])
        self.assertEqual(run_tests.dosbox_command(pathlib.Path("dosbox"), conf),
                         ["dosbox", "-conf", str(conf)])

    def test_explicit_missing_emulator_does_not_silently_fall_back(self):
        with patch.dict(os.environ, {"HWSCOPE_DOSBOX": "missing-emulator"}), patch(
            "shutil.which", return_value=None
        ):
            with self.assertRaises(FileNotFoundError):
                run_tests.find_dosbox()

    def test_process_detection_with_executable_paths(self):
        result = subprocess.CompletedProcess([], 0, "/usr/bin/python\n/opt/bin/dosbox-x\n", "")
        with patch.object(run_tests.sys, "platform", "darwin"), patch.object(
            run_tests, "sh", return_value=result
        ):
            self.assertTrue(run_tests.dosbox_running())

    def test_process_detection_with_csv_output(self):
        result = subprocess.CompletedProcess([], 0, '"DOSBox.exe","42","Console"\n', "")
        with patch.object(run_tests.sys, "platform", "win32"), patch.object(
            run_tests, "sh", return_value=result
        ):
            self.assertTrue(run_tests.dosbox_running())

    def test_generated_runs_are_isolated_and_mount_paths_are_quoted(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            tools = base / "工具"
            tools.mkdir()
            for name in ("MASM.EXE", "LINK.EXE"):
                (tools / name).write_bytes(name.encode())
            root = base / "project"
            for name in ("src/HWSCOPE.ASM", "_tmp_extract/HWV.ASM", "_tmp_extract/HWD.ASM",
                         "tests/KEYHOOK.ASM", "tests/RUNALL.BAT"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture\n")
            runs = base / "run space"
            with patch.dict(os.environ, {"HWSCOPE_RUN_BASE": str(runs)}), patch.object(
                gen_conf, "MASM_TOOLS", tools
            ), patch.object(gen_conf, "ROOT", root), patch.object(gen_conf, "TESTS", root / "tests"):
                gen_conf.copy_tree()
                first = gen_conf.RUN
                (first / "keep.txt").write_text("keep")
                gen_conf.copy_tree()
                self.assertNotEqual(first, gen_conf.RUN)
                self.assertEqual((first / "keep.txt").read_text(), "keep")
                gen_conf.write_conf()
                text = (gen_conf.RUN / "test.conf").read_text(encoding="ascii")
                self.assertIn(f'mount c "{gen_conf.RUN / "tools"}"', text)
                self.assertIn(f'mount d "{gen_conf.RUN}"', text)
                self.assertEqual((gen_conf.RUN / "tools/MASM.EXE").read_bytes(), b"MASM.EXE")

    def test_missing_tools_do_not_create_or_remove_run_data(self):
        with tempfile.TemporaryDirectory() as directory:
            base = pathlib.Path(directory)
            with patch.dict(os.environ, {"HWSCOPE_RUN_BASE": str(base / "runs")}), patch.object(
                gen_conf, "MASM_TOOLS", base / "missing"
            ):
                with self.assertRaises(SystemExit):
                    gen_conf.copy_tree()
            self.assertFalse((base / "runs").exists())


if __name__ == "__main__":
    unittest.main()
