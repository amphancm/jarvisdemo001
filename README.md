<p align="center">
  <img src="docs/images/banner.png" alt="จางวิท — J.A.R.V.I.S ภาษาไทยบน NVIDIA Jetson Orin Nano และ Ubuntu" width="100%">
</p>

# จางวิท — ผู้ช่วยเสียงภาษาไทยบน NVIDIA Jetson Orin Nano

จางวิทคือผู้ช่วยเสียงภาษาไทยแบบ **J.A.R.V.I.S** รองรับ **NVIDIA Jetson Orin Nano บน JetPack 7 / L4T R39** (Ubuntu 24.04) และ Ubuntu Desktop
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
2. **ถอดเสียงเป็นข้อความ** — ใช้ Faster-Whisper บน GPU (CUDA) หรือ CPU ในเครื่อง แม่นยำและไม่ส่งเสียงออกนอกเครื่อง
3. **ตัดสินใจด้วย Jev** — Jev คือ AI ตัดสินใจของ [TypeSafe](https://typesafe.ai) ที่ **เลือกคำตอบจากตัวเลือก**
   (เช่น "เป็นคำสั่งไหม" "เปิดแอปไหน" "คุยเล่นแบบไหน") ถามทุกอย่างในครั้งเดียว ใช้เวลา ~0.4 วินาที
   และบอกด้วยว่ามั่นใจแค่ไหน — **ถ้าไม่มั่นใจ จางวิทจะถามใหม่ ไม่เดาสุ่ม**
4. **ลงมือทำ** — สั่งระบบ Linux (GNOME D-Bus, PipeWire, MPRIS, `gsettings`) / ท่องเว็บด้วย Playwright / คุมเมาส์และคีย์บอร์ดด้วย AT-SPI2
5. **ตอบด้วยเสียง** — สังเคราะห์เสียงพูดภาษาไทยผ่าน Edge TTS (Niwat/Premwadee Neural) คุณภาพสูงและพูดเป็นธรรมชาติ

## หน้าจอ J.A.R.V.I.S

<p align="center"><img src="docs/images/states.png" alt="หน้าจอ J.A.R.V.I.S ในแต่ละสถานะ" width="100%"></p>

ลอยอยู่บนหน้าจอ Ubuntu ขยับตามเสียง และเปลี่ยนสีตามสิ่งที่จางวิทกำลังทำ
**ลากย้ายได้ · ดับเบิลคลิก = หยุด/เริ่มฟัง · คลิกขวา = เมนู** และมีไอคอนบน System Tray (AppIndicator) ให้เปิด/ปิดการฟัง

## แพลตฟอร์มและสิ่งที่ต้องมี

- **แพลตฟอร์มหลักที่ทดสอบ**: Jetson Orin Nano, JetPack 7 / L4T R39, Ubuntu 24.04, CUDA 13.2, cuDNN 9.20
- **แพลตฟอร์ม Desktop**: Ubuntu 26.04 หรือ Linux x86_64 ที่ใช้ GNOME Wayland / X11
- **Python 3.10 ขึ้นไป**
- **คีย์ของ TypeSafe** (สำหรับ Jev) สมัครที่ [typesafe.ai](https://typesafe.ai)
- **คีย์ของ Google Gemini หรือ OpenRouter** (หรือใช้ Ollama รันโมเดลในเครื่อง)
- **Google Chrome หรือ Chromium** (ไม่บังคับ; ใช้กับเอเจนต์ค้นเว็บ)

## ติดตั้งบน Jetson Orin Nano (JetPack 7 / R39)

### 1. ติดตั้งแพ็กเกจระบบ

```bash
sudo apt update
sudo apt install -y build-essential cmake git python3-dev python3-pip python3-venv \
    python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-atspi-2.0 \
    tesseract-ocr tesseract-ocr-tha xdotool wireplumber libportaudio2 ffmpeg
```

JetPack มี CUDA และ cuDNN มาให้แล้ว ไม่ต้องติดตั้ง CUDA แยก

### 2. ติดตั้ง Python dependencies

```bash
git clone https://github.com/jaturapornchai/jarvisdemo001.git
cd jarvisdemo001
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
```

### 3. Build CTranslate2 สำหรับ CUDA บน Orin

wheel aarch64 ปกติจาก PyPI เป็น CPU-only จึงต้อง build CTranslate2 ที่เปิด CUDA:

```bash
./scripts/install_jetson_ctranslate2_cuda.sh
```

สคริปต์ build สำหรับ GPU architecture SM 8.7, จำกัดงานคอมไพล์ไว้หนึ่งงานเพื่อลดการใช้ RAM และทดสอบว่า wheel พบ CUDA ก่อนแทนที่แพ็กเกจใน `.venv` ไฟล์ไลบรารีจะอยู่ที่ `.venv/ctranslate2`; สคริปต์ build ไม่ใช้ `sudo` และลบ source/build ชั่วคราวเมื่อเสร็จ

### 4. ตั้งค่า API keys และเริ่มใช้งาน

```bash
cp .env.example .env
```

เปิด `.env` แล้วใส่คีย์:
- `TYPESAFE_API_KEY=...`
- `GOOGLE_API_KEY=...` หรือ `OPENROUTER_API_KEY=...` (เมื่อต้องการใช้โมเดลคลาวด์)

```bash
./run_app.sh
```

ค่าปริยายใช้ Typhoon Whisper ที่แปลงเป็น CTranslate2 และเลือก CUDA `int8_float16` บน Jetson เพื่อลดการใช้หน่วยความจำ หากไม่มี CUDA-enabled CTranslate2 ระบบจะแจ้งเตือนและกลับไปใช้ CPU; ตั้ง `WHISPER_DEVICE=cuda` ใน `.env` เพื่อบังคับใช้ GPU และให้เริ่มต้นล้มเหลวเมื่อไม่พบ CUDA จางวิทจะเปิด HUD; ปิดด้วย **Ctrl+C** หรือเมนู **ออก** ที่ System Tray

### ทดสอบระบบ (Selftest)

ตรวจว่าระบบอ่านจอ OCR, ขยับเมาส์, พิมพ์คีย์บอร์ด และ AT-SPI2 Accessibility พร้อมหรือไม่:

```bash
./run_app.sh --selftest
```

การทดสอบจะเปิดหน้าต่างทดสอบของตัวเองกลางจอ และไม่แตะต้องหน้าต่างงานอื่นๆ ของคุณ

## ติดตั้งบน Ubuntu Desktop 26.04

สำหรับเครื่อง Desktop ที่ไม่ใช่ Jetson ให้ติดตั้งแพ็กเกจระบบ:

```bash
sudo apt update
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 gir1.2-atspi-2.0 \
    tesseract-ocr tesseract-ocr-tha xdotool wireplumber libportaudio2 ffmpeg
```

จากนั้นสร้าง environment และติดตั้ง dependencies:

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
./run_app.sh
```

หากติดตั้ง `requirements.txt` ใหม่บน Jetson ให้รันสคริปต์ CTranslate2 CUDA ซ้ำ เพราะ pip อาจแทนที่ wheel ที่คอมไพล์เองด้วย wheel CPU-only

## ปรับแต่ง (ไฟล์ `.env`)

| อยากได้ | ตั้งค่า |
|---|---|
| เปลี่ยนชื่อที่ใช้เรียก | `WAKE_WORD=จาร์วิส` |
| เลือกลำโพง | `SPEAKER_DEVICE=auto` (ค่าเริ่มต้น เลือก `pipewire` ตามเอาต์พุตเริ่มต้นของระบบ เช่น HDMI ที่ตั้งใน Ubuntu Settings) หรือชื่อบางส่วน/เลขอุปกรณ์จากรายการ PortAudio |
| เลือกไมโครโฟน | `MIC_DEVICE=auto` หรือชื่อบางส่วน/เลขอุปกรณ์จากรายการ PortAudio (ใช้ `pipewire` สำหรับไมค์ระบบ เช่น Bluetooth) |
| ไม่ต้องเรียกชื่อก่อนสั่ง | `WAKE_WORD=off` |
| เสียงพูดไทย | `TTS_VOICE=th-TH-NiwatNeural` (หรือ `th-TH-PremwadeeNeural`) |
| ความเร็วเสียงพูด | `TTS_RATE=+15%` |
| ให้ Chrome เปิดโปรไฟล์ที่ต้องการ | `CHROME_PROFILE=Default` |
| ใช้ AI บนคลาวด์ | `LLM_MODE=cloud` และใส่ `GOOGLE_API_KEY` |
| ปิดหน้าจอ HUD (รันแบบเบื้องหลัง) | `HUD=off` |
| เลือกอุปกรณ์ถอดเสียง | `WHISPER_DEVICE=auto`, `cuda` หรือ `cpu` |
| เปลี่ยน precision ถอดเสียง | `WHISPER_COMPUTE_TYPE=auto`, `int8_float16`, `float16`, `int8` หรือ `float32` |
| เปลี่ยนโมเดลถอดเสียง | `FASTER_WHISPER_MODEL=typhoon-ai/typhoon-whisper-large-v3` |

ดูตัวเลือกทั้งหมดพร้อมคำอธิบายได้ที่ [`.env.example`](.env.example)

Typhoon Whisper บน Hugging Face เป็นโมเดล Transformers จึงต้องแปลงเป็น CTranslate2 ก่อนใช้งานกับ Faster-Whisper
รัน `scripts/convert_typhoon_whisper_for_jetson.sh` ในเครื่องที่มี `ct2-transformers-converter`, PyTorch และ Transformers
จากนั้นคัดลอกโฟลเดอร์ `models/typhoon-whisper-large-v3-ct2` มายังเครื่อง Jetson หากแปลงโมเดลบนเครื่องอื่น
สคริปต์จะ quantize เป็น `int8_float16` ซึ่งเหมาะกับ CUDA บน Jetson Orin Nano; ค่า `WHISPER_COMPUTE_TYPE=auto` จะเลือกชนิดนี้เมื่อรองรับ

## ความปลอดภัยและความเป็นส่วนตัว

- **เสียงของคุณไม่ถูกส่งออกจากเครื่อง** — ถอดเสียงในเครื่องด้วย Faster-Whisper ส่งเฉพาะข้อความสั้นๆ ให้ Jev
- **AI ในเครื่อง** — รองรับ Ollama (เช่น typhoon2, qwen2.5) ตอบคำถามโดยไม่ต้องต่อเน็ต
- **Chrome แยกโปรไฟล์** — เอเจนต์ท่องเว็บใช้โฟลเดอร์แยก (`.browser-profile`) ไม่แตะต้องรหัสผ่านหรือคุกกี้ส่วนตัวของคุณ
- **ไม่ทำเรื่องเสี่ยงแทนคุณ**: ไม่กดปุ่มลบ / สั่งซื้อ / จ่ายเงิน / Format / ลบไฟล์สำคัญ และไม่กรอกรหัสผ่านแทนคุณ

## ไฟล์ในโปรเจกต์

| ไฟล์ | หน้าที่ |
|---|---|
| `jarvis.py` | แกนหลัก: ฟังเสียง, Faster-Whisper, ตัดสินใจด้วย Jev, ควบคุมระบบ และสังเคราะห์เสียงพูด |
| `computer_agent.py` | จับภาพหน้าจอ (GNOME D-Bus), OCR, AT-SPI2 Accessibility, คุมเมาส์และคีย์บอร์ด |
| `browser_agent.py` | ท่องเว็บด้วย Playwright บน Google Chrome |
| `hud.html` | ส่วนต่อประสาน GUI แบบโปร่งใส (GTK3 + WebKit2) |
| `selftest.py` | สคริปต์ทดสอบสิทธิ์และการคุมเครื่องอัตโนมัติ |
| `run_app.sh` | เชลล์สคริปต์เปิดรันจางวิทบน Ubuntu |
| `scripts/install_jetson_ctranslate2_cuda.sh` | Build และติดตั้ง CTranslate2 CUDA สำหรับ Jetson Orin Nano |
| [`docs/TECHNICAL.md`](docs/TECHNICAL.md) | รายละเอียดเชิงเทคนิค สถาปัตยกรรม และการวัดประสิทธิภาพ |
