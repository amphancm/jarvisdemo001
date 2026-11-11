#!/usr/bin/env python3
"""
Jarvis ไทย (Ubuntu 26.04) — "จางวิท" ผู้ช่วยสั่งงานคอมพิวเตอร์ด้วยเสียงภาษาไทย แบบ full duplex
(ฟังตลอดเวลา ไม่ต้องกดปุ่ม เรียก "จางวิท" แล้วสั่งได้เลย พูดแทรกตอนจางวิทกำลังพูดได้)

ท่อการทำงาน
  ไมค์ ─► ตัดเสียงสะท้อน (AEC) ─► VAD ตัดประโยค ─► faster-whisper ในเครื่อง (ภาษาไทย) ─► ได้ยิน "จางวิท" ไหม
       ─► Jev ตัดสินใจ (typesafe-sdk หรือ LLM fallback, speculative fan-out)
       ─► สั่งเครื่อง Ubuntu | ท่องเว็บด้วย Playwright (browser_agent.py) | คุมจอ (computer_agent.py) | ถาม LLM
       ─► พูดตอบด้วยเสียงไทย (edge-tts เล่นผ่านลำโพงเอง จึงหยุดได้ทันทีเมื่อถูกพูดแทรก)

วิธีใช้
  python jarvis.py                          ฟังไมค์ (full duplex) เรียก "จางวิท ..." ก่อนสั่ง
  python jarvis.py --text "เปิดสปอติฟาย"      สั่งด้วยข้อความ
  python jarvis.py --dry-run                ไม่สั่งเครื่องจริง แค่ print ว่าจะทำอะไร
  python jarvis.py --eval                   วัดความแม่นกับชุดประโยคทดสอบภาษาไทย
  python jarvis.py --wav file.wav           ป้อนไฟล์เสียงแทนไมค์ (ไว้ทดสอบ VAD + STT)
"""

from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import queue
import random
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import wave

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    def load_dotenv(path=None):
        _env_file = Path(path) if path else (Path(__file__).resolve().parent / ".env")
        if _env_file.exists():
            for _line in _env_file.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                _k, _v = _line.split("=", 1)
                _k, _v = _k.strip(), _v.strip().strip("'\"")
                if _k and _k not in os.environ:
                    os.environ[_k] = _v
    load_dotenv()

try:
    import numpy as np
except ImportError:
    np = None

import requests

try:
    from typesafe_sdk import (
        Choice,
        ChoiceAnswer,
        Noul,
        NoulAnswer,
        RetryPolicy,
        Score,
        TypeSafeClient,
        TypeSafeError,
    )
except ImportError:
    @dataclass
    class Choice:
        instructions: str
        criteria: dict

    @dataclass
    class Noul:
        instructions: str
        criteria: dict

    @dataclass
    class Score:
        instructions: str
        criteria: list

    class TypeSafeError(Exception):
        pass

    ChoiceAnswer = NoulAnswer = RetryPolicy = TypeSafeClient = None

# ════════════════════════════════════════════════════════════════════════════
# 1) ปรับแต่งได้ง่าย: แอป / คำสั่ง / ระดับเสียง / ประโยคตอบ
#    คำอธิบายเขียนเป็นอังกฤษ (Jev ถนัดสุด) แล้วแนบคำไทยที่คนใช้เรียกไว้ในวงเล็บ
# ════════════════════════════════════════════════════════════════════════════

# "ชื่อแอปมาตรฐาน": ("ชื่อที่จางวิทพูด", "คำอธิบายให้ Jev")
APPS = {
    "Spotify":            ("สปอติฟาย", "สปอติฟาย"),
    "Google Chrome":      ("กูเกิลโครม", "โครม"),
    "Safari":             ("เบราว์เซอร์", "ซาฟารี, ไฟร์ฟอกซ์, เบราว์เซอร์"),
    "LINE":               ("ไลน์", "ไลน์"),
    "Slack":              ("สแล็ก", "สแล็ก"),
    "Visual Studio Code": ("วีเอสโค้ด", "VS Code, วีเอสโค้ด"),
    "Terminal":           ("เทอร์มินัล", "เทอร์มินัล"),
    "Finder":             ("ไฟล์", "ไฟน์เดอร์, แฟ้ม, ไฟล์"),
    "Notes":              ("โน้ต", "โน้ต, สมุดบันทึก"),
    "Calendar":           ("ปฏิทิน", "ปฏิทิน"),
    "Mail":               ("เมล", "เมล, อีเมล"),
    "Calculator":         ("เครื่องคิดเลข", "เครื่องคิดเลข"),
    "System Settings":    ("การตั้งค่าระบบ", "ตั้งค่า"),
    "none":               ("", "No app or website is named"),
}

# เว็บยอดนิยม: "เปิดยูทูบ" = เปิดเว็บตรงๆ เลย (เร็วกว่าและไม่เปลือง token เท่าให้เอเจนต์ท่องเว็บ)
# "ชื่อ": ("ชื่อที่จางวิทพูด", "คำอธิบายให้ Jev", "URL")
SITES = {
    "YouTube":     ("ยูทูบ", "ยูทูบ", "https://www.youtube.com"),
    "Facebook":    ("เฟซบุ๊ก", "เฟซบุ๊ก, เฟส", "https://www.facebook.com"),
    "Gmail":       ("จีเมล", "จีเมล", "https://mail.google.com"),
    "Google Maps": ("กูเกิลแมป", "กูเกิลแมป, แผนที่", "https://www.google.com/maps"),
    "Shopee":      ("ช้อปปี้", "ช้อปปี้", "https://shopee.co.th"),
    "Lazada":      ("ลาซาด้า", "ลาซาด้า", "https://www.lazada.co.th"),
    "Netflix":     ("เน็ตฟลิกซ์", "เน็ตฟลิกซ์", "https://www.netflix.com"),
}

# คำสั่งที่จางวิททำได้: ชื่อ action → คำอธิบายให้ Jev
ACTIONS = {
    "open_app":       "Open or switch to a named app or a popular website like YouTube (Thai: เปิด..., ขอ..., เข้า...). "
                      "Not for music, sound or searching",
    "quit_app":       "Quit or close a named app (Thai: ปิด..., ออกจาก...)",
    "volume_up":      "Make the computer louder or unmute it (Thai: เพิ่มเสียง, ดังขึ้น, เปิดเสียง)",
    "volume_down":    "Make the computer quieter (Thai: ลดเสียง, เบาเสียง)",
    "volume_mute":    "Mute all sound (Thai: ปิดเสียง, มิวต์)",
    "volume_set":     "Set the volume to a stated level (Thai: ตั้งเสียง..., เสียงครึ่งหนึ่ง, ดังสุด)",
    "music_play":     "Play or resume music (Thai: เล่นเพลง, เปิดเพลง, เล่นต่อ)",
    "music_pause":    "Pause or stop music (Thai: หยุดเพลง, ปิดเพลง)",
    "music_next":     "Skip to the next song (Thai: เพลงถัดไป, ข้ามเพลง)",
    "music_previous": "Go back to the previous song (Thai: เพลงก่อนหน้า, ย้อนเพลง)",
    "dark_mode":      "Toggle dark or light mode (Thai: โหมดมืด, โหมดสว่าง)",
    "lock_screen":    "Lock the screen (Thai: ล็อกจอ)",
    "sleep":          "Put the computer to sleep/suspend (Thai: พักเครื่อง, สลีป)",
    "tell_time":      "Tell the current time (Thai: กี่โมงแล้ว)",
    "screenshot":     "Take a screenshot (Thai: แคปหน้าจอ)",
    "web_task":       "Search or look up live info on the web: places, prices, reviews, weather, news, or find something "
                      "inside a website (Thai: หา..., ค้นหา..., เช็คราคา..., หาเพลง...ในยูทูบ)",
    "read_screen":    "Read or describe what is on the screen right now (Thai: อ่านจอ, บนจอมีอะไร, หน้าจอเขียนว่าอะไร)",
    "computer_task":  "Operate the screen directly in any app: click a button, type into an app, scroll, move the "
                      "mouse, use a menu or shortcut (Thai: คลิก..., กดปุ่ม..., พิมพ์ว่า..., เลื่อนลง, เลื่อนเมาส์, กดเซฟ)",
    "stop_talking":   "Tell the assistant itself to stop talking or cancel what it is doing "
                      "(Thai: หยุดพูด, เงียบก่อน, พอแล้ว, ยกเลิก, ไม่ต้องหาแล้ว). Not about music",
    "none":           "No system action: a general question, chit-chat, or noise",
}

# ประเภทของประโยค (คำถามแรกของ fan-out)
CATEGORIES = {
    "command": "The speaker tells the assistant to do something on this computer or on the web, including polite "
               "requests (Thai: เปิด..., ปิด..., เพิ่มเสียง, หยุดเพลง, ล็อกจอ, กี่โมงแล้ว, หาห้องพักให้หน่อย, "
               "ค้นหา..., ช่วย...ให้หน่อย, ...ได้ไหม)",
    "question": "The speaker asks a general-knowledge question or chats with the assistant, and it can be "
                "answered from general knowledge without searching the web or doing anything on the computer "
                "(Thai: ...คืออะไร, ทำไม..., อย่างไร, ช่วยอธิบาย, เล่าให้ฟังหน่อย, สวัสดี)",
    "noise": "Not meant for the assistant: speech addressed to another person (e.g. calling แม่, พ่อ, พี่, ลูก "
             "and asking them something), TV or video audio, filler sounds (อืม, เอ่อ), cut-off words, "
             "or speech-recognition junk such as 'ขอบคุณที่รับชม' or 'ซับไตเติ้ลโดย'",
}

# ระดับเสียงสำหรับ Score: (เปอร์เซ็นต์ที่ตั้งจริง, คำอธิบายให้ Jev)
VOLUME_LEVELS = [
    (10, "10 percent (สิบ)"), (20, "20 percent"), (30, "30 percent"), (40, "40 percent"),
    (50, "50 percent, half (ครึ่ง)"), (60, "60 percent"), (70, "70 percent"), (80, "80 percent"),
    (90, "90 percent"), (100, "100 percent, maximum (ดังสุด, เต็ม)"),
]

# ประโยคตอบสำเร็จรูป (สุ่มหนึ่งแบบ) คุยแบบเพื่อน สั้นๆ ไวๆ · {app} = ชื่อแอปภาษาไทย, {vol} = เปอร์เซ็นต์เสียง
REPLIES = {
    "open_app":       ["ได้เลย เปิด{app}ให้แล้ว", "จัดไป {app}มาแล้ว", "โอเค {app}เปิดแล้วนะ"],
    "quit_app":       ["ปิด{app}ให้แล้ว", "โอเค ปิด{app}แล้วนะ"],
    "volume_up":      ["ดังขึ้นละ {vol} เปอร์เซ็นต์", "เพิ่มให้แล้ว {vol} เปอร์เซ็นต์นะ"],
    "volume_down":    ["เบาลงละ เหลือ {vol} เปอร์เซ็นต์", "ลดให้แล้ว {vol} เปอร์เซ็นต์นะ"],
    "volume_mute":    ["ปิดเสียงนะ", "เงียบละนะ"],
    "volume_set":     ["เสียง {vol} เปอร์เซ็นต์ละ", "ตั้งไว้ {vol} เปอร์เซ็นต์แล้วนะ"],
    "music_play":     ["เปิดเพลงละ", "จัดเพลงให้เลย"],
    "music_pause":    ["หยุดเพลงแล้ว", "พักเพลงไว้ก่อนนะ"],
    "music_next":     ["เพลงต่อไปเลย", "ข้ามให้ละ"],
    "music_previous": ["ย้อนให้แล้ว", "กลับไปเพลงเมื่อกี้ละ"],
    "dark_mode":      ["สลับธีมให้แล้ว", "เปลี่ยนโหมดจอให้ละ"],
    "lock_screen":    ["ล็อกจอนะ", "ล็อกให้เลย"],
    "sleep":          ["พักเครื่องนะ", "ไปพักก่อนนะ"],
    "screenshot":     ["แคปจอเก็บไว้บนเดสก์ท็อปแล้ว", "แคปให้ละนะ"],
    "web_task":       ["ได้ เดี๋ยวหาให้", "แป๊บนึงนะ กำลังหา", "โอเค ขอค้นแป๊บ"],
    "read_screen":    ["แป๊บนะ ขอดูจอก่อน", "ขออ่านจอแป๊บ"],
    "computer_task":  ["ได้ เดี๋ยวจัดการให้", "โอเค ขอคุมเครื่องแป๊บนะ"],
    "none":           ["อันนี้เรายังทำไม่เป็นอะ"],
    # ── ประโยคของระบบ ──
    "ready":          ["จางวิทมาแล้ว เรียกได้เลย", "พร้อมละครับ"],
    "wake":           ["ครับผม", "ครับ"],
    "which_app":      ["เปิดแอปไหนนะ หาชื่อนั้นไม่เจออะ", "แอปอะไรนะ ขอชื่ออีกทีได้ไหม"],
    "retry":          ["เมื่อกี้ว่าไงนะ", "ไม่ค่อยชัดอะ ขออีกทีได้ไหม", "ขอโทษ ไม่ทันได้ยิน พูดอีกรอบนะ"],
    "skip":           ["งั้นข้ามก่อนนะ", "ยังจับไม่ได้ ข้ามไปก่อนละกัน"],
    "fail":           ["อ้าว ทำไม่สำเร็จอะ", "ขอโทษ มีอะไรผิดพลาดนิดนึง"],
    "no_llm":         ["ยังไม่ได้ตั้งค่าสมองส่วนคุยเลยอะ ตอบไม่ได้"],
    "llm_error":      ["ขอโทษ ตอนนี้คิดไม่ออก ลองใหม่อีกทีนะ"],
    "llm_quota":      ["โควตาของแอลแอลเอ็มหมดแล้วอะ ไว้ลองใหม่นะ"],
    "jev_error":      ["ขอโทษ ระบบตัดสินใจขัดข้อง ลองใหม่อีกทีนะ"],
    "web_cancel":     ["โอเค หยุดละ", "ได้ ไม่ทำต่อแล้ว"],
    "web_fail":       ["หาไม่สำเร็จอะ ลองใหม่อีกทีนะ"],
    "web_no_llm":     ["ต้องตั้งค่าสมองส่วนคุยก่อน ถึงจะท่องเว็บให้ได้"],
}

# คุยเล่นแบบที่ตอบได้ทันที: Jev จัดประเภทไปพร้อมกับการตัดสินใจรอบแรก (ไม่เพิ่มเวลา) แล้วตอบจากชุดนี้
CHAT_INTENTS = {
    "greeting":    "Says hi or checks the assistant is there (สวัสดี, หวัดดี, ว่าไง, อยู่ไหม, ตื่นยัง)",
    "thanks":      "Thanks the assistant (ขอบคุณ, ขอบใจ, แต๊งกิ้ว, ขอบคุณมาก)",
    "praise":      "Praises the assistant (เก่งมาก, เยี่ยม, สุดยอด, ดีมาก, เก่งจัง)",
    "complaint":   "Complains the assistant is slow, wrong, useless or dumb (ช้าจัง, ทำไมไม่ทำ, ไม่ได้เรื่อง, โง่)",
    "how_are_you": "Asks how the assistant is doing (เป็นไงบ้าง, สบายดีไหม, วันนี้เป็นไง)",
    "who_are_you": "Asks who or what the assistant is, or its name (เป็นใคร, ชื่ออะไร, เป็นคนหรือเปล่า)",
    "abilities":   "Asks what the assistant can do or how to use it (ทำอะไรได้บ้าง, ช่วยอะไรได้บ้าง, ใช้ยังไง)",
    "tired":       "Says they are tired or sleepy (เหนื่อย, ง่วง, เพลีย, อยากนอน)",
    "hungry":      "Says they are hungry (หิว, หิวข้าว)",
    "bored":       "Says they are bored (เบื่อ, เซ็ง, ไม่มีอะไรทำ)",
    "sad":         "Says they feel sad, stressed or down (เศร้า, เครียด, ท้อ, ไม่สบายใจ)",
    "good_news":   "Shares that they are happy or something good happened (ดีใจ, สำเร็จแล้ว, ได้งานแล้ว)",
    "laugh":       "Laughs or finds something funny (555, ฮ่าๆ, ขำ)",
    "sorry":       "Apologizes to the assistant (ขอโทษ, โทษที)",
    "wait":        "Asks the assistant to wait or hold on (เดี๋ยวนะ, รอแป๊บ, แป๊บนึง)",
    "ok":          "Just acknowledges with no new request (โอเค, ได้, อืม, เข้าใจแล้ว, ไม่เป็นไร)",
    "retry":       "Tells the assistant to try the previous task again or go ahead with it now "
                   "(ลองดูสิ, ลองใหม่, ลองอีกที, ทำเลย, เอาเลย, ลองเล่นดูสิ)",
    "goodbye":     "Says goodbye or good night (ไปก่อนนะ, บาย, ฝันดี, ราตรีสวัสดิ์)",
    "none":        "Anything else: a real question that needs facts or an explanation, a request, an answer to "
                   "something the assistant asked, or talk not directed at the assistant",
}
CHAT_REPLIES = {
    "greeting":    ["ว่าไง อยู่นี่ละ", "หวัดดี มีอะไรให้ช่วยไหม", "ว่าไงนาย"],
    "thanks":      ["ยินดีเลย", "ไม่เป็นไรเลย", "ได้เสมอ"],
    "praise":      ["ขอบคุณนะ ดีใจเลย", "เขินเลยอะ ขอบใจนะ"],
    "complaint":   ["ขอโทษนะ เดี๋ยวเราปรับให้ดีขึ้น บอกอีกทีได้ไหมว่าอยากให้ทำอะไร",
                    "ขอโทษจริงๆ ลองบอกใหม่อีกทีนะ เราจะตั้งใจฟัง"],
    "how_are_you": ["สบายดี พร้อมช่วยอยู่ นายล่ะเป็นไงบ้าง", "ดีเลย วันนี้นายเป็นไงบ้าง"],
    "who_are_you": ["เราจางวิท ผู้ช่วยบนเครื่องของนายไง", "จางวิทไง เพื่อนที่คอยช่วยใช้คอมให้"],
    "abilities":   ["เปิดปิดแอป ปรับเสียง คุมเพลง หาของในเว็บ อ่านจอ แล้วก็คลิกหรือพิมพ์ให้ได้ เรียกจางวิทแล้วสั่งมาเลย"],
    "tired":       ["พักบ้างนะ ดื่มน้ำด้วย", "เหนื่อยก็พักก่อน เดี๋ยวค่อยลุยต่อ"],
    "hungry":      ["หาอะไรกินก่อนเลย", "ไปกินข้าวก่อนนะ เดี๋ยวค่อยลุยต่อ"],
    "bored":       ["เปิดเพลงฟังไหม", "พักสายตาแป๊บนึงก็ได้นะ"],
    "sad":         ["เราอยู่ตรงนี้นะ อยากเล่าก็เล่าได้", "ไม่เป็นไรนะ ค่อยๆ ไป"],
    "good_news":   ["ดีใจด้วยเลย", "เยี่ยมไปเลย ยินดีด้วยนะ"],
    "laugh":       ["ขำด้วยเลย", "ฮ่าๆ"],
    "sorry":       ["ไม่เป็นไรเลย", "สบายมาก ไม่ต้องขอโทษ"],
    "wait":        ["ได้ รออยู่นะ", "โอเค ไม่รีบ"],
    "ok":          ["โอเค", "ได้เลย"],
    "retry":       ["ลองอะไรดี บอกคำสั่งมาได้เลย"],
    "goodbye":     ["ไว้เจอกันนะ", "บาย พักผ่อนเยอะๆ"],
}
CHAT_CONF = 0.7                       # Jev มั่นใจเท่านี้ถึงตอบจากชุดคุยเล่น ไม่งั้นให้ LLM คิดเอง
MOOD_INTENTS = {"tired", "hungry", "bored", "sad"}
ASKS_RE = re.compile(r"อะไร|ยังไง|อย่างไร|ทำไม|ไหม|มั้ย|หรือเปล่า|กี่|ที่ไหน|เท่าไ|ช่วย|แนะนำ|ดี\s*$")

# คำใบ้ให้ Whisper: ประโยคไทยปนชื่อแอปอังกฤษ ช่วยให้สะกดชื่อแอปและคำปลุกถูก
WHISPER_PROMPT = "จางวิท เปิด Spotify ปิด LINE เปิด Slack เปิด Google Chrome เปิด VS Code เพิ่มเสียง ลดเสียง หยุดเพลง หาห้องพัก กี่โมงแล้ว"

# รูปที่ Whisper มักถอดคำว่า "จางวิท" ออกมา: จางวิท จาง วิท จางวิทย์ จางวิช จางวิด จางวิส จาร์วิส จาวิส อาจารย์วิท
JANG_WIT_RE = r"(?:(?:น้อง|อาจารย์|จารย์)?[\s,]*(?:จ|ช|ท|ก)[่้๊๋]?[ัา]ร?์?[งนรย]?[\s,]*ว[ิี][่้๊๋]?(?:ท|ต|ด|ช|ธ|ซ|ส|ญ|ทย์|ทธิ์|ชญ์|ตร์|ร์)|jarvis|jangwit)"

# ข้อความผีที่ Whisper ชอบแต่งขึ้นเองตอนเงียบ/มีเสียงรบกวน → ทิ้งเลย ไม่ต้องถาม Jev
HALLUCINATIONS = ("ขอบคุณที่รับชม", "ขอบคุณสำหรับการรับชม", "ขอบคุณสำหรับชม", "ขอบคุณติดตาม", "ขอบคุณที่ติดตาม",
                  "ขอบคุณสำหรับความสุข", "ซับไตเติ้ล", "subtitle", "โปรดติดตามตอนต่อไป",
                  "กดไลค์", "กดไลก์", "กดติดตาม", "subscribe")

# ════════════════════════════════════════════════════════════════════════════
# 2) ค่าตั้งจาก .env
# ════════════════════════════════════════════════════════════════════════════

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")


def env_str(name: str, default: str = "") -> str:
    return (os.getenv(name) or "").strip() or default


def env_float(name: str, default: float) -> float:
    try:
        return float(env_str(name, str(default)))
    except ValueError:
        print(f"⚠️  {name} ไม่ใช่ตัวเลข ใช้ค่าเริ่มต้น {default}")
        return default


TYPESAFE_API_KEY = env_str("TYPESAFE_API_KEY")
OPENROUTER_API_KEY = env_str("OPENROUTER_API_KEY")
TOGETHER_API_KEY = env_str("TOGETHER_API_KEY") or env_str("TOGETHERAI_API_KEY")
GOOGLE_API_KEY = env_str("GOOGLE_API_KEY") or env_str("GEMINI_API_KEY")

# ผู้ให้บริการ LLM (ตอบคำถาม + ขับเบราว์เซอร์) ทุกตัวใช้ endpoint แบบ OpenAI chat completions จึงใช้โค้ดชุดเดียว
# LLM_MODE: local = รันในเครื่อง (Ollama พอร์ต 11434) · cloud = OpenRouter / TogetherAI / Gemini
_default_llm_mode = "cloud" if (OPENROUTER_API_KEY or TOGETHER_API_KEY or GOOGLE_API_KEY) else "local"
LLM_MODE = env_str("LLM_MODE", _default_llm_mode).lower()
LOCAL_LLM_MODEL = env_str("LOCAL_LLM_MODEL", "scb10x/llama3.1-typhoon2-8b-instruct")
LOCAL_LLM_PORT = int(env_float("LOCAL_LLM_PORT", 11434))
LOCAL_LLM_URL = env_str("LOCAL_LLM_URL", "")
if LLM_MODE == "local":
    LLM_PROVIDER, LLM_URL, LLM_KEY = "ในเครื่อง", (LOCAL_LLM_URL or f"http://127.0.0.1:{LOCAL_LLM_PORT}/v1/chat/completions"), "local"
    _DEFAULT_MODEL, _FALLBACK_MODEL = LOCAL_LLM_MODEL, ""
elif OPENROUTER_API_KEY:
    LLM_PROVIDER, LLM_URL, LLM_KEY = "OpenRouter", "https://openrouter.ai/api/v1/chat/completions", OPENROUTER_API_KEY
    _DEFAULT_MODEL, _FALLBACK_MODEL = "anthropic/claude-haiku-4.5", ""
elif TOGETHER_API_KEY:
    LLM_PROVIDER, LLM_URL, LLM_KEY = "TogetherAI", "https://api.together.xyz/v1/chat/completions", TOGETHER_API_KEY
    _DEFAULT_MODEL, _FALLBACK_MODEL = "Qwen/Qwen3.5-9B", "Qwen/Qwen2.5-7B-Instruct-Turbo"
elif GOOGLE_API_KEY:
    LLM_PROVIDER, LLM_URL, LLM_KEY = "Google", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", GOOGLE_API_KEY
    _DEFAULT_MODEL, _FALLBACK_MODEL = "gemini-3.5-flash-lite", "gemini-flash-lite-latest"
else:
    LLM_PROVIDER, LLM_URL, LLM_KEY, _DEFAULT_MODEL, _FALLBACK_MODEL = "", "", "", "anthropic/claude-haiku-4.5", ""


def _model_env(name: str, default: str) -> str:
    if LLM_PROVIDER == "ในเครื่อง":
        return default
    model = env_str(name, default)
    return default if LLM_PROVIDER == "Google" and "/" in model else model


LLM_MODEL = _model_env("LLM_MODEL", _DEFAULT_MODEL)
AGENT_MODEL = _model_env("AGENT_MODEL", LLM_MODEL)
JEV_MODEL = env_str("JEV_MODEL", "jev-latest")
CONF_MIN = env_float("CONF_MIN", 0.65)
TTS_VOICE = env_str("TTS_VOICE", "th-TH-NiwatNeural")
TTS_RATE = int(env_float("TTS_RATE", 205))
TTS_PITCH = env_str("TTS_PITCH", "")
BARGE_IN = env_str("BARGE_IN", "auto").lower()          # auto | on | off
SILENCE_MS = env_float("SILENCE_MS", 550)
VAD_THRESHOLD = env_float("VAD_THRESHOLD", 0.5)
LINUX_DESKTOP_APPS: dict[str, list[str]] = {}


def _clean_desktop_exec(exec_line: str) -> list[str]:
    """ตัด field codes (%U, %u, %F, %f ฯลฯ) ออกจากบรรทัด Exec= ในไฟล์ .desktop"""
    cleaned = re.sub(r"%[fFuUdDnNickvm]", "", exec_line).strip()
    try:
        return [a for a in shlex.split(cleaned) if a]
    except ValueError:
        return cleaned.split()


def _installed_apps() -> dict:
    """สแกนแอปจากไฟล์ .desktop บน Ubuntu 26.04 → ใส่เป็นตัวเลือกของ Jev ให้สั่งเปิด/ปิดได้ทุกแอป (จำกัด 220 ตัว)"""
    if env_str("EXTRA_APPS", "auto").lower() in ("off", "0", "no"):
        return {}
    desktop_dirs = [
        Path("/usr/share/applications"),
        Path("/usr/local/share/applications"),
        Path("/var/lib/snapd/desktop/applications"),
        Path("/var/lib/flatpak/exports/share/applications"),
        Path.home() / ".local/share/applications",
    ]
    ignore = re.compile(r"uninstall|help|urlhandler|gnome-.*-panel|gcr-|apport|geoclue|xdg-|initial-setup", re.I)
    out: dict[str, tuple[str, str]] = {}
    for d in desktop_dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.desktop")):
            if ignore.search(p.stem):
                continue
            try:
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            in_entry = False
            name_en, name_th, exec_str, nodisplay = "", "", "", False
            for line in lines:
                s = line.strip()
                if s.startswith("["):
                    if s == "[Desktop Entry]":
                        in_entry = True
                        continue
                    elif in_entry:
                        break
                if not in_entry or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k, v = k.strip(), v.strip()
                if k == "Name" and not name_en:
                    name_en = v
                elif k == "Name[th]" and not name_th:
                    name_th = v
                elif k == "Exec" and not exec_str:
                    exec_str = v
                elif k in ("NoDisplay", "Hidden") and v.lower() == "true":
                    nodisplay = True
            if nodisplay or not name_en or not exec_str or name_en in APPS or name_en in SITES:
                continue
            cmd = _clean_desktop_exec(exec_str)
            if not cmd:
                continue
            LINUX_DESKTOP_APPS.setdefault(name_en, cmd)
            desc = f"{name_en} (Thai: {name_th}) app installed on this Ubuntu PC" if name_th and name_th != name_en else f"{name_en} (app installed on this Ubuntu PC)"
            out.setdefault(name_en, (name_th or name_en, desc))
            if len(out) >= 220:
                return out
    return out


EXTRA_APPS = _installed_apps()
MENUBAR = env_str("MENUBAR", "on").lower() not in ("off", "0", "no")
HUD = env_str("HUD", "on").lower() not in ("off", "0", "no")

# คำปลุก: ค่าเริ่มต้น "จางวิท" (คั่นหลายคำด้วย ,) ตั้ง WAKE_WORD=off เพื่อฟังทุกประโยคโดยไม่ต้องเรียกชื่อ
_wake = env_str("WAKE_WORD", "จางวิท")
WAKE_WORDS = [] if _wake.lower() in ("off", "none", "-") else [w.strip() for w in _wake.split(",") if w.strip()]
WAKE_RE = re.compile("|".join(JANG_WIT_RE if w == "จางวิท" else re.escape(w) for w in WAKE_WORDS), re.I) \
    if WAKE_WORDS else None

RATE = 16000                          # ทุกอย่างเป็น 16 kHz mono
APP_ACTIONS = {"open_app", "quit_app"}
RISKY_ACTIONS = {"quit_app", "lock_screen", "sleep"}
CONF_RISKY = max(CONF_MIN, 0.8)
WEB_ROUTE_CONF = max(CONF_MIN, 0.8)
AGENT_BRAIN = env_str("AGENT_BRAIN", "jev").lower()
COMPOUND_MIN = env_float("COMPOUND_MIN", 0.5)
HISTORY_IDLE_SEC = 180
SPEAK_FIRST = {"volume_mute", "lock_screen", "sleep"}
VOLUME_STEP = 10
FOLLOWUP_SEC = env_float("CONVO_SEC", 30)
BROWSER_PROFILE = ROOT / ".browser-profile"
FASTER_WHISPER_MODEL = env_str("FASTER_WHISPER_MODEL", "large-v3-turbo")
_prompt_mode = env_str("WHISPER_PROMPT_MODE", "auto").lower()
USE_WHISPER_PROMPT = _prompt_mode in ("on", "auto") and "typhoon" not in FASTER_WHISPER_MODEL.lower()
SAVE_UTTERANCES = env_str("SAVE_UTTERANCES")
LOG_HEARD = env_str("LOG_HEARD", "").lower()
STT_SECOND = env_str("STT_SECOND_OPINION", "off")
JEV_PRICE_PER_MTOK = 0.042

# ════════════════════════════════════════════════════════════════════════════
# 3) ตัวช่วยทั่วไป
# ════════════════════════════════════════════════════════════════════════════

_TH_DIGIT = ["", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
_TH_WEEKDAY = ["วันจันทร์", "วันอังคาร", "วันพุธ", "วันพฤหัสบดี", "วันศุกร์", "วันเสาร์", "วันอาทิตย์"]
_THAI_NUMERALS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def thai_number(n: int) -> str:
    """อ่านเลข 0-99 เป็นคำไทย เช่น 21 → ยี่สิบเอ็ด"""
    if n == 0:
        return "ศูนย์"
    tens, units = divmod(n, 10)
    text = "" if tens == 0 else "สิบ" if tens == 1 else "ยี่สิบ" if tens == 2 else _TH_DIGIT[tens] + "สิบ"
    if units:
        text += "เอ็ด" if (units == 1 and tens) else _TH_DIGIT[units]
    return text


def thai_hour(h: int) -> str:
    """ชั่วโมงแบบภาษาพูด 6 ชั่วโมง: ตีหนึ่ง, เจ็ดโมงเช้า, บ่ายสองโมง, หนึ่งทุ่ม ..."""
    if h == 0:
        return "เที่ยงคืน"
    if h <= 5:
        return "ตี" + thai_number(h)
    if h <= 11:
        return thai_number(h) + "โมงเช้า"
    if h == 12:
        return "เที่ยง"
    if h == 13:
        return "บ่ายโมง"
    if h <= 15:
        return "บ่าย" + thai_number(h - 12) + "โมง"
    if h <= 18:
        return thai_number(h - 12) + "โมงเย็น"
    return thai_number(h - 18) + "ทุ่ม"


def thai_time(now: datetime | None = None) -> str:
    now = now or datetime.now()
    m = now.minute
    minute = "ตรง" if m == 0 else "ครึ่ง" if m == 30 else thai_number(m) + "นาที"
    return f"ตอนนี้{thai_hour(now.hour)}{minute}"


def pick(key: str, **kw) -> str:
    """สุ่มประโยคตอบหนึ่งแบบจาก REPLIES แล้วเติมค่า"""
    text = random.choice(REPLIES.get(key) or [""]).format(**kw)
    CANNED.add(text)
    return text


CANNED: set[str] = set()

# รับรูปพ้องเสียงกับ "จางวิท" ที่ต้นประโยค เช่น "ทางวิท", "กางวิท", "ชางวิท", "จางมิด", "จางนิด"
_WAKE_RHYME = re.compile(r"^\s*(?:จ|ช|ท|ก|ด)[่้๊๋]?[ัา]ร?[งนรย]?[\s,]*(?:ว|ม|น|บ)[ิี][่้๊๋]?(?:ท|ต|ด|ช|ธ|ซ|ส|ญ)")


def _fuzzy_wake_prefix(text: str) -> int:
    """ต้นประโยคฟังคล้าย "จางวิท" ไหม คืนความยาวที่ต้องตัดออก หรือ 0"""
    if "จางวิท" not in WAKE_WORDS:
        return 0
    m = _WAKE_RHYME.match(text)
    return m.end() if m else 0


def has_wake(text: str) -> bool:
    return WAKE_RE is None or bool(WAKE_RE.search(text)) or _fuzzy_wake_prefix(text) > 0


def strip_wake(text: str) -> str:
    """ตัดคำปลุกออกก่อนส่งให้ Jev เช่น "จางวิท เปิดไลน์" → "เปิดไลน์" """
    if WAKE_RE is None:
        return text.strip()
    if WAKE_RE.search(text):
        text = WAKE_RE.sub(" ", text, count=1)
    else:
        text = text[_fuzzy_wake_prefix(text):]
    return re.sub(r"^[\s,.!?ๆ]+|[\s,.!?]+$", "", text).strip()


def only_wake(text: str) -> bool:
    """เรียกชื่อเฉยๆ ไม่ได้สั่งอะไร เช่น "จางวิท" / "จางวิทครับ" / "สวัสดีจางวิท" """
    rest = re.sub(r"(ครับผม|ครับ|คับ|ค่ะ|ค่า|คะ|ขา|จ้ะ|จ้า|ฮะ|นะ|หน่อย|สวัสดี|หวัดดี|เฮ้|ฮัลโหล|ว่าไง|อืม|เอ่อ)", "",
                  strip_wake(text))
    return WAKE_RE is not None and has_wake(text) and normalize(rest) == ""


_NUM_DIGIT = {"ศูนย์": 0, "หนึ่ง": 1, "เอ็ด": 1, "สอง": 2, "ยี่": 2, "สาม": 3, "สี่": 4, "ห้า": 5,
              "หก": 6, "เจ็ด": 7, "แปด": 8, "เก้า": 9}
_NUM_WORD = "ศูนย์|หนึ่ง|เอ็ด|สอง|ยี่|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|ร้อย|สิบ"
_NUM_RUN = re.compile(rf"(?:{_NUM_WORD})(?:\s?(?:{_NUM_WORD}))*")
_NOT_NUMBER = re.compile(r"สามารถ|สามี|สามัญ|ห้าง|ห้าม|เก้าอี้|ครึ่งหนึ่ง|หนึ่งเดียว")
_VOLUME_RE = re.compile(r"(?:เสียง|วอลลุ่ม|วอลุ่ม|volume)\D{0,20}?(\d{1,3})|(\d{1,3})\s*(?:%|เปอร์เซ็น)", re.I)


def _thai_number_value(run: str) -> int | None:
    total, digit = 0, None
    for tok in re.findall(_NUM_WORD, run):
        if tok in ("ร้อย", "สิบ"):
            total += (1 if digit is None else digit) * (100 if tok == "ร้อย" else 10)
            digit = None
        elif digit is not None:
            return None
        else:
            digit = _NUM_DIGIT[tok]
    return total + (digit or 0)


def thai_digits(text: str) -> str:
    """แปลงคำอ่านตัวเลขไทยเป็นเลข: 'ตั้งเสียงสามสิบห้าเปอร์เซ็นต์' → 'ตั้งเสียง 35 เปอร์เซ็นต์'"""
    text = text.translate(_THAI_NUMERALS)
    masked = _NOT_NUMBER.sub(lambda m: "\0" * len(m.group()), text)
    out, last = [], 0
    for m in _NUM_RUN.finditer(masked):
        value = _thai_number_value(m.group())
        if value is not None:
            out += [text[last:m.start()], f" {value} "]
            last = m.end()
    out.append(text[last:])
    return re.sub(r"\s+", " ", "".join(out)).strip()


def number_in_text(text: str) -> int | None:
    """ระดับเสียง 0-100 ที่พูดมา (ตัวเลขหรือคำไทย) โดยเลือกเลขหลังคำว่า "เสียง" หรือหน้า "%" ก่อน"""
    m = _VOLUME_RE.search(thai_digits(text))
    if m:
        value = int(m.group(1) or m.group(2))
        return value if value <= 100 else None
    return None


def normalize(text: str) -> str:
    """ตัดช่องว่าง/เครื่องหมาย และรวมสระอำที่ถูกแยก ไว้เทียบข้อความ"""
    return re.sub(r"[\s\.,!?'\"“”‘’()\-–—…]+", "", text.replace("ํา", "ำ")).lower()


def coverage(part: str, whole: str) -> float:
    """สัดส่วนของ part ที่พบใน whole (ไว้จับเสียงสะท้อนเป็นท่อนๆ)"""
    if not part or not whole:
        return 0.0
    blocks = SequenceMatcher(None, part, whole, autojunk=False).get_matching_blocks()
    return sum(b.size for b in blocks) / len(part)


EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def speakable(text: str) -> str:
    """ลบ markdown/อีโมจิ ให้เหลือข้อความที่อ่านออกเสียงได้"""
    text = re.sub(r"^\s*(?:[-*•]|\d+\.)\s+", "", text, flags=re.M)
    text = re.sub(r"[*_#`>|~\[\]]", "", text)
    text = re.sub(r"(?:ค่ะ|คะ)(?=[\s.!?,]|$)", "ครับ", text)
    text = re.sub(r"ดิฉัน", "เรา", text)
    return " ".join(EMOJI_RE.sub("", text).split())


def warm_local_llm() -> None:
    """อุ่นเครื่องเซิร์ฟเวอร์ LLM ในเครื่อง"""
    try:
        llm_chat([{"role": "user", "content": "สวัสดี"}], max_tokens=4)
        print("  🧠 LLM ในเครื่องพร้อมแล้ว")
    except Exception as e:
        print(f"  ⚠️  LLM ในเครื่องยังไม่พร้อม: {e}")


class LocalLLM:
    """เชื่อมต่อหรือเปิดเซิร์ฟเวอร์ LLM ในเครื่อง (เช่น Ollama พอร์ต 11434) บน Ubuntu 26.04"""
    proc: subprocess.Popen | None = None
    lock = threading.Lock()
    port = LOCAL_LLM_PORT

    @classmethod
    def url(cls) -> str:
        return LOCAL_LLM_URL or f"http://127.0.0.1:{cls.port}/v1/chat/completions"

    @classmethod
    def _is_ours(cls, port: int) -> bool:
        try:
            r = requests.get(f"http://127.0.0.1:{port}/v1/models", timeout=1)
            return r.ok and "data" in r.json()
        except (requests.RequestException, ValueError):
            return False

    @classmethod
    def ensure(cls, wait: float = 30) -> None:
        with cls.lock:
            if LOCAL_LLM_URL or cls._is_ours(cls.port):
                return
            for p in (cls.port, 11434, 1234):
                if cls._is_ours(p):
                    cls.port = p
                    return
            if shutil.which("ollama"):
                log = open(ROOT / ".local-llm.log", "a")
                cls.proc = subprocess.Popen(["ollama", "serve"], stdout=log, stderr=log)
                import atexit
                atexit.register(cls.stop)
                end = time.monotonic() + wait
                while time.monotonic() < end and cls.proc.poll() is None:
                    if cls._is_ours(11434):
                        cls.port = 11434
                        return
                    time.sleep(0.3)
            raise RuntimeError(
                "ไม่พบเซิร์ฟเวอร์ LLM ในเครื่อง (เช่น Ollama พอร์ต 11434) "
                "หรือตั้ง LLM_MODE=cloud พร้อมใส่ TOGETHER_API_KEY / GOOGLE_API_KEY / OPENROUTER_API_KEY ใน .env"
            )

    @classmethod
    def stop(cls) -> None:
        if cls.proc is not None and cls.proc.poll() is None:
            cls.proc.terminate()


def llm_chat(messages: list, model: str = "", tools: list | None = None,
             max_tokens: int = 400, temperature: float = 0.6, timeout: float = 25) -> dict:
    """เรียก LLM ผ่าน endpoint แบบ OpenAI (ในเครื่อง, OpenRouter, TogetherAI หรือ Gemini) คืน message ของคำตอบ"""
    if not LLM_KEY:
        raise RuntimeError("ยังไม่ได้ตั้ง OPENROUTER_API_KEY, TOGETHER_API_KEY หรือ GOOGLE_API_KEY")
    body = {"messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    if tools:
        body |= {"tools": tools, "tool_choice": "auto"}
    if LLM_PROVIDER == "ในเครื่อง":
        LocalLLM.ensure()
        body |= {"temperature": min(temperature, 0.2), "repetition_penalty": 1.05}
    elif LLM_PROVIDER == "TogetherAI":
        body |= {"chat_template_kwargs": {"enable_thinking": False}}
    error, statuses = "", []
    url = LocalLLM.url() if LLM_PROVIDER == "ในเครื่อง" else LLM_URL
    for m in dict.fromkeys(x for x in (model or LLM_MODEL, _FALLBACK_MODEL) if x):
        try:
            r = requests.post(url, json={**body, "model": m}, timeout=timeout,
                              headers={"Authorization": f"Bearer {LLM_KEY}", "X-Title": "Jarvis Thai"})
            wait = _retry_delay(r) if r.status_code == 429 else None
            if wait is not None and wait <= 8:
                print(f"  ⏳ {LLM_PROVIDER} {m} ขอให้รอ {wait:.0f} วิ (เพดานต่อนาที)")
                time.sleep(wait + 0.5)
                r = requests.post(url, json={**body, "model": m}, timeout=timeout,
                                  headers={"Authorization": f"Bearer {LLM_KEY}", "X-Title": "Jarvis Thai"})
        except (requests.Timeout, requests.ConnectionError) as e:
            error = f"{LLM_PROVIDER} {m} → {type(e).__name__}"
            print(f"  ⚠️  {error} — ลองโมเดลสำรอง")
            continue
        if r.status_code == 200:
            message = r.json()["choices"][0]["message"]
            if message.get("content"):
                message["content"] = re.sub(r"<think>.*?(?:</think>|$)", "", message["content"], flags=re.S).strip()
            return message
        statuses.append(r.status_code)
        error = f"{LLM_PROVIDER} {m} → {r.status_code}: {_api_error_message(r)}"
        if r.status_code not in (400, 404, 429, 500, 502, 503, 504):
            break
        print(f"  ⚠️  {error} — ลองโมเดลสำรอง")
    if statuses and all(s == 429 for s in statuses):
        raise LLMQuotaError(error)
    raise RuntimeError(error)


class LLMQuotaError(RuntimeError):
    """ผู้ให้บริการ LLM ตอบ 429 ทุกโมเดล"""


def _retry_delay(r) -> float | None:
    if r.headers.get("retry-after", "").replace(".", "", 1).isdigit():
        return float(r.headers["retry-after"])
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', r.text)
    return float(m.group(1)) if m else None


def _api_error_message(r) -> str:
    try:
        data = r.json()
        data = data[0] if isinstance(data, list) else data
        return str(data.get("error", {}).get("message", ""))[:120] or r.text[:120]
    except ValueError:
        return r.text[:120]


# ════════════════════════════════════════════════════════════════════════════
# 4) Jev: ตัดสินใจด้วย speculative fan-out (ถามทุกคำถามในครั้งเดียว)
# ════════════════════════════════════════════════════════════════════════════

class JevError(Exception):
    pass


@dataclass
class Step:
    action: str
    app: str = "none"
    volume: int | None = None
    conf: float = 1.0


@dataclass
class Decision:
    text: str
    category: str
    conf: float
    compound: float = 0.0
    steps: list[Step] = field(default_factory=list)
    ms: float = 0.0
    calls: int = 0
    tokens: int = 0
    chat: str = "none"
    chat_conf: float = 0.0


APP_CRITERIA = {name: v[1] for name, v in (APPS | SITES | EXTRA_APPS).items()}


def step_questions(suffix: str = "", scope: str | None = None,
                   actions: dict | None = None, apps: dict | None = None) -> dict:
    lead = f"Consider ONLY the {scope} action the speaker asks for. " if scope else ""
    return {
        f"action{suffix}": Choice(
            instructions=lead + "Which action does the speaker want the assistant to do?",
            criteria=actions or ACTIONS),
        f"app{suffix}": Choice(
            instructions=lead + "Which app does this action open or quit? Choose none if no app is named.",
            criteria=apps or APP_CRITERIA),
        f"volume{suffix}": Score(
            instructions=lead + "If the speaker sets the volume to a specific level, which level is it?",
            criteria=[desc for _, desc in VOLUME_LEVELS]),
    }


@dataclass
class _MockChoiceAnswer:
    choice: str
    confidence: float
    probabilities: dict


@dataclass
class _MockNoulAnswer:
    noul: float


@dataclass
class _MockScoreAnswer:
    score: float
    confidence: float
    probabilities: dict


@dataclass
class _MockUsage:
    input_tokens: int


@dataclass
class _MockResponse:
    model: str
    usage: _MockUsage
    choices: dict
    nouls: dict
    scores: dict
    answers: dict


def _llm_system_one(state: dict, questions: dict) -> _MockResponse:
    """จำลองการทำงานของ Jev (Speculative Fan-out) ด้วย LLM (Together AI / OpenRouter / Gemini / Ollama)
    ถามทุกคำถามในครั้งเดียวและรับผลลัพธ์เป็น JSON พร้อมค่า confidence"""
    q_desc = {}
    for name, q in questions.items():
        if isinstance(q, Choice):
            q_desc[name] = {
                "type": "choice",
                "instructions": q.instructions,
                "options": q.criteria,
                "return_format": {"choice": "exact_option_key", "confidence": 0.95},
            }
        elif isinstance(q, Noul):
            q_desc[name] = {
                "type": "boolean_probability",
                "instructions": q.instructions,
                "criteria": q.criteria,
                "return_format": {"probability": 0.05},
            }
        else:
            q_desc[name] = {
                "type": "score_index",
                "instructions": q.instructions,
                "levels": {str(i): desc for i, desc in enumerate(q.criteria)},
                "return_format": {"index": 4, "confidence": 0.95},
            }

    sys_prompt = (
        "You are a fast, accurate System-1 decision classifier (replacing Jev) for a Thai voice assistant (จางวิท). "
        "Given the input `state` and `questions`, evaluate EVERY question in `questions` simultaneously and return ONLY a single valid JSON object "
        "(no markdown fences, no explanation). For each question key:\n"
        "- If type == 'choice': return {\"choice\": \"<exact key from options>\", \"confidence\": <float 0.0 to 1.0>}. "
        "Pay close attention to Thai keywords in parentheses.\n"
        "- If type == 'boolean_probability': return {\"probability\": <float 0.0 to 1.0 that the condition is true>}.\n"
        "- If type == 'score_index': return {\"index\": <integer 0 to N-1>, \"confidence\": <float 0.0 to 1.0>}.\n"
        "Be decisive: when the user's intent matches an option, give high confidence (0.85 - 0.99)."
    )
    user_prompt = json.dumps({"state": state, "questions": q_desc}, ensure_ascii=False)
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}]
    msg = llm_chat(messages, model=LLM_MODEL, max_tokens=1024, temperature=0.0, timeout=15)
    raw = (msg.get("content") or "{}").strip()
    m = re.search(r"\{.*\}", raw, flags=re.S)
    try:
        parsed = json.loads(m.group(0) if m else raw)
    except Exception:
        parsed = {}

    choices, nouls, scores, answers = {}, {}, {}, {}
    for name, q in questions.items():
        ans = parsed.get(name) if isinstance(parsed, dict) else {}
        if not isinstance(ans, dict):
            ans = {}
        if isinstance(q, Choice):
            keys = list(q.criteria.keys())
            default_k = "none" if "none" in q.criteria else keys[0]
            ch = str(ans.get("choice", default_k))
            if ch not in q.criteria:
                ch = next((k for k in keys if k.lower() == ch.lower()), default_k)
            conf = float(ans.get("confidence", 0.9 if ch != default_k else 0.8))
            conf = max(0.0, min(1.0, conf))
            rem = max(0.0, 1.0 - conf)
            probs = {k: (conf if k == ch else rem / max(1, len(keys) - 1)) for k in keys}
            if len(keys) > 2:
                for k in keys:
                    if k != ch:
                        probs[k] = max(probs[k], 0.02)
            ca = _MockChoiceAnswer(choice=ch, confidence=conf, probabilities=probs)
            choices[name] = answers[name] = ca
        elif isinstance(q, Noul):
            p = float(ans.get("probability", ans.get("noul", 0.0)))
            p = max(0.0, min(1.0, p))
            na = _MockNoulAnswer(noul=p)
            nouls[name] = answers[name] = na
        else:
            n_lvl = len(q.criteria)
            idx = ans.get("index", 4)
            try:
                idx = max(0, min(n_lvl - 1, int(idx)))
            except (ValueError, TypeError):
                idx = 4
            conf = max(0.0, min(1.0, float(ans.get("confidence", 0.9))))
            probs = {i: (conf if i == idx else (1.0 - conf) / max(1, n_lvl - 1)) for i in range(n_lvl)}
            sa = _MockScoreAnswer(score=float(idx), confidence=conf, probabilities=probs)
            scores[name] = answers[name] = sa

    est_tokens = (len(sys_prompt) + len(user_prompt)) // 3
    model_label = f"{LLM_PROVIDER}:{LOCAL_LLM_MODEL if LLM_PROVIDER == 'ในเครื่อง' else LLM_MODEL}"
    return _MockResponse(model=model_label, usage=_MockUsage(input_tokens=est_tokens),
                         choices=choices, nouls=nouls, scores=scores, answers=answers)


class Jev:
    def __init__(self):
        self.use_llm = not bool(TYPESAFE_API_KEY)
        if not self.use_llm and TypeSafeClient is not None:
            self.client = TypeSafeClient(api_key=TYPESAFE_API_KEY, model=JEV_MODEL, timeout=8.0,
                                         retry=RetryPolicy(max_retries=1))
        else:
            self.use_llm = True
            self.client = None
            if not LLM_KEY:
                raise JevError(
                    "ยังไม่ได้ใส่คีย์ตัดสินใจ: ตั้งค่า TOGETHER_API_KEY, OPENROUTER_API_KEY, GOOGLE_API_KEY "
                    "(หรือ TYPESAFE_API_KEY) ในไฟล์ .env ก่อนใช้งาน"
                )

    @staticmethod
    def state(text: str, extra: str = "") -> dict:
        return {
            "transcript": text,
            "language": "th",
            "context": "Thai speech-to-text transcript captured by จางวิท (Jangwit / Jarvis), an always-listening "
                       "voice assistant that controls an Ubuntu PC and can browse the web. Speech recognition may "
                       "misspell words or write English app names in Thai script. The speaker may be talking "
                       "to the assistant or to someone else." + (f" {extra}" if extra else ""),
        }

    def ask(self, tag: str, text: str, questions: dict, extra: str = ""):
        t0 = time.perf_counter()
        st = self.state(text, extra)
        try:
            resp = _llm_system_one(st, questions) if self.use_llm else self.client.system_one(state=st, questions=questions)
        except Exception as e:
            raise JevError(f"เรียกตัวตัดสินใจไม่สำเร็จ: {e}") from e
        ms = (time.perf_counter() - t0) * 1000
        print_trace(tag, resp, ms)
        return resp, ms

    def ask_state(self, tag: str, state: dict, questions: dict):
        t0 = time.perf_counter()
        try:
            resp = _llm_system_one(state, questions) if self.use_llm else self.client.system_one(state=state, questions=questions)
        except Exception as e:
            raise JevError(f"เรียกตัวตัดสินใจไม่สำเร็จ: {e}") from e
        print_trace(tag, resp, (time.perf_counter() - t0) * 1000)
        return resp

    def decide(self, text: str, extra: str = "") -> Decision:
        questions = {
            "category": Choice(instructions="What kind of utterance is this transcript?", criteria=CATEGORIES),
            "compound": Noul(
                instructions="Does the speaker ask the assistant to do TWO separate actions in this transcript?",
                criteria={"true": "Two different actions joined by words like แล้ว, แล้วก็, และ, กับ, จากนั้น "
                                  "(e.g. หยุดเพลงแล้วเปิดสแล็ก = pause music AND open Slack)",
                          "false": "Only one action, or a question, chit-chat, or noise"}),
            **step_questions(),
            "chat": Choice(instructions="If the speaker is chatting casually with the assistant, which kind of chat "
                                        "is it? Choose none if it needs a real answer or is not casual chat.",
                           criteria=CHAT_INTENTS),
        }
        r1, ms = self.ask("รอบ 1 · fan-out", text, questions, extra)
        try:
            cat = r1.choices["category"]
            d = Decision(text, cat.choice, cat.confidence, compound=r1.nouls["compound"].noul,
                         ms=ms, calls=1, tokens=r1.usage.input_tokens or 0)
            chat = r1.choices.get("chat")
            if chat is not None:
                d.chat, d.chat_conf = chat.choice, chat.confidence
            act = r1.choices["action"]
            if d.category == "question" and act.choice in ("web_task", "read_screen") \
                    and act.confidence >= WEB_ROUTE_CONF:
                why = "คำถามที่ต้องใช้ข้อมูลสด" if act.choice == "web_task" else "ถามเรื่องบนจอ"
                print(f"  ↪ {why} → {act.choice} (action conf {act.confidence:.2f})")
                d.category, d.conf, d.steps = "command", act.confidence, [Step(act.choice, conf=act.confidence)]
                return d
            if d.category != "command":
                return d
            steps = [read_step(r1, "", text)]
            if d.compound >= COMPOUND_MIN:
                acts, apps = likely(act, ACTIONS), likely(r1.choices["app"], APP_CRITERIA)
                r2, ms2 = self.ask("รอบ 2 · แยกสองคำสั่ง", text,
                                   {**step_questions("_1", "FIRST", acts, apps),
                                    **step_questions("_2", "SECOND", acts, apps)}, extra)
                d.ms, d.calls, d.tokens = d.ms + ms2, 2, d.tokens + (r2.usage.input_tokens or 0)
                split = []
                for s in (read_step(r2, "_1", text), read_step(r2, "_2", text)):
                    if s.action != "none" and all((s.action, s.app) != (x.action, x.app) for x in split):
                        split.append(s)
                steps = split or steps
        except KeyError as e:
            raise JevError(f"คำตอบจาก Jev ไม่ครบ: ไม่มี {e}") from e
        d.steps = steps
        d.conf = min([cat.confidence] + [s.conf for s in steps])
        return d


def likely(answer, criteria: dict, p: float = 0.01) -> dict:
    return {k: v for k, v in criteria.items() if k == "none" or answer.probabilities.get(k, 0.0) >= p}


def read_step(resp, suffix: str, text: str) -> Step:
    action = resp.choices[f"action{suffix}"]
    step = Step(action.choice, conf=action.confidence)
    if step.action in APP_ACTIONS:
        app = resp.choices[f"app{suffix}"]
        step.app = app.choice
        step.conf = min(step.conf, app.confidence if app.choice != "none" else 0.0)
    if step.action == "volume_set":
        spoken = number_in_text(text)
        if spoken is not None:
            step.volume = spoken
        else:
            vol = resp.scores[f"volume{suffix}"]
            step.volume = VOLUME_LEVELS[max(vol.probabilities, key=vol.probabilities.get)][0]
            step.conf = min(step.conf, vol.confidence)
    return step


def print_trace(tag: str, resp, ms: float) -> None:
    clock = datetime.now().strftime("%H:%M:%S")
    tokens = resp.usage.input_tokens or 0
    print(f"  ┌─ Jev {tag} · {clock} · {ms:.0f} ms · {resp.model} · {tokens} tokens")
    choice_types = (ChoiceAnswer, _MockChoiceAnswer) if ChoiceAnswer is not None else (_MockChoiceAnswer,)
    noul_types = (NoulAnswer, _MockNoulAnswer) if NoulAnswer is not None else (_MockNoulAnswer,)
    for name, a in resp.answers.items():
        if isinstance(a, choice_types):
            value, conf = a.choice, a.confidence
            runner = sorted(a.probabilities.items(), key=lambda kv: -kv[1])[1:2]
            extra = f"  (รอง: {runner[0][0]} {runner[0][1]:.2f})" if runner else ""
        elif isinstance(a, noul_types):
            value, conf, extra = f"{'ใช่' if a.noul >= 0.5 else 'ไม่ใช่'} p={a.noul:.2f}", max(a.noul, 1 - a.noul), ""
        else:
            level = max(a.probabilities, key=a.probabilities.get)
            value, conf, extra = f"{VOLUME_LEVELS[level][0]}%", a.confidence, f"  (ค่าคาดหมาย {a.score:.1f})"
        flag = " ⚠" if conf < CONF_MIN else "  "
        print(f"  │ {name:<10} {value:<16} conf {conf:.2f}{flag}{extra}")
    print("  └─")


def required_conf(d: Decision) -> float:
    return CONF_RISKY if any(s.action in RISKY_ACTIONS for s in d.steps) else CONF_MIN


def describe(d: Decision) -> str:
    if d.category != "command":
        return d.category
    return " + ".join(describe_step(s) for s in d.steps) or "command"


def describe_step(s: Step) -> str:
    if s.action in APP_ACTIONS:
        return f"{s.action}({s.app})"
    if s.action == "volume_set":
        return f"volume_set({s.volume}%)"
    return s.action


# ════════════════════════════════════════════════════════════════════════════
# 5) คำสั่ง Ubuntu 26.04 (Linux / GNOME / WirePlumber / Shell)
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class Plan:
    reply: str                                             # ประโยคที่จะพูดเมื่อสำเร็จ
    cmds: list[list[str]] = field(default_factory=list)    # คำสั่งทางเลือก: ลองตัวแรก ถ้าล้มเหลวค่อยตัวถัดไป
    speak_first: bool = False                              # พูดให้จบก่อนค่อยทำ
    job: str = ""                                          # งานเบื้องหลัง: web / computer / screen
    fallback_web: str = ""                                 # ทำไม่สำเร็จ → ส่งต่อให้เอเจนต์เว็บด้วยคำขอนี้
    fail_reply: str = ""                                   # พูดเมื่อทำไม่สำเร็จ (ว่าง = ประโยคกลาง)
    func: object = None                                    # งานที่ทำในโปรแกรมเอง (แทนคำสั่ง shell) คืน True = สำเร็จ


def _default_browser() -> str:
    """ชื่อหรือคำสั่งเบราว์เซอร์เริ่มต้นบน Linux"""
    try:
        out = read_cmd(["xdg-settings", "get", "default-web-browser"]).lower()
        if "chrome" in out:
            return "google-chrome"
        if "chromium" in out:
            return "chromium"
        if "firefox" in out:
            return "firefox"
    except Exception:
        pass
    return "google-chrome"


def open_url_cmd(url: str) -> list[str]:
    """เปิดลิงก์ในเบราว์เซอร์ประจำของผู้ใช้ (ถ้าเป็น Chrome ต้องไม่ไปโผล่ในหน้าต่างของจางวิท)"""
    from browser_agent import CHROME
    if "chrome" in _default_browser() and CHROME.exists():
        from computer_agent import user_chrome_cmd
        return user_chrome_cmd(url)
    return ["xdg-open", url]


def user_chrome_pids() -> list[int]:
    """โปรเซสหลักของ Chrome ที่ผู้ใช้ใช้เอง (ไม่นับตัวของเอเจนต์เว็บ)"""
    out = read_cmd(["pgrep", "-f", "chrome"])
    pids = []
    for line in out.splitlines():
        p = line.strip()
        if not p.isdigit():
            continue
        pid = int(p)
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", errors="ignore")
            if BROWSER_PROFILE.name not in cmd and "--type=" not in cmd:
                pids.append(pid)
        except OSError:
            pass
    return pids


def quit_user_chrome() -> bool:
    """ปิดเฉพาะ Chrome ของผู้ใช้ ไม่แตะตัวของจางวิท"""
    pids = user_chrome_pids()
    if not pids:
        return False
    ok = True
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            ok = False
    return ok


def read_cmd(cmd: list[str]) -> str:
    """รันคำสั่งแบบอ่านอย่างเดียว (ไม่เปลี่ยนสถานะเครื่อง) ใช้ได้แม้ใน dry-run"""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def app_running(app: str) -> bool:
    """เช็คว่าแอปกำลังรันอยู่หรือไม่บน Ubuntu"""
    proc_name = app.lower()
    from computer_agent import LINUX_APP_MAP
    target = LINUX_APP_MAP.get(app, proc_name)
    out = read_cmd(["pgrep", "-f", target])
    return bool(out.strip())


def app_installed(app: str) -> bool:
    """เช็คว่ามีแอปนี้ติดตั้งอยู่ใน Ubuntu หรือไม่"""
    if app in LINUX_DESKTOP_APPS:
        return True
    from computer_agent import LINUX_APP_MAP
    target = LINUX_APP_MAP.get(app, app.lower())
    return bool(shutil.which(target))


def current_volume() -> int | None:
    """ระดับเสียงปัจจุบันบน Ubuntu (0-100) ผ่าน wpctl (WirePlumber / PipeWire) หรือ amixer"""
    out = read_cmd(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    m = re.search(r"Volume:\s*(\d+(?:\.\d+)?)", out)
    if m:
        return round(float(m.group(1)) * 100)
    out = read_cmd(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
    m = re.search(r"(\d+)%", out)
    if m:
        return int(m.group(1))
    out = read_cmd(["amixer", "sget", "Master"])
    m = re.search(r"\[(\d+)%\]", out)
    if m:
        return int(m.group(1))
    return 50


def host_app() -> str:
    """แอปที่รัน Jarvis อยู่ (ห้ามปิด ไม่งั้น Jarvis ตายไปด้วย)"""
    term = os.getenv("TERM_PROGRAM", "")
    if term:
        return term
    from computer_agent import responsible_app
    return responsible_app()


def music_player() -> str:
    """เครื่องเล่นเพลงบน Ubuntu"""
    return "Spotify" if app_installed("Spotify") else "Browser"


def _set_linux_volume(vol: int, mute: bool = False) -> bool:
    """ปรับระดับเสียงหรือปิดเสียงบน Ubuntu (รองรับ wpctl, pactl, amixer)"""
    vol = max(0, min(100, vol))
    if mute:
        if shutil.which("wpctl"):
            r = subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"], capture_output=True)
            if r.returncode == 0:
                return True
        if shutil.which("pactl"):
            r = subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1"], capture_output=True)
            if r.returncode == 0:
                return True
        if shutil.which("amixer"):
            r = subprocess.run(["amixer", "sset", "Master", "mute"], capture_output=True)
            if r.returncode == 0:
                return True
        return False

    frac = f"{vol / 100.0:.2f}"
    if shutil.which("wpctl"):
        subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"], capture_output=True)
        r = subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", frac], capture_output=True)
        if r.returncode == 0:
            return True
    if shutil.which("pactl"):
        subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"], capture_output=True)
        r = subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{vol}%"], capture_output=True)
        if r.returncode == 0:
            return True
    if shutil.which("amixer"):
        subprocess.run(["amixer", "sset", "Master", "unmute"], capture_output=True)
        r = subprocess.run(["amixer", "sset", "Master", f"{vol}%"], capture_output=True)
        if r.returncode == 0:
            return True
    return False


def _control_mpris(action: str) -> bool:
    """ควบคุมมีเดียผ่าน MPRIS (D-Bus) หรือ playerctl"""
    if shutil.which("playerctl"):
        act_map = {"music_play": "play", "music_pause": "pause", "music_next": "next", "music_previous": "previous"}
        cmd = ["playerctl", act_map.get(action, "play-pause")]
        r = subprocess.run(cmd, capture_output=True)
        if r.returncode == 0:
            return True
    method_map = {
        "music_play": "Play",
        "music_pause": "Pause",
        "music_next": "Next",
        "music_previous": "Previous",
    }
    m = method_map.get(action, "PlayPause")
    cmd = [
        "busctl", "--user", "call", "org.mpris.MediaPlayer2.spotify",
        "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", m
    ]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0


def _toggle_dark_mode() -> bool:
    """สลับโหมดมืด/สว่างบน GNOME (Ubuntu 26.04)"""
    try:
        cur = read_cmd(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"]).strip("'\"")
        new_mode = "default" if cur == "prefer-dark" else "prefer-dark"
        r = subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme", new_mode], capture_output=True)
        return r.returncode == 0
    except Exception:
        return False


def _save_screenshot(path: Path) -> bool:
    """แคปหน้าจอบันทึกเป็นไฟล์ PNG"""
    try:
        from computer_agent import grab_screen_image
        img = grab_screen_image()
        if img is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            img.save(str(path))
            return True
    except Exception:
        pass
    return False


def make_plan(step: Step) -> Plan:
    """แปลงหนึ่งขั้นตอนเป็นคำสั่ง shell + ประโยคตอบ สำหรับ Ubuntu 26.04"""
    a, app = step.action, step.app
    name = (APPS | SITES | EXTRA_APPS).get(app, (app,))[0] or app

    if a == "open_app" and app in SITES:
        return Plan(pick(a, app=name), [open_url_cmd(SITES[app][2])])
    if a == "open_app" and app == "Google Chrome":
        from computer_agent import user_chrome_cmd
        return Plan(pick(a, app=name), [user_chrome_cmd()], fail_reply=f"เปิด{name}ไม่ได้ครับ")
    if a == "open_app":
        if app in LINUX_DESKTOP_APPS:
            return Plan(pick(a, app=name), [LINUX_DESKTOP_APPS[app]], fail_reply=f"ไม่พบแอป{name}ในเครื่องครับ")
        from computer_agent import LINUX_APP_MAP
        target = LINUX_APP_MAP.get(app, app.lower())
        return Plan(pick(a, app=name), [[target]], fail_reply=f"ไม่พบแอป{name}ในเครื่องครับ")

    if a == "quit_app" and app in SITES:
        return Plan(f"{name}เป็นเว็บ ปิดแท็บเองได้เลยครับ")
    if a == "quit_app":
        if app == host_app():
            return Plan(f"ปิด{name}ไม่ได้ครับ เพราะผมทำงานอยู่ในนั้น")
        if app in ("Finder", "Files"):
            return Plan("ปิดหน้าต่างไฟล์ให้แล้วครับ", [["pkill", "-f", "nautilus"]])
        if app == "Google Chrome":
            if not user_chrome_pids():
                return Plan(f"{name}ไม่ได้เปิดอยู่ครับ")
            return Plan(pick(a, app=name), func=quit_user_chrome, fail_reply=f"{name}ยังไม่ปิดครับ")
        from computer_agent import LINUX_APP_MAP
        target = LINUX_APP_MAP.get(app, app.lower())
        if not app_running(target):
            return Plan(f"{name}ไม่ได้เปิดอยู่ครับ")
        return Plan(pick(a, app=name), [["pkill", "-f", target]], fail_reply=f"{name}ยังไม่ปิดครับ")

    if a in ("volume_up", "volume_down"):
        now = current_volume()
        if now is None:
            return Plan("อุปกรณ์เสียงตอนนี้ปรับระดับไม่ได้ครับ")
        new = min(100, now + VOLUME_STEP) if a == "volume_up" else max(0, now - VOLUME_STEP)
        fn = lambda v=new: _set_linux_volume(v, mute=False)
        fn.__name__ = f"set_volume({new}%)"
        return Plan(pick(a, vol=new), func=fn)
    if a == "volume_mute":
        fn = lambda: _set_linux_volume(0, mute=True)
        fn.__name__ = "mute_volume"
        return Plan(pick(a), func=fn, speak_first=True)
    if a == "volume_set":
        vol = max(0, min(100, step.volume if step.volume is not None else 50))
        if vol == 0:
            fn = lambda: _set_linux_volume(0, mute=True)
            fn.__name__ = "mute_volume"
            return Plan(pick("volume_mute"), func=fn, speak_first=True)
        fn = lambda v=vol: _set_linux_volume(v, mute=False)
        fn.__name__ = f"set_volume({vol}%)"
        return Plan(pick(a, vol=vol), func=fn)

    if a.startswith("music_"):
        fn = lambda act=a: _control_mpris(act)
        fn.__name__ = a
        if a == "music_play":
            return Plan(pick(a), func=fn,
                        fail_reply="ยังไม่มีเพลงที่เล่นค้างอยู่ เดี๋ยวเปิดในยูทูบให้นะ",
                        fallback_web="เปิดเพลงตามคำขอนี้ในยูทูบให้เล่นเลย (ถ้าไม่ได้ระบุเพลง ให้เปิดเพลงฮิตไทย)")
        return Plan(pick(a), func=fn)

    if a == "dark_mode":
        return Plan(pick(a), func=_toggle_dark_mode)
    if a == "lock_screen":
        return Plan(pick(a), [["loginctl", "lock-session"]], speak_first=True)
    if a == "sleep":
        return Plan(pick(a), [["systemctl", "suspend"]], speak_first=True)
    if a == "screenshot":
        path = Path.home() / "Desktop" / f"Jarvis-{datetime.now():%Y%m%d-%H%M%S}.png"
        fn = lambda p=path: _save_screenshot(p)
        fn.__name__ = f"screenshot({path.name})"
        return Plan(pick(a), func=fn)
    if a == "tell_time":
        return Plan(thai_time())
    if a == "web_task":
        return Plan(pick(a), job="web")
    if a in ("computer_task", "read_screen"):
        return Plan(pick(a), job="computer" if a == "computer_task" else "screen")
    if a == "stop_talking":
        return Plan("")
    return Plan(pick("none"))


def execute(plan: Plan, dry_run: bool) -> bool:
    """รันคำสั่งของแผน คืน True ถ้าสำเร็จ (หรือไม่มีอะไรต้องรัน)"""
    if plan.func is not None:
        if dry_run:
            print(f"  🧪 [dry-run] {plan.func.__name__}()")
            return True
        ok = bool(plan.func())
        print(f"  ⚙️  {plan.func.__name__}() → {'สำเร็จ' if ok else 'ไม่สำเร็จ'}")
        return ok
    for i, cmd in enumerate(plan.cmds):
        label = "สำรอง: " if i else ""
        if dry_run:
            print(f"  🧪 [dry-run] {label}{shlex.join(cmd)}")
            continue
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"  ⚙️  {label}{shlex.join(cmd)} → ล้มเหลว: {e}")
            continue
        print(f"  ⚙️  {label}{shlex.join(cmd)} → rc={r.returncode}")
        if r.returncode == 0:
            return True
        if r.stderr.strip():
            print(f"     {r.stderr.strip()[:200]}")
    return dry_run or not plan.cmds


def save_utterance(audio: np.ndarray, text: str) -> None:
    """เก็บเสียงแต่ละประโยคเป็น WAV ไว้เทียบโมเดล STT ด้วย --wav"""
    folder = Path(SAVE_UTTERANCES).expanduser()
    folder.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\wก-๙]+", "_", text)[:40] or "empty"
    with wave.open(str(folder / f"{datetime.now():%H%M%S}_{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


# ════════════════════════════════════════════════════════════════════════════
# 6) สมองกลาง: ข้อความ → Jev → สั่งเครื่อง / ถาม LLM / ข้าม → พูดตอบ
# ════════════════════════════════════════════════════════════════════════════

LLM_SYSTEM_PROMPT = """คุณคือ "จางวิท" ผู้ช่วยเสียงบนเครื่องคอมพิวเตอร์ Ubuntu ของผู้ใช้ เป็นผู้ชาย คุยกับผู้ใช้เหมือนเพื่อนสนิท เป็นกันเอง ตอบไว
- ตอบสั้นมาก 1-2 ประโยค เหมือนคุยโทรศัพท์กับเพื่อน ตอบตรงคำถามก่อนเสมอ
- แทนตัวเองว่า "เรา" เท่านั้น (ห้ามใช้ "ฉัน" "ดิฉัน" "ผม") เรียกผู้ใช้ว่า "นาย" หรือไม่ต้องใช้สรรพนาม
- ลงท้ายด้วย "นะ" "อะ" "ครับ" ตามธรรมชาติ สุภาพแบบเพื่อน ห้ามใช้คำหยาบ ห้ามใช้ "กู" "มึง"
- ไม่ต้องถามกลับทุกครั้ง ถามต่อเฉพาะตอนที่ชวนคุยได้จริงหรือคำตอบยังไม่ครบ
- ถ้าผู้ใช้หงุดหงิดหรือบ่นว่าเราทำไม่ได้ ให้ขอโทษสั้นๆ อย่างจริงใจ แล้วถามว่าจะให้ช่วยอะไร ไม่ต้องเล่นมุก
- คำตอบจะถูกอ่านออกเสียง ห้ามใช้ markdown บูลเล็ต เลขข้อ หรืออีโมจิ
- ข้อความของผู้ใช้มาจากการถอดเสียง อาจสะกดผิด (เช่น ร/ล สลับกัน) ให้เดาความหมายที่น่าจะเป็น
- ถ้าไม่แน่ใจข้อเท็จจริง บอกตรงๆ ว่าไม่แน่ใจ ห้ามเดาเรื่องยา สุขภาพ เงิน หรือตัวเลขสำคัญ
- ตอนคุยแบบนี้เรามองไม่เห็นจอและยังไม่ได้ทำอะไรบนเครื่อง ห้ามแต่งว่าเห็นอะไรบนจอหรือทำอะไรให้แล้ว
  ถ้าถามว่าทำได้ไหม ให้บอกว่าทำได้และบอกวิธีสั่ง เช่น "จางวิท อ่านจอให้ฟังหน่อย" "จางวิท เปิดสปอติฟาย"
  "จางวิท หาห้องพักแถวเมืองทองให้หน่อย" "จางวิท คลิกปุ่มบันทึกให้หน่อย"
ตอนนี้คือ {now}"""


class Assistant:
    def __init__(self, speaker, dry_run: bool = False, background_web: bool = False):
        self.jev = Jev()
        self.speaker = speaker
        self.dry_run = dry_run
        self.background_web = background_web
        self.misses = 0
        self.history = deque(maxlen=6)
        self.last_active = 0.0
        self.last_text = ""
        self.last_request = ""
        self.thinking = False
        self._web_agent = None
        self._pc_agent = None
        self._web_bg = None
        self._job_kind = ""
        self.hud_rect = None
        self.last_failed, self.last_failed_at = "", 0.0
        from concurrent.futures import ThreadPoolExecutor
        self._pool = ThreadPoolExecutor(max_workers=1)
        self._stt_pool = ThreadPoolExecutor(max_workers=1)
        self._early = None

    @property
    def browsing(self) -> bool:
        return self.job != ""

    def handle(self, text: str, second_opinion=None) -> None:
        self.last_text, self.thinking = text, True
        try:
            self._handle(text, second_opinion)
        finally:
            self.thinking = False

    def _decide(self, text: str, context: str = "") -> Decision | None:
        try:
            d = self.jev.decide(text, context)
        except JevError as e:
            print(f"  ❌ {e}")
            self.speaker.say(pick("jev_error"))
            return None
        print(f"  ⇒ {describe(d)} · conf {d.conf:.2f} (เกณฑ์ {required_conf(d):.2f}) · Jev {d.calls} ครั้ง {d.ms:.0f} ms")
        return d

    def _handle(self, text: str, second_opinion=None) -> None:
        if only_wake(text):
            self.speaker.say(pick("wake"))
            self.last_active = time.monotonic()
            return
        woke = WAKE_RE is None or has_wake(text)
        text = strip_wake(text)
        if self.history and time.monotonic() - self.last_active > HISTORY_IDLE_SEC:
            self.history.clear()
        chatting = self.history and time.monotonic() - self.last_active < FOLLOWUP_SEC
        context = f"The assistant just said: \"{self.history[-1][1][:120]}\". The speaker may be replying to it." \
            if chatting else ""
        if woke:
            context += " The speaker called the assistant by name, so this is addressed to the assistant."
        early, early_text = None, text
        if LLM_PROVIDER == "ในเครื่อง":
            if self._early is not None:
                self._early.cancel()
            early = self._early = self._pool.submit(self._think, text)
        spec2 = self._stt_pool.submit(second_opinion) if woke and second_opinion is not None else None
        d = self._decide(text, context.strip())
        if d is None:
            return
        need = required_conf(d)
        if woke and d.category != "noise" and d.conf < need and spec2 is not None:
            try:
                alt = strip_wake(spec2.result(timeout=15) or "")
            except Exception as e:
                print(f"  ⚠️  ถอดเสียงซ้ำไม่สำเร็จ: {e}")
                alt = ""
            if alt and normalize(alt) != normalize(text):
                print(f"  🔁 ความเห็นที่สอง: {alt}")
                d2 = self._decide(alt, context.strip())
                if d2 is not None and d2.category != "noise" and d2.conf >= required_conf(d2):
                    d, text, need = d2, alt, required_conf(d2)

        clear_command = d.category == "command" and d.conf >= need and any(s.action != "none" for s in d.steps)
        vague_command = d.category == "command" and any(s.action not in ("none", "web_task") for s in d.steps)
        chat_reply = chatting and d.category != "noise"
        if not clear_command and not vague_command and (woke or chat_reply):
            asks = d.chat in MOOD_INTENTS and ASKS_RE.search(text)
            retry = self.last_failed if d.chat == "retry" and time.monotonic() - self.last_failed_at < 120 else ""
            if retry and d.chat_conf >= CHAT_CONF:
                print(f"  ↻ ลองคำขอเดิมอีกครั้ง: {retry}")
                self.last_failed = ""
                self._handle(retry)
                return
            if d.chat in CHAT_REPLIES and d.chat_conf >= CHAT_CONF and d.category != "command" and not asks:
                print(f"  💬 คุยเล่น ({d.chat} {d.chat_conf:.2f}) → ตอบทันทีจาก Jev ไม่ต้องรอ LLM")
                self._canned_reply(text, d.chat, early)
                return
            print("  💬 คุยเล่น/ถามทั่วไป → ตอบแบบเพื่อน")
            self._chat_reply(text, early, early_text)
            return
        if d.category == "noise":
            print("  🔇 ไม่ได้พูดกับจางวิท — ข้าม")
            return
        if d.conf < need and not woke:
            print("  🔇 ไม่ชัดและไม่ได้เรียกชื่อ — ข้ามเงียบๆ")
            return
        if d.conf < need:
            self.misses += 1
            if self.misses >= 2:
                self.misses = 0
                print("  ⏭  พลาด 2 ครั้งติด — ข้าม")
                self.speaker.say(pick("skip"))
            else:
                print("  ↻  ความมั่นใจต่ำ — ขอให้พูดใหม่")
                unknown_app = any(s.action in APP_ACTIONS and s.app == "none" for s in d.steps)
                self.speaker.say(pick("which_app" if unknown_app else "retry"))
            self.last_active = time.monotonic()
            return
        self.misses = 0
        if d.category == "question" or all(s.action == "none" for s in d.steps):
            self._chat_reply(text, early, early_text)
            return
        else:
            spoken = self.run_steps(d.steps, text)
            if spoken:
                self.history.append((text, spoken))
        self.last_request = text
        self.last_active = time.monotonic()

    def _canned_reply(self, text: str, intent: str, early=None) -> None:
        if early is not None:
            early.cancel()
        answer = random.choice(CHAT_REPLIES[intent])
        CANNED.add(answer)
        self.misses = 0
        self.speaker.say(answer)
        self.history.append((text, answer))
        self.last_request = text
        self.last_active = time.monotonic()

    def _chat_reply(self, text: str, early=None, early_text: str = "") -> None:
        self.misses = 0
        if early is not None and early_text == text and not early.cancelled():
            answer, ok = early.result()
        else:
            answer, ok = self._think(text)
        self.speaker.say(answer)
        if ok:
            self.history.append((text, answer))
        self.last_request = text
        self.last_active = time.monotonic()

    def run_steps(self, steps: list[Step], text: str) -> str:
        if any(s.action == "stop_talking" for s in steps) and self._web_bg is not None and self._web_bg.cancel():
            print("  🛑 ยกเลิกงานเบื้องหลัง")
            reply = pick("web_cancel")
            self.speaker.say(reply)
            return reply
        plans = [make_plan(s) for s in steps]
        replies, web, task = [], None, text
        jobs = {p.job for p in plans if p.job}
        for p in plans:
            if p.job:
                if web is None:
                    web = p if len(jobs) == 1 else Plan(p.reply, job="computer")
            elif not p.speak_first:
                ok = execute(p, self.dry_run)
                replies.append(p.reply if ok else (p.fail_reply or pick("fail")))
                if not ok and p.fallback_web and web is None and LLM_KEY:
                    web, task = Plan("", job="web"), f"{p.fallback_web}: {text}"
        later = [p for p in plans if p.speak_first]
        replies += [p.reply for p in later]
        if web is not None:
            replies.append(web.reply if LLM_KEY else pick("web_no_llm"))
        spoken = " ".join(r for r in replies if r)
        self.speaker.say(spoken)
        after = []
        if later and web is not None and LLM_KEY and not self.dry_run:
            after = later
        elif later:
            if self.speaker.wait():
                print("  ✋ ถูกขัดก่อนทำ — ยกเลิกคำสั่งที่ต้องพูดก่อน")
            else:
                for p in later:
                    execute(p, self.dry_run)
        if web is not None and LLM_KEY:
            self.start_job(web.job, task, after)
        return spoken

    @property
    def job(self) -> str:
        return self._job_kind if self._web_bg is not None and self._web_bg.running else ""

    def start_job(self, kind: str, task: str, after: list | None = None) -> None:
        label = {"web": "🌐 เอเจนต์ท่องเว็บ", "computer": "🖱 เอเจนต์คุมคอม", "screen": "👀 อ่านจอ"}[kind]
        if self.dry_run:
            print(f"  🧪 [dry-run] {label} ({AGENT_MODEL}): «{task}»")
            return
        if self._web_agent is None:
            from browser_agent import BackgroundBrowser, BrowserAgent
            from computer_agent import ComputerAgent, JevComputerAgent
            self._web_agent = BrowserAgent(self._agent_chat, BROWSER_PROFILE)
            if AGENT_BRAIN == "llm":
                self._pc_agent = ComputerAgent(self._agent_chat, web=self._web_agent, exclude=lambda: self.hud_rect)
            else:
                apps = {k: v for k, v in APP_CRITERIA.items() if k not in SITES}
                self._pc_agent = JevComputerAgent(self.jev.ask_state, apps, chat=self._agent_chat,
                                                  web=self._web_agent, exclude=lambda: self.hud_rect)
            if self.background_web:
                self._web_bg = BackgroundBrowser(self._web_agent)
        request = task
        if kind == "web" and self.last_request and time.monotonic() - self.last_active < 120:
            task = f"{task}\n(คำขอก่อนหน้าของผู้ใช้ อาจเกี่ยวข้อง: {self.last_request})"
        from computer_agent import describe_screen
        runner = {"web": self._web_agent.run, "computer": self._pc_agent.run,
                  "screen": lambda t, cancel=None: describe_screen(self._agent_chat, t,
                                                                   exclude=lambda: self.hud_rect)}[kind]
        print(f"  {label} ({AGENT_MODEL}): «{task}»")
        self._job_kind = kind
        done = lambda summary, error: self._web_done(summary, error, kind, request, after or [])
        if self._web_bg is not None:
            self._web_bg.submit(task, done, runner)
            return
        self.speaker.wait()
        try:
            summary, error = runner(task, None), None
        except Exception as e:
            summary, error = None, e
        done(summary, error)

    @staticmethod
    def _agent_chat(messages: list, tools: list | None) -> dict:
        return llm_chat(messages, model=AGENT_MODEL, tools=tools, max_tokens=1500, temperature=0.2, timeout=45)

    def _web_done(self, summary: str | None, error: Exception | None, kind: str = "web", request: str = "",
                  after: list | None = None) -> None:
        from computer_agent import AgentIncomplete
        speech = speakable(summary) if summary else ""
        if error is not None:
            print(f"  ❌ {'ท่องเว็บ' if kind == 'web' else 'คุมคอม'}ผิดพลาด: {error}")
            if isinstance(error, (PermissionError, AgentIncomplete)):
                said = str(error)
            else:
                said = pick("llm_quota" if isinstance(error, LLMQuotaError) else "web_fail" if kind == "web" else "fail")
            self.speaker.say(said)
            if request:
                self.history.append((request, f"(ทำไม่สำเร็จ) {said}"))
                self.last_failed, self.last_failed_at = request, time.monotonic()
        elif not speech:
            if summary is not None:
                print(f"  ⚠️  งาน{kind}ได้สรุปว่าง")
                self.speaker.say(pick("web_fail" if kind == "web" else "fail"))
        else:
            self.speaker.say(speech)
            self.history.append((request or "หาข้อมูลบนเว็บ", speech))
            if after and not self.speaker.wait(settle=True):
                for p in after:
                    execute(p, self.dry_run)
            elif after:
                print("  ✋ ถูกพูดแทรก — ไม่ทำคำสั่งที่รอไว้")
        self.last_active = time.monotonic()

    def ask_llm(self, question: str) -> str:
        answer, ok = self._think(question)
        if ok:
            self.history.append((question, answer))
        return answer

    def _think(self, question: str) -> tuple[str, bool]:
        if not LLM_KEY:
            return pick("no_llm"), False
        now = datetime.now()
        system = LLM_SYSTEM_PROMPT.format(now=f"{_TH_WEEKDAY[now.weekday()]} {now:%d/%m/%Y %H:%M} น.")
        messages = [{"role": "system", "content": system}]
        for q, a in list(self.history):
            messages += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        messages.append({"role": "user", "content": question})
        t0 = time.perf_counter()
        try:
            answer = speakable(llm_chat(messages).get("content") or "")
        except LLMQuotaError as e:
            print(f"  ❌ LLM โควตาหมด: {e}")
            return pick("llm_quota"), False
        except (RuntimeError, requests.RequestException, KeyError, IndexError, TypeError, ValueError) as e:
            print(f"  ❌ LLM ผิดพลาด: {e}")
            return pick("llm_error"), False
        print(f"  🤖 LLM {LLM_PROVIDER} {LOCAL_LLM_MODEL if LLM_PROVIDER == 'ในเครื่อง' else LLM_MODEL}"
              f" · {(time.perf_counter() - t0) * 1000:.0f} ms")
        return (answer, True) if answer else (pick("llm_error"), False)


# ════════════════════════════════════════════════════════════════════════════
# 7) เสียงพูด (TTS) บน Ubuntu 26.04 (edge-tts + miniaudio)
# ════════════════════════════════════════════════════════════════════════════

_SHUTTING_DOWN = threading.Event()


def _edge_tts_params() -> tuple[str, str, str]:
    voice = TTS_VOICE or "th-TH-NiwatNeural"
    pct = max(-50, min(100, round((TTS_RATE - 180) / 180 * 100)))
    rate_str = f"{pct:+d}%"
    pitch_str = "+0Hz"
    if TTS_PITCH:
        p = TTS_PITCH.strip()
        if p.endswith("Hz"):
            pitch_str = p if p.startswith(("+", "-")) else f"-{p}"
        elif p.lstrip("+-").isdigit():
            val = int(p)
            pitch_str = f"{val:+d}Hz"
    return voice, rate_str, pitch_str


def synthesize(text: str) -> np.ndarray | None:
    """สังเคราะห์ข้อความเป็นเสียง int16 16 kHz mono ด้วย edge-tts และแปลงด้วย miniaudio"""
    if _SHUTTING_DOWN.is_set() or sys.is_finalizing() or not text.strip():
        return None
    import asyncio
    try:
        import edge_tts
        import miniaudio
        voice, rate_str, pitch_str = _edge_tts_params()

        async def _fetch() -> bytes:
            comm = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
            chunks = []
            async for chunk in comm.stream():
                if _SHUTTING_DOWN.is_set() or sys.is_finalizing():
                    return b""
                if chunk.get("type") == "audio" and chunk.get("data"):
                    chunks.append(chunk["data"])
            return b"".join(chunks)

        mp3_bytes = asyncio.run(_fetch())
        if mp3_bytes and not (_SHUTTING_DOWN.is_set() or sys.is_finalizing()):
            decoded = miniaudio.decode(mp3_bytes, output_format=miniaudio.SampleFormat.SIGNED16,
                                       nchannels=1, sample_rate=RATE)
            return np.frombuffer(decoded.samples, dtype=np.int16).copy()
    except Exception as e:
        if not (_SHUTTING_DOWN.is_set() or sys.is_finalizing()):
            print(f"  ⚠️  edge-tts ล้มเหลว ({e})")
    return None


TTS_CACHE_DIR = ROOT / ".tts-cache"
_tts_mem: dict[str, np.ndarray] = {}
_tts_lock = threading.Lock()


def _tts_key(text: str) -> str:
    import hashlib
    return hashlib.sha1(f"{TTS_VOICE}|{TTS_RATE}|{TTS_PITCH}|{text}".encode()).hexdigest()


def speech_audio(text: str) -> np.ndarray | None:
    key = _tts_key(text)
    with _tts_lock:
        hit = _tts_mem.get(key)
    if hit is not None:
        return hit
    path = TTS_CACHE_DIR / f"{key}.npy"
    audio = None
    if path.exists():
        try:
            audio = np.load(path)
        except Exception:
            audio = None
            try:
                path.unlink()
            except OSError:
                pass
    if audio is None:
        audio = synthesize(text)
        if audio is not None and text in CANNED:
            tmp = path.with_name(f"{key}.{threading.get_ident()}.tmp")
            try:
                TTS_CACHE_DIR.mkdir(exist_ok=True)
                with open(tmp, "wb") as f:
                    np.save(f, audio)
                os.replace(tmp, path)
            except OSError:
                try:
                    tmp.unlink()
                except OSError:
                    pass
    if audio is not None and len(text) <= 80:
        with _tts_lock:
            if len(_tts_mem) >= 800:
                _tts_mem.pop(next(iter(_tts_mem)))
            _tts_mem[key] = audio
    return audio


def canned_texts() -> list[str]:
    texts = [t for key in ("ready", "wake", "retry", "which_app", "skip", "fail") for t in REPLIES[key]]
    texts += [t for ts in CHAT_REPLIES.values() for t in ts]
    names = [v[0] for v in (APPS | SITES).values() if v[0]]
    for key in ("open_app", "quit_app"):
        texts += [t.format(app=n) for t in REPLIES[key] for n in names]
    for key in ("volume_up", "volume_down", "volume_set"):
        texts += [t.format(vol=v) for t in REPLIES[key] for v in range(0, 101, 10)]
    texts += [t for ts in REPLIES.values() for t in ts if "{" not in t]
    return list(dict.fromkeys(texts))


def warm_tts() -> None:
    import atexit
    atexit.register(_SHUTTING_DOWN.set)
    todo = canned_texts()
    CANNED.update(todo)
    made = 0
    for text in todo:
        if _SHUTTING_DOWN.is_set() or sys.is_finalizing():
            return
        if not (TTS_CACHE_DIR / f"{_tts_key(text)}.npy").exists():
            made += 1
        speech_audio(text)
    if made and not (_SHUTTING_DOWN.is_set() or sys.is_finalizing()):
        print(f"  🗣️  เตรียมเสียงประโยคสำเร็จรูปไว้แล้ว {made} ประโยค")


class SaySpeaker:
    """พูดผ่าน sounddevice ตรงๆ หรือ print ในโหมด dry-run"""
    on_played = None
    dac_lead = 0.0
    in_warmup = False
    _last_sound = 0.0

    def pause(self) -> None:
        self.stop()

    def resume(self) -> None:
        pass

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self.recent: deque = deque(maxlen=5)
        self._playing = False

    def say(self, text: str) -> None:
        if not text:
            return
        print(f"  🔊 {text}")
        self.recent.append((time.monotonic(), text))
        if not self.enabled:
            return
        self.stop()
        def _play():
            self._playing = True
            try:
                audio = speech_audio(text)
                if audio is not None:
                    try:
                        import sounddevice as sd
                        sd.play(audio, samplerate=RATE, blocking=True)
                    except Exception as e:
                        print(f"  ⚠️  เล่นเสียงไม่สำเร็จ: {e}")
            finally:
                self._playing = False
        threading.Thread(target=_play, daemon=True).start()

    def stop(self) -> None:
        if self._playing:
            try:
                import sounddevice as sd
                sd.stop()
            except Exception:
                pass
            self._playing = False

    @property
    def playing(self) -> bool:
        return self._playing

    busy = playing

    def wait(self, timeout: float = 60, settle: bool = False) -> None:
        end = time.monotonic() + timeout
        while self._playing and time.monotonic() < end:
            time.sleep(0.05)

    def close(self) -> None:
        pass


class Speaker:
    BLOCK = 480
    TAIL = 0.3
    WARMUP = 0.8

    def __init__(self):
        import sounddevice as sd
        self.on_played = None
        self.recent: deque = deque(maxlen=5)
        self.dac_lead = 0.04
        self._lock = threading.Lock()
        self._chunks: deque = deque()
        self._jobs: queue.Queue = queue.Queue()
        self._gen = 0
        self._pending = 0
        self._paused = False
        self._last_sound = 0.0
        self._reply_start = 0.0
        self.level = 0.0
        self.stream = sd.OutputStream(samplerate=RATE, channels=1, dtype="int16",
                                      blocksize=self.BLOCK, callback=self._on_output)
        self.stream.start()
        threading.Thread(target=self._synth_loop, daemon=True).start()

    @property
    def in_warmup(self) -> bool:
        return time.monotonic() - self._reply_start < self.WARMUP

    def pause(self) -> None:
        with self._lock:
            self._paused = bool(self._chunks)

    def resume(self) -> None:
        with self._lock:
            if self._paused:
                self._paused = False
                self._reply_start = time.monotonic()

    def say(self, text: str) -> None:
        if not text:
            return
        print(f"  🔊 {text}")
        with self._lock:
            self._pending += 1
            gen = self._gen
        self.recent.append((time.monotonic(), text))
        self._jobs.put((gen, text))

    def stop(self) -> None:
        with self._lock:
            self._gen += 1
            self._chunks.clear()
            self._paused = False

    @property
    def playing(self) -> bool:
        with self._lock:
            return (bool(self._chunks) and not self._paused) or time.monotonic() - self._last_sound < self.TAIL

    @property
    def busy(self) -> bool:
        with self._lock:
            waiting = bool(self._chunks) and not self._paused
        return self._pending > 0 or waiting or self.playing

    def wait(self, timeout: float = 60, settle: bool = False) -> bool:
        gen, end = self._gen, time.monotonic() + timeout
        while (self.busy or (settle and self._paused)) and self._gen == gen and time.monotonic() < end:
            time.sleep(0.05)
        return self._paused or self._gen != gen

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()

    def _synth_loop(self) -> None:
        while not (_SHUTTING_DOWN.is_set() or sys.is_finalizing()):
            gen, text = self._jobs.get()
            if _SHUTTING_DOWN.is_set() or sys.is_finalizing():
                break
            try:
                audio = speech_audio(text) if gen == self._gen else None
                with self._lock:
                    if audio is not None and gen == self._gen:
                        self._chunks.append(audio)
            except Exception as e:
                if not (_SHUTTING_DOWN.is_set() or sys.is_finalizing()):
                    print(f"  ⚠️  เตรียมเสียงไม่สำเร็จ: {e}")
            finally:
                with self._lock:
                    self._pending -= 1

    def _on_output(self, outdata, frames, time_info, status) -> None:
        self.dac_lead = max(0.0, time_info.outputBufferDacTime - time_info.currentTime)
        out = np.zeros(frames, dtype=np.int16)
        with self._lock:
            filled = 0
            while filled < frames and self._chunks and not self._paused:
                head = self._chunks[0]
                n = min(frames - filled, len(head))
                out[filled:filled + n] = head[:n]
                if n == len(head):
                    self._chunks.popleft()
                else:
                    self._chunks[0] = head[n:]
                filled += n
            if filled:
                now = time.monotonic()
                if now - self._last_sound > self.TAIL:
                    self._reply_start = now
                self._last_sound = now
        outdata[:, 0] = out
        self.level = float(np.sqrt(np.mean(out.astype(np.float32) ** 2))) / 32768
        if self.on_played is not None:
            self.on_played(out)


# ════════════════════════════════════════════════════════════════════════════
# 8) หูฟัง: ไมค์ → AEC → VAD → ตัดประโยค (full duplex)
# ════════════════════════════════════════════════════════════════════════════

AEC_FRAME = 160
VAD_CHUNK = 512


class Segmenter:
    CHUNK_MS = 32

    def __init__(self):
        ms = self.CHUNK_MS
        self.start_chunks = 3
        self.barge_chunks = 10
        self.barge_threshold = max(VAD_THRESHOLD, 0.6)
        self.end_chunks = max(1, int(SILENCE_MS / ms))
        self.max_chunks = int(15_000 / ms)
        self.min_voiced = int(300 / ms)
        self.preroll: deque = deque(maxlen=int(500 / ms) + self.barge_chunks)
        self.reset()

    def reset(self) -> None:
        self.active, self.chunks, self.run, self.silence, self.voiced = False, [], 0, 0, 0

    def feed(self, chunk: np.ndarray, prob: float, playing: bool = False,
             allow_barge: bool = True) -> tuple[np.ndarray | None, bool]:
        self.preroll.append(chunk)
        if not self.active:
            if playing and not allow_barge:
                self.run = 0
                return None, False
            threshold = self.barge_threshold if playing else VAD_THRESHOLD
            self.run = self.run + 1 if prob >= threshold else 0
            if self.run < (self.barge_chunks if playing else self.start_chunks):
                return None, False
            self.active, self.chunks, self.voiced, self.silence = True, list(self.preroll), self.run, 0
            return None, playing
        self.chunks.append(chunk)
        if prob >= VAD_THRESHOLD * 0.7:
            self.voiced, self.silence = self.voiced + 1, 0
        else:
            self.silence += 1
        if self.silence < self.end_chunks and len(self.chunks) < self.max_chunks:
            return None, False
        audio = np.concatenate(self.chunks) if self.voiced >= self.min_voiced else None
        self.reset()
        self.preroll.clear()
        return audio, False


def make_echo_canceller():
    try:
        from livekit import rtc
    except ImportError:
        return None, None
    try:
        return rtc, rtc.AudioProcessingModule(echo_cancellation=True, high_pass_filter=True)
    except Exception:
        return None, None


class Ears:
    BLOCK = 480

    def __init__(self, speaker):
        import sounddevice as sd
        from pysilero_vad import SileroVoiceActivityDetector
        self.speaker = speaker
        self.vad = SileroVoiceActivityDetector()
        self.seg = Segmenter()
        self.utterances: queue.Queue = queue.Queue()
        self._blocks: queue.Queue = queue.Queue()
        self.rtc, self.apm = make_echo_canceller() if isinstance(speaker, Speaker) else (None, None)
        self._apm_lock = threading.Lock()
        self._adc_lag = 0.05
        self.barge_in = BARGE_IN == "on" or (BARGE_IN == "auto" and self.apm is not None)
        self.listening = True
        self.level = 0.0
        self._talk = 0
        self._overlap = self._interrupted = False
        speaker.on_played = self._reference
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16",
                                     blocksize=self.BLOCK, callback=self._on_input)

    def start(self) -> None:
        self.stream.start()
        threading.Thread(target=self._loop, daemon=True).start()

    def set_listening(self, on: bool) -> None:
        if on == self.listening:
            return
        self.listening = on
        if on:
            self.stream.start()
        else:
            self.stream.stop()
            self.seg.reset()
            self.vad.reset()
            self.speaker.resume()
        print(f"\n{'🎙  เปิดการฟังแล้ว' if on else '🔇 ปิดการฟังแล้ว'}")

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()
        self.speaker.on_played = None
        with self._apm_lock:
            self.apm = None

    @property
    def delay_ms(self) -> int:
        return int(min(400, max(0, (self.speaker.dac_lead + self._adc_lag) * 1000 + 5)))

    def _frames(self, samples: np.ndarray):
        for i in range(0, len(samples) - AEC_FRAME + 1, AEC_FRAME):
            yield i, self.rtc.AudioFrame(bytearray(samples[i:i + AEC_FRAME].tobytes()), RATE, 1, AEC_FRAME)

    def _aec_failed(self, e: Exception) -> None:
        self.apm = None
        self.barge_in = BARGE_IN == "on"
        print(f"\n⚠️  ตัวตัดเสียงสะท้อนผิดพลาด ({e}) — ปิด AEC และไม่ฟังระหว่างจางวิทพูด")

    def _reference(self, played: np.ndarray) -> None:
        with self._apm_lock:
            if self.apm is not None:
                try:
                    for _, frame in self._frames(played):
                        self.apm.process_reverse_stream(frame)
                except Exception as e:
                    self._aec_failed(e)

    def _on_input(self, indata, frames, time_info, status) -> None:
        self._adc_lag = max(0.0, time_info.currentTime - time_info.inputBufferAdcTime)
        block = indata[:, 0].copy()
        with self._apm_lock:
            if self.apm is not None:
                try:
                    delay = self.delay_ms
                    for i, frame in self._frames(block):
                        self.apm.set_stream_delay_ms(delay)
                        self.apm.process_stream(frame)
                        block[i:i + AEC_FRAME] = np.frombuffer(frame.data, dtype=np.int16)
                except Exception as e:
                    self._aec_failed(e)
        self._blocks.put(block)

    def _loop(self) -> None:
        pending = np.zeros(0, dtype=np.int16)
        heard, started, warned = 0, time.monotonic(), False
        while True:
            pending = np.concatenate([pending, self._blocks.get()])
            while len(pending) >= VAD_CHUNK:
                chunk, pending = pending[:VAD_CHUNK], pending[VAD_CHUNK:]
                heard = max(heard, int(np.abs(chunk).max()))
                self._on_chunk(chunk)
            if not warned and heard == 0 and time.monotonic() - started > 3:
                warned = True
                print("⚠️  ไมค์ส่งมาแต่ความเงียบสนิท — ตรวจสอบการตั้งค่าไมค์ในระบบ")

    def _on_chunk(self, chunk: np.ndarray) -> None:
        if not self.listening:
            return
        playing = self.speaker.playing
        if playing and not self.barge_in:
            if self.seg.active or self.seg.run:
                self.seg.reset()
                self.vad.reset()
            return
        self.level = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) / 32768
        prob = self.vad.process_chunk(chunk.tobytes())
        talking = playing and self.seg.active and not self.speaker.in_warmup and prob >= self.seg.barge_threshold
        self._talk = self._talk + 1 if talking else 0
        if self._talk >= 4:
            self.speaker.pause()
            self._interrupted = True
        was_active = self.seg.active
        audio, barged = self.seg.feed(chunk, prob, playing, allow_barge=not self.speaker.in_warmup)
        if self.seg.active and not was_active:
            self._overlap = playing
            self._interrupted = False
        if barged:
            self.speaker.pause()
            self._interrupted = True
            print("\n✋ ได้ยินเสียงแทรก — หยุดฟังก่อน")
        if was_active and not self.seg.active:
            self.vad.reset()
            if audio is None:
                if self._interrupted:
                    self.speaker.resume()
                return
            self.utterances.put((audio.astype(np.float32) / 32768.0, self._overlap, self._interrupted))


LOOP_RE = re.compile(r"([^\s\d].{0,14}?)(?:\s*\1){2,}")


def collapse_repeats(text: str) -> str:
    text = " ".join(text.split())
    text = re.sub(r"(.{5,}?)(?:\s*\1)+", r"\1", text)
    head, _, tail = text.rpartition(" ")
    if head and len(tail) >= 2 and head.startswith(tail):
        text = head
    return text


def is_garbage(text: str) -> bool:
    t = normalize(text)
    if len(t) < 2:
        return True
    if len(t) < 40 and any(normalize(h) in t for h in HALLUCINATIONS):
        return True
    prompt = normalize(WHISPER_PROMPT)
    return len(t) >= len(prompt) // 2 and coverage(t, prompt) > 0.9


def is_echo(text: str, recent) -> bool:
    t, now = normalize(text), time.monotonic()
    return len(t) >= 6 and any(now - ts < 20 and coverage(t, normalize(said)) > 0.8 for ts, said in list(recent))


# ════════════════════════════════════════════════════════════════════════════
# 9) แปลงเสียงเป็นข้อความ (faster-whisper ในเครื่องบน Ubuntu 26.04)
# ════════════════════════════════════════════════════════════════════════════

def _preload_cuda_libs() -> None:
    """โหลด cuBLAS/cuDNN จากแพ็กเกจ pip (nvidia-cublas-cu12, nvidia-cudnn-cu12) ให้ CTranslate2 ใช้ GPU ได้
    โดยไม่ต้องตั้ง LD_LIBRARY_PATH เอง"""
    import ctypes
    import glob
    import site
    roots = list(site.getsitepackages()) + [site.getusersitepackages()]
    # โหลด cuBLAS ก่อน แล้วค่อย cuDNN (cuDNN ต้องพึ่ง cuBLAS)
    for pattern in ("nvidia/cublas/lib/libcublasLt.so.*", "nvidia/cublas/lib/libcublas.so.*",
                    "nvidia/cudnn/lib/libcudnn*.so.*"):
        for root in roots:
            for lib in sorted(glob.glob(os.path.join(root, pattern))):
                try:
                    ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


class STT:
    def __init__(self):
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        _preload_cuda_libs()
        device, compute = "cpu", "int8"
        try:
            import ctranslate2
            if ctranslate2.get_cuda_device_count() > 0:
                device, compute = "cuda", "float16"
        except Exception:
            pass
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            sys.exit(
                "\n❌ ไม่พบโมเดลถอดเสียง faster-whisper (หรือยังไม่ได้ติดตั้งแพ็กเกจ)\n"
                "กรุณาติดตั้งแพ็กเกจด้วยคำสั่ง:\n"
                "    .venv/bin/pip install -r requirements.txt\n\n"
                "หากยังไม่มี pip หรือ .venv บน Ubuntu ให้รัน:\n"
                "    sudo apt update && sudo apt install -y python3-pip python3-venv libportaudio2 ffmpeg\n"
                "    rm -rf .venv && python3 -m venv --system-site-packages .venv\n"
                "    .venv/bin/pip install -r requirements.txt\n"
            )
        self._model = WhisperModel(FASTER_WHISPER_MODEL, device=device, compute_type=compute)
        self.whisper_name = f"faster-whisper · {FASTER_WHISPER_MODEL} {compute} {device.upper()}"
        self.name = self.whisper_name
        self.second = STT_SECOND if STT_SECOND.lower() not in ("off", "0", "no", "") else ""

    def warmup(self) -> None:
        self.transcribe(np.zeros(RATE, dtype=np.float32))

    def transcribe_second(self, audio: np.ndarray) -> str:
        if not self.second:
            return ""
        text = self._run(audio, None, model_name=self.second)
        return "" if LOOP_RE.search(text) else collapse_repeats(text)

    @staticmethod
    def normalize(audio: np.ndarray) -> np.ndarray:
        frames = audio[: len(audio) // 480 * 480].reshape(-1, 480)
        if not len(frames):
            return audio
        rms = np.sqrt((frames ** 2).mean(1))
        speech = rms[rms >= np.percentile(rms, 60)].mean()
        if speech < 1e-4:
            return audio
        return np.clip(audio * min(0.1 / speech, 20.0), -1, 1).astype(np.float32)

    def _run(self, audio: np.ndarray, prompt: str | None, model_name: str = "") -> str:
        audio = self.normalize(audio)
        max_tokens = min(224, int(15 * len(audio) / RATE) + 24)
        segs, _ = self._model.transcribe(audio, language="th", initial_prompt=prompt, beam_size=5,
                                         temperature=0.0, condition_on_previous_text=False,
                                         vad_filter=False, max_new_tokens=max_tokens)
        segments = [(s.text, s.avg_logprob, s.compression_ratio) for s in segs]
        return " ".join(t.strip() for t, logprob, ratio in segments if logprob >= -1.0 and ratio <= 2.4).strip()

    def transcribe(self, audio: np.ndarray) -> str:
        text = self._run(audio, WHISPER_PROMPT if USE_WHISPER_PROMPT else None)
        if USE_WHISPER_PROMPT and LOOP_RE.search(text):
            text = self._run(audio, None)
        return "" if LOOP_RE.search(text) else collapse_repeats(text)


# ════════════════════════════════════════════════════════════════════════════
# 10) โหมดการทำงาน
# ════════════════════════════════════════════════════════════════════════════

def run_text(text: str, dry_run: bool) -> None:
    speaker = SaySpeaker(enabled=not dry_run)
    assistant = Assistant(speaker, dry_run)
    print(f"🗣️  {text}")
    assistant.handle(text)
    speaker.wait()


def load_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise SystemExit("รองรับเฉพาะ WAV 16-bit")
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        channels, rate = w.getnchannels(), w.getframerate()
    audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != RATE:
        audio = np.interp(np.arange(0, len(audio), rate / RATE), np.arange(len(audio)), audio)
    return audio.astype(np.int16)


def run_wav(path: str, dry_run: bool) -> None:
    from pysilero_vad import SileroVoiceActivityDetector
    audio = load_wav(path)
    audio = np.concatenate([audio, np.zeros(RATE * 2, dtype=np.int16)])
    vad, seg = SileroVoiceActivityDetector(), Segmenter()
    utterances = []
    for i in range(0, len(audio) - VAD_CHUNK + 1, VAD_CHUNK):
        chunk = audio[i:i + VAD_CHUNK]
        u, _ = seg.feed(chunk, vad.process_chunk(chunk.tobytes()))
        if u is not None:
            utterances.append(u)
            vad.reset()
    print(f"🎧 {path}: ยาว {len(audio) / RATE:.1f} วิ ตัดได้ {len(utterances)} ประโยค")
    stt = STT()
    speaker = SaySpeaker(enabled=not dry_run)
    assistant = Assistant(speaker, dry_run)
    for u in utterances:
        t0 = time.perf_counter()
        text = stt.transcribe(u.astype(np.float32) / 32768.0)
        print(f"\n🗣️  {text or '(ว่าง)'}  ·  STT {(time.perf_counter() - t0) * 1000:.0f} ms ({len(u) / RATE:.1f} วิ)")
        if should_handle(text, assistant):
            assistant.handle(text)
            speaker.wait()


def private(text: str) -> str:
    return text if LOG_HEARD == "all" else f"({len(text)} ตัวอักษร)"


def should_handle(text: str, assistant: Assistant, recent=(), overlapped: bool = False) -> bool:
    if not text or is_garbage(text):
        return False
    if overlapped and is_echo(text, recent):
        print(f"  (ตัดทิ้ง: เสียงของจางวิทเองที่ย้อนเข้าไมค์) {text}")
        return False
    if has_wake(text):
        return True
    if overlapped:
        print(f"  (ได้ยินระหว่างจางวิทพูด แต่ไม่ได้เรียกชื่อ — ข้าม) {private(text)}")
        return False
    last = assistant.last_active
    if last and assistant.speaker._last_sound > last:
        last = assistant.speaker._last_sound
    if not last or time.monotonic() - last > FOLLOWUP_SEC:
        print(f"  💤 ไม่ได้เรียกจางวิท — ข้าม: {private(text)}")
        return False
    return True


def shutdown(ears) -> None:
    _SHUTTING_DOWN.set()
    if getattr(shutdown, "done", False):
        return
    shutdown.done = True
    print("\n👋 ไว้คุยกันใหม่นะ")
    for close in (ears.close, ears.speaker.close, LocalLLM.stop):
        try:
            close()
        except Exception:
            pass


def run_menubar(ears: Ears, assistant: Assistant, listen_loop) -> bool:
    """หน้าจอ HUD (GTK3 + WebKit2) + ถาดระบบ (pystray) บน Ubuntu 26.04"""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        gi.require_version("WebKit2", "4.1")
        from gi.repository import Gtk, Gdk, GLib, WebKit2
        if not Gtk.init_check()[0]:
            return False
    except Exception:
        return False

    labels = {"off": "ปิดการฟังอยู่", "web": "กำลังท่องเว็บ…", "control": "กำลังคุมเครื่อง…", "speak": "กำลังพูด…",
              "think": "กำลังคิด…", "listen": "กำลังฟัง — เรียก \"จางวิท\" ได้เลย"}
    colors = {"listen": "#36e3ff", "speak": "#8fc8ff", "think": "#ffb13b",
              "web": "#4dffa6", "control": "#c77dff", "off": "#6f8190"}

    def current_state() -> str:
        job = assistant.job
        return ("off" if not ears.listening else "web" if job == "web" else "control" if job else
                "speak" if ears.speaker.playing else "think" if assistant.thinking else "listen")

    state_file = ROOT / ".hud.json"
    try:
        saved = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}

    pinned = [saved.get("pinned", True)]
    visible = [saved.get("visible", True)]

    # สร้างหน้าต่าง HUD ด้วย GTK 3.0 + WebKit2 4.1
    win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    win.set_title("J.A.R.V.I.S")
    win.set_decorated(False)
    win.set_app_paintable(True)
    win.set_default_size(380, 450)
    win.set_keep_above(pinned[0])

    screen = win.get_screen()
    visual = screen.get_rgba_visual()
    if visual is not None:
        win.set_visual(visual)

    sw, sh = screen.get_width(), screen.get_height()
    x = int(saved.get("x", sw - 380 - 30))
    y = int(saved.get("y", sh - 450 - 70))
    win.move(x, y)

    webview = WebKit2.WebView()
    webview.set_background_color(Gdk.RGBA(0, 0, 0, 0))
    hud_page = (ROOT / "hud.html").resolve()
    webview.load_uri(hud_page.as_uri())

    win.add(webview)
    if visible[0]:
        win.show_all()

    def update_hud():
        st = current_state()
        if visible[0]:
            try:
                wx, wy = win.get_position()
                ww, wh = win.get_size()
                assistant.hud_rect = (wx, wy, ww, wh)
                spk = ears.speaker
                lvl = getattr(spk, "level", 0.0) if st == "speak" else ears.level
                recent = list(getattr(spk, "recent", []))
                data = {"state": st, "level": round(lvl, 4), "pinned": pinned[0],
                        "heard": assistant.last_text[-80:], "reply": recent[-1][1][:90] if recent else ""}
                js = f"window.hud && hud.update({json.dumps(data)})"
                webview.run_javascript(js, None, None, None)
            except Exception:
                pass
        else:
            assistant.hud_rect = None
        return True

    def save_hud():
        try:
            wx, wy = win.get_position()
            state_file.write_text(json.dumps({"x": wx, "y": wy, "pinned": pinned[0], "visible": visible[0]}), encoding="utf-8")
        except Exception:
            pass

    GLib.timeout_add(50, update_hud)

    # System Tray ผ่าน pystray (ถ้ามี)
    try:
        import pystray
        from PIL import Image, ImageDraw

        def make_tray_icon(state: str):
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            col = colors.get(state, "#36e3ff")
            d.ellipse((6, 6, 58, 58), outline=col, width=5)
            d.ellipse((20, 20, 44, 44), fill=col)
            return img

        def toggle_listen(*_):
            ears.set_listening(not ears.listening)

        def toggle_hud(*_):
            visible[0] = not visible[0]
            if visible[0]:
                win.show_all()
            else:
                win.hide()

        def quit_app(*_):
            save_hud()
            shutdown(ears)
            Gtk.main_quit()

        menu = pystray.Menu(
            pystray.MenuItem(lambda _: labels[current_state()], None, enabled=False),
            pystray.MenuItem(lambda _: f"ได้ยินล่าสุด: {(assistant.last_text[:40] or '-')}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda _: "เริ่มฟัง" if not ears.listening else "หยุดฟัง", toggle_listen),
            pystray.MenuItem(lambda _: "ซ่อน J.A.R.V.I.S" if visible[0] else "แสดง J.A.R.V.I.S", toggle_hud),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("ออกจากจางวิท", quit_app),
        )
        tray = pystray.Icon("jarvis", make_tray_icon("listen"), "จางวิท (J.A.R.V.I.S)", menu)
        threading.Thread(target=tray.run, daemon=True).start()
    except Exception:
        pass

    threading.Thread(target=listen_loop, daemon=True).start()
    print("🎛  หน้าจอ J.A.R.V.I.S เปิดแล้วบน Ubuntu (ลากย้ายได้)")

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: (save_hud(), shutdown(ears), Gtk.main_quit()))

    try:
        Gtk.main()
    finally:
        save_hud()
    return True


def run_mic(dry_run: bool) -> None:
    for sig_name in ("SIGTERM", "SIGHUP"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            signal.signal(sig, signal.default_int_handler)
    Jev()
    print("⏳ กำลังโหลดตัวถอดเสียง (faster-whisper) ...")
    stt = STT()
    stt.warmup()
    try:
        speaker = Speaker()
    except Exception as e:
        print(f"⚠️  เปิดลำโพง sounddevice ไม่ได้ ({e}) ใช้ SaySpeaker แทน")
        speaker = SaySpeaker()
    ears = Ears(speaker)
    assistant = Assistant(speaker, dry_run, background_web=True)
    ears.start()
    if LLM_PROVIDER == "ในเครื่อง":
        threading.Thread(target=warm_local_llm, daemon=True).start()

    duplex = ("full duplex + ตัดเสียงสะท้อน (AEC)" if ears.apm is not None and ears.barge_in else
              "full duplex ไม่มี AEC (ควรใส่หูฟัง)" if ears.barge_in else
              "half duplex (ไม่ฟังระหว่างจางวิทพูด)")
    llm_label = (f"ในเครื่อง · {LOCAL_LLM_MODEL} (ตอบคำถาม + ท่องเว็บ)" if LLM_PROVIDER == "ในเครื่อง" else
                 f"{LLM_PROVIDER} {LLM_MODEL} · ท่องเว็บ {AGENT_MODEL}" if LLM_KEY else "ยังไม่ได้ตั้งค่า")
    jev_label = JEV_MODEL if TYPESAFE_API_KEY else f"{LLM_PROVIDER} ({LLM_MODEL}) [แทน TypeSafe]"
    wake = f"{', '.join(WAKE_WORDS)} (คุยต่อได้ {FOLLOWUP_SEC:.0f} วิโดยไม่ต้องเรียกซ้ำ)" if WAKE_WORDS \
        else "ไม่ใช้ (ฟังทุกประโยค)"
    print(f"""
╭─ Jarvis ไทย · จางวิท (Ubuntu 26.04) ────────────────────
│ STT      : {stt.name}
│ Jev      : {jev_label} · CONF_MIN {CONF_MIN:.2f} (คำสั่งเสี่ยง {CONF_RISKY:.2f})
│ LLM      : {llm_label}
│ Voice    : {TTS_VOICE} @ {TTS_RATE} · {duplex}
│ Wake     : {wake}{'  · DRY-RUN' if dry_run else ''}
╰─ พูดได้เลย เช่น "จางวิท เปิดสปอติฟาย" (Ctrl+C เพื่อออก)""")
    speaker.say(pick("ready"))
    threading.Thread(target=warm_tts, daemon=True).start()

    def listen_loop() -> None:
        while True:
            audio, overlapped, interrupted = ears.utterances.get()
            try:
                t0 = time.perf_counter()
                text = stt.transcribe(audio)
                ms = (time.perf_counter() - t0) * 1000
                if SAVE_UTTERANCES:
                    save_utterance(audio, text)
                if not should_handle(text, assistant, speaker.recent, overlapped):
                    if interrupted:
                        speaker.resume()
                    continue
                if interrupted:
                    speaker.stop()
                print(f"\n🗣️  {text}  ·  STT {ms:.0f} ms ({len(audio) / RATE:.1f} วิ)")
                assistant.handle(text, (lambda a=audio: stt.transcribe_second(a)) if stt.second else None)
                print(f"  ⏱  ตอบใน {(time.perf_counter() - t0) * 1000:.0f} ms นับจากพูดจบ (ถอดเสียง {ms:.0f} ms)")
            except Exception as e:
                print(f"  ❌ ผิดพลาดระหว่างประมวลผล: {type(e).__name__}: {e}")
                speaker.resume()

    try:
        if MENUBAR and run_menubar(ears, assistant, listen_loop):
            pass
        else:
            listen_loop()
    except KeyboardInterrupt:
        pass
    finally:
        shutdown(ears)


EVAL_CASES = [
    ("คำสั่งเดี่ยว", "จางวิท เปิดสปอติฟายให้หน่อย", "command", [("open_app", "Spotify")]),
    ("คำสั่งเดี่ยว", "จางวิทย์ ปิดไลน์ที", "command", [("quit_app", "LINE")]),
    ("คำสั่งเดี่ยว", "เพิ่มเสียงหน่อย", "command", [("volume_up",)]),
    ("คำสั่งเดี่ยว", "เบาเสียงลงหน่อยครับ", "command", [("volume_down",)]),
    ("คำสั่งเดี่ยว", "ตั้งเสียงไว้ที่ห้าสิบเปอร์เซ็นต์", "command", [("volume_set", None, 50)]),
    ("คำสั่งเดี่ยว", "ปิดเสียงเครื่องที", "command", [("volume_mute",)]),
    ("คำสั่งเดี่ยว", "ข้ามเพลงนี้ไปเลย", "command", [("music_next",)]),
    ("คำสั่งเดี่ยว", "เปิดโหมดมืดให้หน่อย", "command", [("dark_mode",)]),
    ("คำสั่งเดี่ยว", "ล็อกหน้าจอเลย", "command", [("lock_screen",)]),
    ("คำสั่งเดี่ยว", "ตอนนี้กี่โมงแล้ว", "command", [("tell_time",)]),
    ("คำสั่งเดี่ยว", "เปิดวีเอสโค้ดหน่อย", "command", [("open_app", "Visual Studio Code")]),
    ("คำสั่งเดี่ยว", "ขอ Google Chrome หน่อย", "command", [("open_app", "Google Chrome")]),
    ("คำสั่งเดี่ยว", "จางวิท เปิดยูทูบให้หน่อย", "command", [("open_app", "YouTube")]),
    ("คำสั่งเดี่ยว", "ตั้งเสียงสามสิบห้า", "command", [("volume_set", None, 35)]),
    ("คำสั่งซ้อน", "หยุดเพลงแล้วเปิดสแล็ก", "command", [("music_pause",), ("open_app", "Slack")]),
    ("คำสั่งซ้อน", "ปิดซาฟารีแล้วเปิดโน้ต", "command", [("quit_app", "Safari"), ("open_app", "Notes")]),
    ("คำสั่งซ้อน", "เพิ่มเสียงแล้วก็เปลี่ยนเพลงถัดไป", "command", [("volume_up",), ("music_next",)]),
    ("คำสั่งซ้อน", "ปิด Slack แล้วตั้งเสียง 30", "command", [("quit_app", "Slack"), ("volume_set", None, 30)]),
    ("งานบนเว็บ", "จางวิท หาห้องพักแถวเมืองทองธานีให้หน่อย", "command", [("web_task",)]),
    ("งานบนเว็บ", "ช่วยเช็คราคาไอโฟนรุ่นล่าสุดให้หน่อย", "command", [("web_task",)]),
    ("งานบนเว็บ", "พรุ่งนี้กรุงเทพฝนจะตกไหม", "command", [("web_task",)]),
    ("คุมคอม", "จางวิท อ่านจอให้ฟังหน่อย", "command", [("read_screen",)]),
    ("คุมคอม", "จางวิท อ่านจอได้รึเปล่า", "command", [("read_screen",)]),
    ("คุมคอม", "คลิกปุ่มบันทึกให้หน่อย", "command", [("computer_task",)]),
    ("คุมคอม", "เลื่อนลงอีกหน่อย", "command", [("computer_task",)]),
    ("คุมคอม", "พิมพ์คำว่าสวัสดีลงไปในช่องนี้ที", "command", [("computer_task",)]),
    ("คำถามทั่วไป", "เมืองหลวงของญี่ปุ่นคือที่ไหน", "question", []),
    ("คำถามทั่วไป", "ทำไมท้องฟ้าถึงเป็นสีฟ้า", "question", []),
    ("คำถามทั่วไป", "แนะนำวิธีนอนให้หลับง่ายหน่อย", "question", []),
    ("คำถามทั่วไป", "จางวิท สวัสดี วันนี้เป็นยังไงบ้าง", "question", []),
    ("เสียงรบกวน", "เออ แม่ วันนี้กินข้าวที่ไหนดี", "noise", []),
    ("เสียงรบกวน", "อืม เอ่อ", "noise", []),
    ("เสียงรบกวน", "ขอบคุณที่รับชมค่ะ", "noise", []),
]


def matches(d: Decision, category: str, expected: list[tuple]) -> bool:
    if d.category != category:
        return False
    if category != "command":
        return True
    if len(d.steps) != len(expected):
        return False
    for got, exp in zip(d.steps, expected):
        action, app, vol = (*exp, None, None)[:3]
        if got.action != action or (app and got.app != app) or (vol is not None and got.volume != vol):
            return False
    return True


def describe_expected(category: str, expected: list[tuple]) -> str:
    if category != "command":
        return category
    return " + ".join(describe_step(Step(e[0], (e[1:2] or ["none"])[0] or "none", (*e[2:3], None)[0]))
                      for e in expected)


def run_eval() -> float:
    jev = Jev()
    rows = []
    for i, (group, text, category, expected) in enumerate(EVAL_CASES, 1):
        print(f"\n[{i:02d}/{len(EVAL_CASES)}] {group} · 「{text}」")
        try:
            d = jev.decide(strip_wake(text))
        except JevError as e:
            print(f"❌ {e}")
            rows.append((group, False, 0.0, True, 0.0, 0))
            continue
        ok, low = matches(d, category, expected), d.conf < required_conf(d)
        rows.append((group, ok, d.conf, low, d.ms, d.tokens))
        print(f"{'✅' if ok else '❌'} ได้ {describe(d)}  ·  conf {d.conf:.2f}{' ⚠ ต่ำกว่าเกณฑ์' if low else ''}"
              + ("" if ok else f"  ·  ที่ถูก: {describe_expected(category, expected)}"))

    n = len(rows)
    correct = sum(r[1] for r in rows)
    accuracy = correct / n * 100 if n else 0.0
    tokens = sum(r[5] for r in rows)
    print("\n" + "═" * 60)
    print(f"ผลรวม      : ถูก {correct}/{n} = {accuracy:.1f}%")
    for group in dict.fromkeys(r[0] for r in rows):
        g = [r for r in rows if r[0] == group]
        print(f"  {group:<12}: {sum(r[1] for r in g)}/{len(g)}")
    print(f"conf เฉลี่ย  : {sum(r[2] for r in rows) / n if n else 0.0:.2f}")
    print(f"ต่ำกว่าเกณฑ์ : {sum(r[3] for r in rows)} ประโยค (CONF_MIN {CONF_MIN:.2f}, คำสั่งเสี่ยง {CONF_RISKY:.2f})")
    print(f"ถูกและผ่านเกณฑ์: {sum(r[1] and not r[3] for r in rows)}/{n}")
    print(f"Jev เฉลี่ย  : {sum(r[4] for r in rows) / n if n else 0.0:.0f} ms ต่อประโยค · {tokens} tokens "
          f"(≈ ${tokens * JEV_PRICE_PER_MTOK / 1e6:.5f})")
    print("═" * 60)
    return accuracy


def main() -> None:
    parser = argparse.ArgumentParser(description="Jarvis ไทย (จางวิท) บน Ubuntu 26.04 — ผู้ช่วยสั่งงานด้วยเสียงภาษาไทย แบบ full duplex")
    parser.add_argument("--text", help="สั่งด้วยข้อความแทนเสียง")
    parser.add_argument("--dry-run", action="store_true", help="ไม่สั่งเครื่องจริง แค่ print ว่าจะทำอะไร")
    parser.add_argument("--eval", action="store_true", help="วัดความแม่นกับชุดประโยคทดสอบภาษาไทย")
    parser.add_argument("--wav", help="ป้อนไฟล์เสียง WAV แทนไมค์ (ไว้ทดสอบ VAD + STT)")
    parser.add_argument("--selftest", action="store_true",
                        help="ทดสอบสิทธิ์ อ่านจอ เมาส์ คีย์บอร์ด กับหน้าต่างทดสอบของตัวเอง")
    args = parser.parse_args()
    if args.selftest or os.environ.get("JARVIS_SELFTEST") == "1":
        from selftest import run_selftest
        sys.exit(0 if run_selftest() else 1)
    try:
        if args.eval:
            run_eval()
        elif args.text:
            run_text(args.text, args.dry_run)
        elif args.wav:
            run_wav(args.wav, args.dry_run)
        else:
            run_mic(args.dry_run)
    except JevError as e:
        sys.exit(f"❌ {e}")


if __name__ == "__main__":
    main()
