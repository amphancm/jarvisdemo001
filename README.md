<p align="center">
  <img src="docs/images/banner.png" alt="จางวิท — J.A.R.V.I.S ภาษาไทยบน Ubuntu Linux" width="100%">
</p>

# จางวิท — ผู้ช่วยเสียงภาษาไทยบน Raspberry Pi OS 64-bit และ Ubuntu

จางวิทคือผู้ช่วยแบบ **J.A.R.V.I.S** ในหนัง ที่ฟังภาษาไทยรู้เรื่องบน **Raspberry Pi OS 64-bit Desktop (X11)** และ Ubuntu Linux
แค่เรียก **"จางวิท"** แล้วพูดสิ่งที่อยากให้ทำ — ไม่ต้องกดปุ่ม ไม่ต้องพิมพ์ และคุยต่อได้เหมือนคุยกับเพื่อน

## ลองพูดแบบนี้

| พูดว่า | จางวิทจะ… |
|---|---|
| "จางวิท เปิดยูทูบ" | เปิด YouTube ใน Google Chrome หรือเบราว์เซอร์ของคุณ |
| "จางวิท หยุดเพลงแล้วเปิดสแล็ก" | ทำสองอย่างต่อกันให้เลยผ่าน MPRIS และตัวเปิดแอป Linux |
| "จางวิท ตั้งเสียงไว้ที่สามสิบ" | ปรับเสียงเครื่องเป็น 30% ผ่าน PipeWire / WirePlumber (`wpctl`) |
| "จางวิท ราคาทองวันนี้เท่าไหร่" | ค้นในเว็บแล้วเล่าให้ฟัง |
| "จางวิท หาโรงแรมแถวเชียงใหม่ให้หน่อย" | เปิด Chrome ค้นหาให้ ระหว่างรอคุยเรื่องอื่นได้ |
| "จางวิท อ่านจอให้ฟังหน่อย" | อ่านสิ่งที่อยู่บนจอด้วย OCR / AT-SPI2 แล้วสรุปให้ฟัง |
| "จางวิท เปิดโน้ตแล้วสร้างโน้ตใหม่" | ขยับเมาส์ กดปุ่มให้ทีละขั้นผ่านระบบ Accessibility |
| "จางวิท เหนื่อยจังเลย" | คุยเป็นเพื่อนด้วย AI ภาษาไทย |
| "จางวิท พอแล้ว" | หยุดพูด หรือยกเลิกงานที่ทำอยู่ |

- หลังคุยกันแล้ว **พูดต่อได้อีก 30 วินาทีโดยไม่ต้องเรียกชื่อซ้ำ**
- **พูดแทรก**ตอนจางวิทกำลังพูดได้ (มันจะหยุดฟังทันที)
- ถ้าคนในห้องคุยกันเองโดยไม่ได้เรียก "จางวิท" มันจะไม่ตอบ

## ทำงานยังไง

<p align="center"><img src="docs/images/flow.png" alt="ขั้นตอนการทำงานของจางวิท" width="100%"></p>

1. **ฟัง** — ไมค์ฟังตลอดเวลาด้วย WebRTC AEC และ Silero VAD ตัดเสียงของจางวิทเองออก (จึงพูดแทรกได้)
2. **ถอดเสียงเป็นข้อความ** — ส่งเสียงแต่ละประโยคไปถอดเสียงด้วย Typhoon ASR API (`typhoon-asr-realtime`) จึงไม่ต้องโหลดโมเดล Whisper ขนาดใหญ่บน Raspberry Pi
3. **ตัดสินใจด้วย Jev** — Jev คือ AI ตัดสินใจของ [TypeSafe](https://typesafe.ai) ที่ **เลือกคำตอบจากตัวเลือก**
   (เช่น "เป็นคำสั่งไหม" "เปิดแอปไหน" "คุยเล่นแบบไหน") ถามทุกอย่างในครั้งเดียว ใช้เวลา ~0.4 วินาที
   และบอกด้วยว่ามั่นใจแค่ไหน — **ถ้าไม่มั่นใจ จางวิทจะถามใหม่ ไม่เดาสุ่ม**
4. **ลงมือทำ** — สั่งระบบ Linux (GNOME D-Bus, PipeWire, MPRIS, `gsettings`) / ท่องเว็บด้วย Playwright / คุมเมาส์และคีย์บอร์ดด้วย AT-SPI2
5. **ตอบด้วยเสียง** — สังเคราะห์เสียงพูดภาษาไทยผ่าน Edge TTS (Niwat/Premwadee Neural) คุณภาพสูงและพูดเป็นธรรมชาติ

## หน้าจอ J.A.R.V.I.S

<p align="center"><img src="docs/images/states.png" alt="หน้าจอ J.A.R.V.I.S ในแต่ละสถานะ" width="100%"></p>

ลอยอยู่บนหน้าจอ Ubuntu ขยับตามเสียง และเปลี่ยนสีตามสิ่งที่จางวิทกำลังทำ
**ลากย้ายได้ · ดับเบิลคลิก = หยุด/เริ่มฟัง · คลิกขวา = เมนู** และมีไอคอนบน System Tray (AppIndicator) ให้เปิด/ปิดการฟัง

บน Raspberry Pi HUD ใช้ software rendering ของ WebKit เพื่อหลีกเลี่ยงภาพผิดเพี้ยนจาก GPU ซึ่งอาจทำให้แอนิเมชันช้าลง

## สิ่งที่ต้องมี

- **Raspberry Pi OS 64-bit Desktop (X11)** หรือ Ubuntu Linux
- **Python 3.10 ขึ้นไป**
- **คีย์ของ TypeSafe** (สำหรับ Jev) สมัครที่ [typesafe.ai](https://typesafe.ai)
- **คีย์ Typhoon API** สำหรับถอดเสียง สมัครและดูรายละเอียดที่ [Typhoon ASR docs](https://docs.opentyphoon.ai/en/asr/)
- **คีย์ของ Google Gemini หรือ OpenRouter** (หรือใช้ Ollama รันโมเดลในเครื่อง)
- **Chromium หรือ Google Chrome** (สำหรับเอเจนต์ค้นเว็บ)
- แพ็กเกจระบบ: `python3-gi`, `gir1.2-gtk-3.0`, `tesseract-ocr`, `tesseract-ocr-tha`, `xdotool`, `wireplumber`

## การติดตั้งบน Raspberry Pi OS 64-bit (ทำครั้งเดียว)

**1. ติดตั้งแพ็กเกจระบบที่จำเป็น**

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv python3-dev build-essential \
    python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-atspi-2.0 \
    tesseract-ocr tesseract-ocr-tha xdotool libxtst6 wireplumber libportaudio2 ffmpeg
```

**2. Clone repository และเตรียม Environment**

```bash
git clone https://github.com/jaturapornchai/jarvisdemo001.git
cd jarvisdemo001
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
```

**3. ตั้งค่าคีย์ในไฟล์ `.env`**

```bash
cp .env.example .env
```
เปิด `.env` แล้วใส่คีย์:
- `TYPESAFE_API_KEY=...`
- `TYPHOON_API_KEY=...`
- `GOOGLE_API_KEY=...` หรือ `OPENROUTER_API_KEY=...` (เมื่อต้องการใช้โมเดลคลาวด์)

## เริ่มใช้งาน

```bash
./run_app.sh
```

หากยังไม่มี `.venv` หรือแพ็กเกจ Python ยังไม่ครบ สคริปต์จะสร้าง virtual environment และติดตั้งแพ็กเกจจาก `requirements.txt` ใน `.venv` โดยไม่ติดตั้งลง Python ของระบบ

จางวิทจะเปิดทำงานพร้อมหน้าจอ J.A.R.V.I.S HUD
ปิดได้ด้วย **Ctrl+C** ในเทอร์มินัล หรือเมนู **ออก** ที่ไอคอน System Tray

### แก้ปัญหาเปิดไมค์ไม่สำเร็จ

หากพบ `PortAudio library not found` ให้ติดตั้งไลบรารีระบบ (การติดตั้ง `sounddevice` ด้วย pip อย่างเดียวไม่เพียงพอ) แล้วรันใหม่:

```bash
sudo apt update
sudo apt install -y libportaudio2
./run_app.sh
```

หากพบ `Error starting stream: Wait timed out` ให้ตรวจสอบไมค์และดูรายการอุปกรณ์:

```bash
.venv/bin/python -m sounddevice
arecord -l
```

ลองระบุหมายเลขหรือส่วนหนึ่งของชื่ออุปกรณ์ **input** จากรายการ sounddevice ใน `.env` เช่น `MIC_DEVICE=1` แล้วรันใหม่ หมายเลขอาจเปลี่ยนเมื่อเสียบอุปกรณ์ใหม่; เว้นว่างเพื่อใช้ค่าเริ่มต้น ตัวรับเสียงใช้ blocking-read mode เพื่อเลี่ยง callback thread timeout บน ALSA การเลือกอุปกรณ์ ALSA โดยตรงอาจใช้ไม่ได้หากแอปอื่นหรือ PipeWire กำลังใช้ไมค์อยู่ และไมค์ต้องรองรับ 16 kHz mono

หากใช้ไมค์ในเว็บแคม USB แล้วไม่ตอบสนองต่อเสียงพูด สาเหตุที่พบบ่อยคือเกนไมค์ฮาร์ดแวร์สูงสุดจนเสียงพูดแตก (clipping) แอปจะลดเกนลงเป็น 40% ให้อัตโนมัติตอนเริ่ม ปรับได้ด้วย `MIC_GAIN` ใน `.env` (เช่น `MIC_GAIN=30`; `off` = ไม่ปรับ)

หากใช้หูฟัง Bluetooth ที่เสียงออกได้แต่ไมค์ไม่ทำงาน ให้เปลี่ยนโปรไฟล์จาก **High Fidelity Playback (A2DP)** เป็น **Headset Head Unit (HSP/HFP)** ใน Settings > Sound หรือใช้ `pactl list cards` เพื่อดูชื่อการ์ด แล้วสั่ง `pactl set-card-profile <ชื่อการ์ด> headset-head-unit` จากนั้นเลือกไมค์หูฟังเป็น Input ใน Settings > Sound (หรือ `pactl set-default-source <ชื่อแหล่งเสียงไมค์>`). โปรไฟล์ HSP/HFP เปิดไมค์ได้แต่คุณภาพเสียงขาออกจะลดลง; A2DP ให้เสียงสเตอริโอคุณภาพสูงแต่ไม่มีไมค์

หากยังไม่ได้ ให้ตรวจสอบไมค์และแอปที่ใช้เสียงอยู่ รวมถึงสถานะ `systemctl --user status pipewire pipewire-pulse wireplumber` ก่อนลองใหม่

### แก้ปัญหาเล่นเสียงพูดไม่สำเร็จ

หากพบ `Sample format not supported` ในข้อความ ALSA ให้ลองรันแอปเวอร์ชันล่าสุด ซึ่งส่งเสียงออกเป็น PCM `int16` ที่ ALSA รองรับได้กว้างกว่า หากยังมีปัญหา ให้ตรวจสอบว่าเลือกอุปกรณ์เสียงออกถูกต้องใน Settings > Sound และตรวจรายการอุปกรณ์ด้วย `wpctl status`

### ทดสอบระบบ (Selftest)

ตรวจว่าระบบอ่านจอ OCR, ขยับเมาส์, พิมพ์คีย์บอร์ด และ AT-SPI2 Accessibility พร้อมหรือไม่:

```bash
./run_app.sh --selftest
```

การทดสอบจะเปิดหน้าต่างทดสอบของตัวเองกลางจอ และไม่แตะต้องหน้าต่างงานอื่นๆ ของคุณ

## ปรับแต่ง (ไฟล์ `.env`)

| อยากได้ | ตั้งค่า |
|---|---|
| เปลี่ยนชื่อที่ใช้เรียก | `WAKE_WORD=จาร์วิส` |
| ไม่ต้องเรียกชื่อก่อนสั่ง | `WAKE_WORD=off` |
| เสียงพูดไทย | `TTS_VOICE=th-TH-NiwatNeural` (หรือ `th-TH-PremwadeeNeural`) |
| ความเร็วเสียงพูด | `TTS_RATE=+15%` |
| ให้ Chrome เปิดโปรไฟล์ที่ต้องการ | `CHROME_PROFILE=Default` |
| ใช้ AI บนคลาวด์ | `LLM_MODE=cloud` และใส่ `GOOGLE_API_KEY` |
| ปิดหน้าจอ HUD (รันแบบเบื้องหลัง) | `HUD=off` |

ดูตัวเลือกทั้งหมดพร้อมคำอธิบายได้ที่ [`.env.example`](.env.example)

## ความปลอดภัยและความเป็นส่วนตัว

- **การถอดเสียงใช้คลาวด์** — ส่งเสียงแต่ละประโยคไปยัง Typhoon ASR API; อย่าใช้กับเสียงที่ไม่ต้องการส่งออกนอกเครื่อง
- **AI ในเครื่อง** — รองรับ Ollama (เช่น typhoon2, qwen2.5) ตอบคำถามโดยไม่ต้องต่อเน็ต
- **Chrome แยกโปรไฟล์** — เอเจนต์ท่องเว็บใช้โฟลเดอร์แยก (`.browser-profile`) ไม่แตะต้องรหัสผ่านหรือคุกกี้ส่วนตัวของคุณ
- **ไม่ทำเรื่องเสี่ยงแทนคุณ**: ไม่กดปุ่มลบ / สั่งซื้อ / จ่ายเงิน / Format / ลบไฟล์สำคัญ และไม่กรอกรหัสผ่านแทนคุณ

## ไฟล์ในโปรเจกต์

| ไฟล์ | หน้าที่ |
|---|---|
| `jarvis.py` | แกนหลัก: ฟังเสียง, Typhoon ASR API, ตัดสินใจด้วย Jev, ควบคุมระบบ และสังเคราะห์เสียงพูด |
| `computer_agent.py` | จับภาพหน้าจอ (GNOME D-Bus), OCR, AT-SPI2 Accessibility, คุมเมาส์และคีย์บอร์ด |
| `browser_agent.py` | ท่องเว็บด้วย Playwright บน Google Chrome |
| `hud.html` | ส่วนต่อประสาน GUI แบบโปร่งใส (GTK3 + WebKit2) |
| `selftest.py` | สคริปต์ทดสอบสิทธิ์และการคุมเครื่องอัตโนมัติ |
| `run_app.sh` | เชลล์สคริปต์เปิดรันจางวิทบน Ubuntu |
| [`docs/TECHNICAL.md`](docs/TECHNICAL.md) | รายละเอียดเชิงเทคนิค สถาปัตยกรรม และการวัดประสิทธิภาพ |
