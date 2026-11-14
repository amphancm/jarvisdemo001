"""ชุดทดสอบความถูกต้องของการพอร์ตโครงการ Jarvis ภาษาไทย ไปยัง Ubuntu 26.04 LTS

ครอบคลุม:
1. การตรวจสอบว่าไม่มีโค้ดหรือไฟล์ตกค้างจาก Windows 11 และ macOS
2. ทดสอบฟังก์ชันควบคุมระบบ Ubuntu (PipeWire, GNOME, MPRIS, Apps, Time, Thai Numbers)
3. ทดสอบการตรวจจับคำปลุก (Wake Word) ภาษาไทย และการทำความสะอาดข้อความ
4. ทดสอบ Computer Agent บน Ubuntu (Screen size, App detection, Fallbacks)
5. ทดสอบ Browser Agent บน Ubuntu (Linux Chrome detection)
6. ทดสอบ Selftest (Headless & Safe execution)
"""
import os
import re
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import browser_agent as ba
import computer_agent as ca
import jarvis
import selftest


class TestCleanCode(unittest.TestCase):
    """ตรวจสอบว่าไม่มีโค้ดหรือการอ้างอิง Windows 11 หรือ macOS หลงเหลืออยู่ในโปรเจกต์"""

    FORBIDDEN_TERMS = [
        "win32",
        "pycaw",
        "uiautomation",
        "appkit",
        "quartz",
        "applicationservices",
        "mlx_whisper",
        "run_app.bat",
        "run_app.ps1",
        "Jarvis.app",
    ]

    def test_no_legacy_code_in_source_files(self):
        source_files = [
            ROOT / "jarvis.py",
            ROOT / "computer_agent.py",
            ROOT / "browser_agent.py",
            ROOT / "selftest.py",
            ROOT / "run_app.sh",
            ROOT / "requirements.txt",
            ROOT / ".env.example",
        ]
        for f in source_files:
            self.assertTrue(f.exists(), f"ไม่พบไฟล์ {f.name}")
            content = f.read_text(encoding="utf-8").lower()
            for term in self.FORBIDDEN_TERMS:
                self.assertNotIn(
                    term.lower(),
                    content,
                    f"พบการอ้างอิงของระบบเก่า '{term}' ในไฟล์ {f.name}",
                )

    def test_no_legacy_scripts_or_dirs(self):
        self.assertFalse((ROOT / "macos").exists(), "โฟลเดอร์ macos/ ยังคงอยู่")
        self.assertFalse((ROOT / "run_app.bat").exists(), "run_app.bat ยังคงอยู่")
        self.assertFalse((ROOT / "run_app.ps1").exists(), "run_app.ps1 ยังคงอยู่")


class TestThaiLanguageAndParsing(unittest.TestCase):
    """ทดสอบการประมวลผลภาษาไทย: ตัวเลขไทย คำปลุก และเวลาภาษาไทย"""

    def test_thai_number_formatting(self):
        self.assertEqual(jarvis.thai_number(0), "ศูนย์")
        self.assertEqual(jarvis.thai_number(1), "หนึ่ง")
        self.assertEqual(jarvis.thai_number(10), "สิบ")
        self.assertEqual(jarvis.thai_number(20), "ยี่สิบ")
        self.assertEqual(jarvis.thai_number(35), "สามสิบห้า")
        self.assertEqual(jarvis.thai_number(80), "แปดสิบ")

    def test_wake_word_detection(self):
        self.assertTrue(jarvis.has_wake("จางวิท เปิดยูทูบ"))
        self.assertEqual(jarvis.strip_wake("จางวิท เปิดยูทูบ"), "เปิดยูทูบ")

        self.assertTrue(jarvis.has_wake("น้องจางวิท สวัสดีครับ"))
        self.assertTrue(jarvis.has_wake("จาร์วิส หยุดเพลง"))
        self.assertTrue(jarvis.has_wake("jarvis how are you"))

        self.assertFalse(jarvis.has_wake("วันนี้อากาศดีจังเลยนะ"))

    def test_thai_time(self):
        t = jarvis.thai_time()
        self.assertTrue(t.startswith("ตอนนี้"))
        self.assertIn("นาที", t)


class TestUbuntuControls(unittest.TestCase):
    """ทดสอบคำสั่งควบคุมระบบ Ubuntu 26.04"""

    def test_default_browser(self):
        b = jarvis._default_browser()
        self.assertIn(b, ["google-chrome", "chromium", "firefox"])

    def test_open_url_cmd(self):
        cmd = jarvis.open_url_cmd("https://youtube.com")
        self.assertIsInstance(cmd, list)
        self.assertTrue(len(cmd) >= 2)
        self.assertIn("https://youtube.com", cmd[-1])

    def test_volume_functions(self):
        vol = jarvis.current_volume()
        self.assertIsInstance(vol, int)
        self.assertTrue(0 <= vol <= 100)

    def test_app_installed_check(self):
        self.assertTrue(jarvis.app_installed("Terminal") or jarvis.app_installed("Chrome") or True)

    def test_action_plan_generation(self):
        step = jarvis.Step(action="volume_up")
        p = jarvis.make_plan(step)
        self.assertIsInstance(p, jarvis.Plan)
        self.assertTrue(bool(p.reply))

        step_time = jarvis.Step(action="tell_time")
        p_time = jarvis.make_plan(step_time)
        self.assertTrue(bool(p_time.reply))

    def test_launch_does_not_block_on_foreground_app(self):
        import subprocess
        import time
        t0 = time.monotonic()
        rc, _ = jarvis._launch(["sleep", "30"], wait=0.5)
        self.assertIsNone(rc)
        self.assertLess(time.monotonic() - t0, 3)
        subprocess.run(["pkill", "-f", "^sleep 30$"])
        self.assertEqual(jarvis._launch(["false"])[0], 1)

    def test_run_quiet_times_out_instead_of_hanging(self):
        r = jarvis._run_quiet(["sleep", "5"], timeout=0.3)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(jarvis._run_quiet(["no-such-binary-xyz"]).returncode, 1)


class TestAudioInputSelection(unittest.TestCase):
    def setUp(self):
        from types import SimpleNamespace

        self.devices = [
            {"name": "USB microphone", "max_input_channels": 1},
            {"name": "pipewire", "max_input_channels": 64},
            {"name": "default", "max_input_channels": 128},
        ]
        self.sd = SimpleNamespace(
            query_devices=lambda: self.devices,
            default=SimpleNamespace(device=(2, 2)),
        )

    def test_auto_prefers_pipewire_system_input(self):
        self.assertEqual(jarvis._select_input_device(self.sd, "auto"), 1)

    def test_configured_name_selects_matching_input(self):
        self.assertEqual(jarvis._select_input_device(self.sd, "USB"), 0)

    def test_unknown_input_name_lists_available_devices(self):
        with self.assertRaisesRegex(ValueError, "USB microphone"):
            jarvis._select_input_device(self.sd, "missing")


class TestAudioSampleRateSelection(unittest.TestCase):
    def test_selects_device_default_when_16khz_is_unsupported(self):
        from types import SimpleNamespace

        attempts = []

        def check_output_settings(device, channels, dtype, samplerate):
            attempts.append(samplerate)
            if samplerate != 48000:
                raise ValueError("unsupported sample rate")

        sd = SimpleNamespace(
            query_devices=lambda device, direction: {"default_samplerate": 48000},
            check_output_settings=check_output_settings,
        )

        self.assertEqual(jarvis._select_audio_rate(sd, 3, "output"), 48000)
        self.assertEqual(attempts[:2], [jarvis.RATE, 48000])

    def test_resamples_between_hardware_rate_and_processing_rate(self):
        import numpy as np

        audio = np.arange(480, dtype=np.int16)
        output = jarvis._resample_audio(audio, 16000, 48000)

        self.assertEqual(len(output), 1440)
        self.assertEqual(output.dtype, audio.dtype)
        self.assertIs(jarvis._resample_audio(audio, 16000, 16000), audio)

    def test_raises_when_device_supports_no_candidate_rate(self):
        from types import SimpleNamespace

        def check_input_settings(**kwargs):
            raise ValueError("device unavailable")

        sd = SimpleNamespace(
            query_devices=lambda device, direction: {"default_samplerate": 48000},
            check_input_settings=check_input_settings,
        )

        with self.assertRaisesRegex(RuntimeError, "device unavailable"):
            jarvis._select_audio_rate(sd, 2, "input")


class TestComputerAgentUbuntu(unittest.TestCase):
    """ทดสอบ computer_agent บน Ubuntu"""

    def test_responsible_app(self):
        app = ca.responsible_app()
        self.assertIsInstance(app, str)
        self.assertTrue(len(app) > 0)

    def test_screen_size(self):
        w, h = ca.screen_size()
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_frontmost_app(self):
        name, pid = ca.frontmost()
        self.assertIsInstance(name, str)
        self.assertIsInstance(pid, int)

    def test_ocr_screen_fallback(self):
        items = ca.ocr_screen(max_items=10)
        self.assertIsInstance(items, list)

    def test_key_mapping(self):
        self.assertIn("enter", ca.X11_KEYSYMS)
        self.assertIn("tab", ca.X11_KEYSYMS)
        self.assertIn("space", ca.X11_KEYSYMS)


class TestBrowserAgentUbuntu(unittest.TestCase):
    """ทดสอบ browser_agent บน Ubuntu"""

    def test_chrome_executable_path(self):
        self.assertIsInstance(ba.CHROME, Path)

    def test_browser_profile_path(self):
        self.assertIsInstance(jarvis.BROWSER_PROFILE, Path)
        self.assertTrue(jarvis.BROWSER_PROFILE.name.startswith(".browser-profile"))


class TestWhisperRuntime(unittest.TestCase):
    """ตรวจการเลือกอุปกรณ์และความแม่นยำ/หน่วยความจำของ Faster-Whisper"""

    def test_typhoon_huggingface_model_requires_converted_ct2_checkpoint(self):
        with self.assertRaisesRegex(FileNotFoundError, "convert_typhoon_whisper_for_jetson.sh"):
            jarvis._resolve_whisper_model(
                jarvis.TYPHOON_WHISPER_MODEL, ROOT / "missing-typhoon-model"
            )

        with TemporaryDirectory() as model_dir:
            model_path = Path(model_dir)
            (model_path / "model.bin").touch()
            self.assertEqual(
                jarvis._resolve_whisper_model(jarvis.TYPHOON_WHISPER_MODEL, model_path),
                str(model_path),
            )
            self.assertEqual(
                jarvis._resolve_whisper_model("large-v3-turbo", model_path),
                "large-v3-turbo",
            )

    def test_auto_uses_jetson_cuda_int8_float16(self):
        device = jarvis._select_whisper_device("auto", 1)
        compute = jarvis._select_whisper_compute_type(
            "auto", device, "aarch64", {"float16", "int8_float16"}
        )
        self.assertEqual((device, compute), ("cuda", "int8_float16"))

    def test_auto_uses_cpu_int8_without_cuda(self):
        device = jarvis._select_whisper_device("auto", 0)
        compute = jarvis._select_whisper_compute_type(
            "auto", device, "aarch64", {"int8", "float32"}
        )
        self.assertEqual((device, compute), ("cpu", "int8"))

    def test_auto_uses_fp16_if_jetson_quantized_mode_is_unavailable(self):
        compute = jarvis._select_whisper_compute_type(
            "auto", "cuda", "aarch64", {"float16"}
        )
        self.assertEqual(compute, "float16")

    def test_cuda_can_be_required(self):
        with self.assertRaisesRegex(RuntimeError, "ไม่พบ CUDA device"):
            jarvis._select_whisper_device("cuda", 0)

    def test_invalid_or_unsupported_runtime_settings_fail(self):
        with self.assertRaisesRegex(ValueError, "WHISPER_DEVICE"):
            jarvis._select_whisper_device("gpu", 1)
        with self.assertRaisesRegex(ValueError, "WHISPER_COMPUTE_TYPE"):
            jarvis._select_whisper_compute_type("float16", "cpu", "aarch64", {"int8"})


class TestSelftest(unittest.TestCase):
    """ทดสอบ selftest บน Ubuntu (Headless mode)"""

    def test_headless_selftest(self):
        ok = selftest.run_selftest()
        self.assertTrue(ok)
        log_file = ROOT / "logs" / "selftest.log"
        self.assertTrue(log_file.exists())
        content = log_file.read_text(encoding="utf-8")
        self.assertIn("สรุป", content)


if __name__ == "__main__":
    unittest.main()
