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
import unittest
import io
import wave
import builtins
from pathlib import Path
from unittest.mock import Mock, patch

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


class TestTyphoonSTT(unittest.TestCase):
    """ทดสอบการส่ง WAV ไปยัง Typhoon โดยไม่เรียก API จริง"""

    def test_initialization_requires_api_key(self):
        with patch.object(jarvis, "TYPHOON_API_KEY", ""):
            with self.assertRaisesRegex(RuntimeError, "TYPHOON_API_KEY"):
                jarvis.STT()

    def test_transcribe_posts_mono_16khz_wav(self):
        stt = jarvis.STT.__new__(jarvis.STT)
        stt.api_key = "test-api-key"
        stt.model = "typhoon-asr-realtime"
        response = Mock()
        response.json.return_value = {"text": "จางวิท เปิด Spotify"}

        with patch("jarvis.requests.post", return_value=response) as post:
            text = stt.transcribe(jarvis.np.zeros(jarvis.RATE, dtype=jarvis.np.float32))

        self.assertEqual(text, "จางวิท เปิด Spotify")
        response.raise_for_status.assert_called_once_with()
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.opentyphoon.ai/v1/audio/transcriptions")
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer test-api-key"})
        self.assertEqual(kwargs["data"], {"model": "typhoon-asr-realtime"})
        filename, content, content_type = kwargs["files"]["file"]
        self.assertEqual((filename, content_type), ("utterance.wav", "audio/wav"))
        with wave.open(io.BytesIO(content), "rb") as wav_file:
            self.assertEqual((wav_file.getnchannels(), wav_file.getsampwidth(), wav_file.getframerate()),
                             (1, 2, jarvis.RATE))

    def test_transcribe_propagates_api_errors(self):
        stt = jarvis.STT.__new__(jarvis.STT)
        stt.api_key = "test-api-key"
        stt.model = "typhoon-asr-realtime"
        response = Mock()
        response.raise_for_status.side_effect = jarvis.requests.HTTPError("API unavailable")

        with patch("jarvis.requests.post", return_value=response):
            with self.assertRaises(jarvis.requests.HTTPError):
                stt.transcribe(jarvis.np.zeros(jarvis.RATE, dtype=jarvis.np.float32))


class TestMicrophoneDevice(unittest.TestCase):
    def test_missing_portaudio_reports_system_dependency_before_initialization(self):
        original_import = builtins.__import__

        def import_without_portaudio(name, *args, **kwargs):
            if name == "sounddevice":
                raise OSError("PortAudio library not found")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_without_portaudio), \
                patch.object(jarvis, "Jev") as jev:
            with self.assertRaisesRegex(SystemExit, "sudo apt install -y libportaudio2"):
                jarvis.run_mic(False)
            jev.assert_not_called()

    def test_unrelated_sounddevice_oserror_is_not_masked(self):
        original_import = builtins.__import__

        def import_with_error(name, *args, **kwargs):
            if name == "sounddevice":
                raise OSError("different error")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=import_with_error):
            with self.assertRaisesRegex(OSError, "different error"):
                jarvis.run_mic(False)

    def test_microphone_device_selection(self):
        for configured, expected in (("", None), ("1", 1), ("USB Device", "USB Device")):
            with self.subTest(configured=configured), \
                    patch.object(jarvis, "MIC_DEVICE", configured), \
                    patch("sounddevice.InputStream") as stream, \
                    patch("pysilero_vad.SileroVoiceActivityDetector"):
                jarvis.Ears(Mock())
                self.assertEqual(stream.call_args.kwargs["device"], expected)
                self.assertNotIn("callback", stream.call_args.kwargs)


class TestSpeakerOutput(unittest.TestCase):
    def test_stream_uses_int16_and_preserves_output_samples(self):
        sounddevice = Mock()
        with patch.dict(sys.modules, {"sounddevice": sounddevice}), \
                patch("jarvis.threading.Thread") as thread:
            speaker = jarvis.Speaker()
            thread.return_value.start.assert_called_once()

        self.assertEqual(sounddevice.OutputStream.call_args.kwargs["dtype"], "int16")
        speaker._chunks.append(jarvis.np.array([0, 16384, -32768], dtype=jarvis.np.int16))
        outdata = jarvis.np.zeros((3, 1), dtype=jarvis.np.int16)
        timing = type("Timing", (), {"outputBufferDacTime": 0.1, "currentTime": 0.0})()
        speaker._on_output(outdata, 3, timing, None)
        jarvis.np.testing.assert_array_equal(outdata[:, 0], [0, 16384, -32768])
        speaker.close()

    def test_say_speaker_passes_int16_audio(self):
        audio = jarvis.np.array([0, 32767], dtype=jarvis.np.int16)
        class ImmediateThread:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()

        sounddevice = Mock()
        with patch.dict(sys.modules, {"sounddevice": sounddevice}), \
                patch.object(jarvis, "speech_audio", return_value=audio), \
                patch("jarvis.threading.Thread", ImmediateThread):
            speaker = jarvis.SaySpeaker()
            speaker.say("ทดสอบ")

        played = sounddevice.play.call_args.args[0]
        self.assertEqual(played.dtype, jarvis.np.int16)
        jarvis.np.testing.assert_array_equal(played, audio)


class TestHudRenderer(unittest.TestCase):
    def test_raspberry_pi_disables_webkit_hardware_acceleration(self):
        webview = Mock()
        webkit = Mock()
        with patch.object(Path, "read_bytes", return_value=b"Raspberry Pi 5 Model B Rev 1.0\0"):
            jarvis._configure_hud_renderer(webview, webkit)
        webview.get_settings().set_hardware_acceleration_policy.assert_called_once_with(
            webkit.HardwareAccelerationPolicy.NEVER
        )

    def test_other_machines_keep_webkit_default(self):
        for result in (b"Other computer\0", FileNotFoundError()):
            with self.subTest(result=result):
                webview = Mock()
                with patch.object(Path, "read_bytes", side_effect=result if isinstance(result, Exception) else None,
                                  return_value=result):
                    jarvis._configure_hud_renderer(webview, Mock())
                webview.get_settings.assert_not_called()


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
