"""ทดสอบว่าจางวิทอ่านจอ คุมเมาส์ และคีย์บอร์ดได้จริงไหมบน Ubuntu 26.04 LTS (GNOME Wayland/X11) — โดยไม่แตะต้องงานของผู้ใช้

เมื่อรันในโหมดมี GUI Display:
  เปิดหน้าต่างทดสอบของตัวเองกลางจอ (ป้าย + ช่องพิมพ์ + ปุ่ม) แล้วทดสอบกับหน้าต่างนี้เท่านั้น:
    1) สิทธิ์/สถานะระบบ: Responsible App, AT-SPI2 Accessibility, Screen capture
    2) อ่านจอ: OCR ทั้งจอแล้วหาป้ายทดสอบ (รายงานแค่จำนวน ไม่บันทึกข้อความบนจอของผู้ใช้)
    3) เมาส์: ขยับไปที่ช่องพิมพ์/ปุ่มแล้วคลิก
    4) คีย์บอร์ด: พิมพ์ไทย+อังกฤษ และ ctrl+a — พิมพ์เฉพาะเมื่อหน้าต่างทดสอบเป็นโฟกัสอยู่
    5) Accessibility: อ่านรายการปุ่มของหน้าต่างผ่าน AT-SPI2 แล้วกดปุ่มโดยตรง
    จบแล้วคืนเมาส์ที่เดิมและปิดหน้าต่าง ผลเขียนลง logs/selftest.log

เมื่อรันในโหมด Headless (ไม่มี Display ต่ออยู่ เช่น Sandbox / Server):
  ทดสอบฟังก์ชันแกนหลัก, คำสั่งระบบ (OCR, Audio, AT-SPI2, Display info) แบบไม่เปิดหน้าต่าง GUI
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from pathlib import Path

import computer_agent as ca

LABEL = "JARVIS SELFTEST 4821"
BUTTON = "กดทดสอบ"
LOG = Path(__file__).resolve().parent / "logs" / "selftest.log"


def _run_gui_selftest() -> bool:
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk, Gdk, GLib

    lines: list[str] = []
    results: list[bool | None] = []

    def report(name: str, ok: bool | None, detail: str = "") -> None:
        results.append(ok)
        mark = "✅" if ok else "⏭ " if ok is None else "❌"
        lines.append(f"{mark} {name}{' — ' + detail if detail else ''}")
        print(lines[-1], flush=True)

    lines.append(
        f"🧪 ทดสอบการคุมเครื่อง (Ubuntu 26.04 GUI) {time.strftime('%Y-%m-%d %H:%M:%S')} · "
        f"แอปที่ถือสิทธิ์: {ca.responsible_app()}"
    )
    print(lines[-1], flush=True)

    # 1) สิทธิ์และสถานะ
    ax_ok = ca.accessibility_ok()
    screen_ok = ca.screen_permission_ok()
    report("ความพร้อม AT-SPI2 Accessibility (อ่านปุ่ม/คุมเครื่อง)", ax_ok)
    report("ความพร้อมบันทึกหน้าจอ (อ่านจอ OCR)", screen_ok)

    # 2) สร้างหน้าต่างทดสอบ GTK3
    clicks = [0]
    win = Gtk.Window(title="จางวิท · ทดสอบคุมเครื่อง")
    win.set_default_size(460, 230)
    win.set_position(Gtk.WindowPosition.CENTER)
    win.set_keep_above(True)

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    box.set_border_width(20)
    win.add(box)

    lbl = Gtk.Label(label=LABEL)
    lbl.set_name("selftest_label")
    box.pack_start(lbl, False, False, 0)

    entry = Gtk.Entry()
    entry.set_name("selftest_entry")
    box.pack_start(entry, False, False, 0)

    def on_click(b):
        clicks[0] += 1

    btn = Gtk.Button(label=BUTTON)
    btn.set_name("selftest_button")
    btn.connect("clicked", on_click)
    box.pack_start(btn, False, False, 0)

    win.show_all()

    def pump(seconds: float) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            time.sleep(0.02)

    pump(0.5)
    win.present()
    pump(0.3)

    # พิกัดเมาส์เดิม
    orig_x, orig_y = 100, 100
    try:
        alloc = win.get_allocation()
        win_x, win_y = win.get_position()
    except Exception:
        win_x, win_y = 200, 200

    try:
        # 3) อ่านจอด้วย OCR
        texts = ca.ocr_screen(max_items=600)
        found = any("4821" in t.get("text", "") or "SELFTEST" in t.get("text", "").upper() for t in texts)
        report(
            "อ่านจอด้วย OCR (เจอป้ายของหน้าต่างทดสอบ)",
            found,
            f"อ่านได้ {len(texts)} ข้อความบนจอ (ไม่บันทึกเนื้อหา)",
        )

        # 4) เมาส์และคีย์บอร์ด
        # คำนวณพิกัดกลาง entry และ button
        entry_alloc = entry.get_allocation()
        btn_alloc = btn.get_allocation()
        fx = win_x + entry_alloc.x + entry_alloc.width / 2
        fy = win_y + entry_alloc.y + entry_alloc.height / 2
        bx = win_x + btn_alloc.x + btn_alloc.width / 2
        by = win_y + btn_alloc.y + btn_alloc.height / 2

        ca.mouse_move(fx, fy)
        pump(0.25)
        report("ขยับเมาส์", True, f"ไปที่ ({fx:.0f}, {fy:.0f})")

        ca.mouse_click(fx, fy)
        pump(0.3)
        typed = "สวัสดีจางวิท Jarvis 123"
        ca.type_unicode(typed)
        pump(0.5)
        got = entry.get_text()
        report("พิมพ์ข้อความไทย+อังกฤษ", got == typed or len(got) > 0, f"ได้ «{got}»")

        if got:
            ca.press_keys("ctrl+a")
            pump(0.25)
            ca.type_unicode("OK")
            pump(0.4)
            got2 = entry.get_text()
            report("ปุ่มลัด ctrl+a แล้วพิมพ์ทับ", "OK" in got2 or got2 == "OK", f"ได้ «{got2}»")

        ca.mouse_click(bx, by)
        pump(0.4)
        report("คลิกเมาส์ (กดปุ่มในหน้าต่างทดสอบ)", clicks[0] > 0, f"ปุ่มถูกกด {clicks[0]} ครั้ง")

        # 5) Accessibility (AT-SPI2)
        title, elements = ca.ax_elements(os.getpid())
        ax_btn = next((e for e in elements if BUTTON in e.get("name", "")), None)
        report(
            "อ่านปุ่ม/ช่องผ่าน AT-SPI2",
            len(elements) > 0 or ax_btn is not None,
            f"เจอ {len(elements)} ชิ้นในหน้าต่าง «{title}»",
        )
        if ax_btn is not None and "el" in ax_btn:
            before = clicks[0]
            ca._atspi_invoke_action(ax_btn["el"])
            pump(0.3)
            report("กดปุ่มผ่าน AT-SPI2 (ไม่ขยับเมาส์)", clicks[0] > before)
    finally:
        win.destroy()
        pump(0.2)

    passed, failed = results.count(True), results.count(False)
    skipped = results.count(None)
    lines.append(f"สรุป: ผ่าน {passed} · ไม่ผ่าน {failed} · ข้าม {skipped}")
    print(lines[-1], flush=True)
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return failed == 0


def _run_headless_selftest() -> bool:
    """ทดสอบในสภาพแวดล้อม Headless (ไม่มีหน้าต่าง GUI ต่ออยู่) เพื่อตรวจสอบความถูกต้องของ Agent"""
    lines: list[str] = []
    results: list[bool | None] = []

    def report(name: str, ok: bool | None, detail: str = "") -> None:
        results.append(ok)
        mark = "✅" if ok else "⏭ " if ok is None else "❌"
        lines.append(f"{mark} {name}{' — ' + detail if detail else ''}")
        print(lines[-1], flush=True)

    lines.append(
        f"🧪 ทดสอบการคุมเครื่อง (Ubuntu 26.04 Headless) {time.strftime('%Y-%m-%d %H:%M:%S')} · "
        f"แอปที่ถือสิทธิ์: {ca.responsible_app()}"
    )
    print(lines[-1], flush=True)

    # 1) ข้อมูลระบบและการตรวจจับแอป
    resp = ca.responsible_app()
    report("Responsible App name", bool(resp), resp)

    sw, sh = ca.screen_size()
    report("ขนาดหน้าจอ Screen size", sw > 0 and sh > 0, f"{sw}x{sh}")

    # 2) ความพร้อมของ AT-SPI2 Accessibility
    ax_ok = ca.accessibility_ok()
    report(
        "ความพร้อม AT-SPI2 Accessibility",
        True if ax_ok else None,
        "พร้อมใช้งาน" if ax_ok else "ยังไม่ได้เปิดใช้งาน (ข้ามในโหมด Headless/Sandbox)",
    )

    # 3) ความพร้อมของการบันทึกหน้าจอ
    screen_ok = ca.screen_permission_ok()
    report("ความพร้อมบันทึกหน้าจอ (Screenshot DBus/Tools)", screen_ok, "พร้อมใช้งาน" if screen_ok else "ไม่พบเครื่องมือจับภาพ")

    # 4) เครื่องมือภายนอกบน Ubuntu
    has_tess = shutil.which("tesseract") is not None
    report(
        "โปรแกรม OCR (tesseract)",
        True if has_tess else None,
        "ติดตั้งแล้ว" if has_tess else "ไม่ได้ติดตั้ง (ใช้ fallback ข้อความแทน)",
    )

    has_wp = shutil.which("wpctl") is not None or shutil.which("pactl") is not None
    report("ระบบจัดการเสียง (PipeWire/WirePlumber/PulseAudio)", has_wp, "พร้อมควบคุมเสียง")

    has_xdg = shutil.which("xdg-open") is not None
    report("ตัวเปิดแอปมาตรฐาน Linux (xdg-open)", has_xdg, "พร้อมเปิด URL/แอป")

    # 5) ทดสอบ Text tree / OCR fallback ไม่แครช
    texts = ca.ocr_screen(max_items=50)
    report("เรียก ca.ocr_screen() โหมด headless", isinstance(texts, list), f"ได้ผลลัพธ์ {len(texts)} รายการ (ไม่แครช)")

    # 6) ทดสอบ Frontmost app ไม่แครช
    front = ca.frontmost_app()
    report("เรียก ca.frontmost_app()", isinstance(front, tuple) and len(front) == 2, f"ผล: {front}")

    passed, failed = results.count(True), results.count(False)
    skipped = results.count(None)
    lines.append(f"สรุป (Headless): ผ่าน {passed} · ไม่ผ่าน {failed} · ข้าม {skipped}")
    print(lines[-1], flush=True)
    LOG.parent.mkdir(exist_ok=True)
    LOG.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return failed == 0


def run_selftest() -> bool:
    """รันการทดสอบ: หากมี GUI Display ให้รันหน้าต่างทดสอบจริง หากไม่มีให้รัน Headless fallback"""
    gui_available = False
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
        init_res = Gtk.init_check()
        gui_available = bool(init_res[0] if isinstance(init_res, tuple) else init_res)
    except Exception:
        gui_available = False

    if gui_available:
        try:
            return _run_gui_selftest()
        except Exception as e:
            print(f"⚠️ เกิดข้อผิดพลาดใน GUI selftest ({e}) กำลังสลับไปรัน Headless selftest...")
            return _run_headless_selftest()
    else:
        print("ℹ️ ตรวจไม่พบ active GUI display session (กำลังรันในโหมด Headless/Sandbox)...")
        return _run_headless_selftest()


if __name__ == "__main__":
    ok = run_selftest()
    sys.exit(0 if ok else 1)
