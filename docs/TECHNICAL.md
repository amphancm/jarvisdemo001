# รายละเอียดเชิงเทคนิค — จางวิทบน NVIDIA Jetson Orin Nano และ Ubuntu

> สำหรับนักพัฒนาที่สนใจสถาปัตยกรรมภายใน · คู่มือการใช้งานทั่วไปอยู่ที่ [README](../README.md)

แพลตฟอร์มหลักที่ทดสอบคือ NVIDIA Jetson Orin Nano บน JetPack 7 / L4T R39 (Ubuntu 24.04, CUDA 13.2, cuDNN 9.20); รองรับ Ubuntu Desktop 26.04 (GNOME Wayland / X11) ด้วย ผู้ช่วยเสียงภาษาไทยทำงานแบบ **full duplex**: ฟังตลอดเวลา ไม่ต้องกดปุ่ม เรียก **"จางวิท"** แล้วคุยต่อเนื่องได้เหมือนเพื่อน
พูดแทรกได้ มีเสียงสังเคราะห์ภาษาไทยที่คมชัด มีหน้าจอ **J.A.R.V.I.S** โปร่งแสงลอยบนจอ (GTK3 + WebKit2) และทำงานในเครื่องเกือบทั้งหมด

```
"จางวิท วันนี้เหนื่อยจังเลย"                  → "เฮ้ย เหนื่อยมากเหรอ ..." (คุยต่อได้ 30 วิโดยไม่ต้องเรียกชื่อซ้ำ)
"จางวิท เปิดเบราว์เซอร์ให้หน่อย"              → เปิด Chrome / Firefox (รู้จักทุกแอปตาม .desktop ในเครื่อง)
"จางวิท หยุดเพลงแล้วเปิดสแล็ก"               → หยุดเพลง (MPRIS) + เปิด Slack (Jev แยกสองคำสั่งเอง)
"จางวิท ตั้งเสียงไว้ที่สามสิบห้า"               → ตั้งเสียง 35% ผ่าน PipeWire / WirePlumber
"จางวิท หาเพลงน้องเนยในยูทูบ เปิดให้ฟังหน่อย"   → เอเจนต์เปิด Chrome ค้นแล้วกดเล่นให้
"จางวิท ราคาทองวันนี้เท่าไหร่"                 → เป็นคำถามสด → ค้นเว็บให้ผ่าน Playwright
```

## สถาปัตยกรรมระบบ (Architecture)

```
ไมค์ (ฟังตลอดเวลา) ─► ตัดเสียงสะท้อน AEC (WebRTC ผ่าน livekit) ─► Silero VAD ตัดเป็นประโยค
   ─► ถอดเสียงไทยในเครื่อง: Faster-Whisper (CUDA int8_float16 บน Jetson, CUDA float16 บน GPU อื่น หรือ CPU int8)
   ─► ได้ยินคำปลุก "จางวิท" หรืออยู่ในช่วงสนทนาต่อเนื่องหรือไม่?
   ─► Jev (TypeSafe) ตัดสินใจแบบ Speculative Fan-out: ถามทุกมิติในครั้งเดียว
        category · compound · action · app (ทุกแอปจาก .desktop) · volume · chat
   ─► ลงมือปฏิบัติการ:
        - ระบบ Linux: GNOME D-Bus, PipeWire/WirePlumber (`wpctl`), MPRIS Playerctl, GSettings, loginctl
        - ท่องเว็บ: Playwright + Chromium / Chrome
        - คุมเครื่อง: AT-SPI2 Accessibility + xdotool / XTest
        - สนทนา: Ollama ในเครื่อง หรือ Gemini / OpenRouter
   ─► สังเคราะห์เสียงพูดตอบ: Edge TTS (th-TH-NiwatNeural) ถอดรหัส miniaudio เล่นผ่าน PipeWire
```

- PortAudio จะเลือก sample rate ที่ไมค์และลำโพงรองรับจริง แล้ว resample เข้า/ออก 16 kHz สำหรับ VAD, AEC และ STT เพื่อรองรับอุปกรณ์ ALSA ที่ไม่รับ 16 kHz โดยตรง
- **คุยต่อเนื่องแบบเพื่อน**: หลังเรียกชื่อแล้วคุยต่อได้ 30 วินาทีโดยไม่ต้องเรียกซ้ำ จำบริบท 6 รอบล่าสุด
- **ตอบสนองรวดเร็ว**: จบประโยคหลังเงียบ 0.55 วิ · Jev ~0.4 วิ · แคชเสียงสังเคราะห์ล่วงหน้าใน `.tts-cache/`
- **พูดแทรก (Barge-in)**: เมื่อผู้ใช้เริ่มพูดแทรก ระบบจะหยุดเสียงที่กำลังเล่นทันที
- **คำปลุก "จางวิท"**: รองรับคำที่โมเดลถอดเสียงอาจได้ยินเพี้ยนเล็กน้อย (น้อง จาง, ท่านจาง, น้องจ้าง) และรองรับการปิดคำปลุกด้วย `WAKE_WORD=off`
- **ท่องเว็บอัตโนมัติ**: ควบคุมเบราว์เซอร์ผ่าน Playwright โดยแยก Profile (`.browser-profile`) เพื่อความปลอดภัย
- **J.A.R.V.I.S HUD**: หน้าต่างโปร่งใส (Alpha channel) สร้างด้วย GTK3 + WebKit2 พร้อม WebGL/Canvas ring visualization

## การควบคุมระบบปฏิบัติการบน Ubuntu / JetPack

| การควบคุม | เครื่องมือที่ใช้ | คำอธิบาย |
|---|---|---|
| ระดับเสียง (Volume) | `wpctl` (WirePlumber) / `pactl` | รองรับ PipeWire แบบ native ปรับเสียงตามเปอร์เซ็นต์หรือปิดเสียง |
| ควบคุมเพลง (Media) | MPRIS 2.0 D-Bus / `playerctl` | เล่น, หยุด, ข้ามเพลง, ย้อนกลับ กับโปรแกรมเล่นสื่อที่รองรับ |
| โหมดมืด (Dark Mode) | `gsettings` | `org.gnome.desktop.interface color-scheme` ('prefer-dark' / 'default') |
| ล็อกหน้าจอ / พักเครื่อง | `loginctl` / `systemctl` | `loginctl lock-session`, `systemctl suspend` |
| รายชื่อและการเปิดแอป | XDG `.desktop` specifications | สแกน `/usr/share/applications` และ `~/.local/share/applications` |
| จับภาพหน้าจอ | GNOME Shell Screenshot DBus | `org.gnome.Shell.Screenshot` หรือ `gnome-screenshot` / `grim` / `scrot` |
| การอ่านส่วนติดต่อผู้ใช้ | AT-SPI2 (`gir1.2-atspi-2.0`) | ดึง Accessibility Tree เพื่อคลิกปุ่ม อ่านข้อความ และเข้าถึงเมนู |

## Jetson Orin Nano: CUDA สำหรับ Faster-Whisper

wheel CTranslate2 แบบ aarch64 ที่ติดตั้งจาก PyPI เป็น CPU-only แม้ JetPack จะติดตั้ง CUDA/cuDNN ไว้แล้ว จึงต้อง build CTranslate2 จาก source เพื่อเปิด CUDA การ build ที่ตรวจสอบบน Orin Nano R39 ใช้ CTranslate2 v4.9.0, CUDA architecture 8.7 (SM 87), `WITH_CUDA=ON`, `WITH_CUDNN=ON` และ OpenMP runtime ของ compiler

หลังติดตั้ง system packages และ `requirements.txt` ตาม [คู่มือ Jetson](../README.md#ติดตั้งบน-jetson-orin-nano-jetpack-7--r39) ให้รัน:

```bash
./scripts/install_jetson_ctranslate2_cuda.sh
```

สคริปต์ build แบบหนึ่งงานเพื่อลด RAM, เก็บ C++ library ไว้ใน `.venv/ctranslate2`, สร้าง Python wheel ใน directory ชั่วคราว และตรวจว่า CUDA ใช้งานได้ก่อนติดตั้ง wheel ลง `.venv` การ build ใช้ CUDA/cuDNN ที่มากับ JetPack; ไม่แก้ไข system Python หรือใช้ `sudo` ในสคริปต์

เมื่อ `WHISPER_DEVICE=auto` ระบบเลือก CUDA ถ้า CTranslate2 ตรวจพบ GPU มิฉะนั้นจะแจ้งเตือนและใช้ CPU ตั้ง `WHISPER_DEVICE=cuda` เพื่อกำหนดให้การเริ่มต้นล้มเหลวเมื่อ GPU ใช้ไม่ได้ ค่า `WHISPER_COMPUTE_TYPE=auto` เลือก `int8_float16` บน Jetson, `float16` บน CUDA อื่น และ `int8` บน CPU; สามารถตั้ง precision เองใน `.env` ได้

หากติดตั้ง `requirements.txt` ใหม่ pip อาจเขียนทับ wheel ที่ build ไว้ด้วย wheel CPU-only ให้รันสคริปต์ Jetson ซ้ำหลังติดตั้ง requirements ทุกครั้ง

## การตั้งค่า Environment (`.env`)

ดูคำอธิบายเต็มใน [`.env.example`](../.env.example)

Typhoon Whisper รุ่น Hugging Face เป็น Transformers checkpoint ที่ Faster-Whisper โหลดตรงๆ ไม่ได้
แปลงบนเครื่องที่มี `ct2-transformers-converter`, PyTorch และ Transformers ด้วย `scripts/convert_typhoon_whisper_for_jetson.sh`
สคริปต์สร้าง `models/typhoon-whisper-large-v3-ct2` โดย quantize เป็น `int8_float16`; คัดลอกโฟลเดอร์นี้ไปยัง Jetson
หากแปลงบนเครื่องอื่น ค่า `WHISPER_COMPUTE_TYPE=auto` จะใช้ `int8_float16` เมื่อ CUDA ของ Jetson รองรับ

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `TYPESAFE_API_KEY` | – (**จำเป็น**) | API Key สำหรับ Jev decision routing |
| `LLM_MODE` | `local` | `local` = Ollama ในเครื่อง, `cloud` = Gemini หรือ OpenRouter |
| `OLLAMA_MODEL` | `typhoon2:latest` | โมเดลภาษาไทยใน Ollama |
| `STT_ENGINE` | `whisper` | ถอดเสียงด้วย Faster-Whisper |
| `WHISPER_DEVICE` | `auto` | `auto` เลือก CUDA เมื่อ CTranslate2 รองรับ, หรือกำหนด `cuda` / `cpu` |
| `WHISPER_COMPUTE_TYPE` | `auto` | `auto` เลือก Jetson CUDA `int8_float16`, CUDA อื่น `float16`, CPU `int8`; ชนิดที่ไม่รองรับจะแจ้ง error |
| `FASTER_WHISPER_MODEL` | `typhoon-ai/typhoon-whisper-large-v3` | โมเดลถอดเสียงภาษาไทยจาก Hugging Face; ต้องแปลงเป็น CTranslate2 ก่อนใช้งาน |
| `TTS_VOICE` | `th-TH-NiwatNeural` | เสียงภาษาไทยของ Edge TTS |
| `SPEAKER_DEVICE` | `auto` | เลือกอุปกรณ์เล่นเสียง; เลือก PipeWire ก่อนเพื่อตามเอาต์พุตเริ่มต้นของระบบ (เช่น HDMI) หรือระบุชื่อบางส่วน/เลขอุปกรณ์ |
| `MIC_DEVICE` | `auto` | เลือกอุปกรณ์รับเสียง; เลือก PipeWire ก่อนเพื่อใช้ไมค์ระบบ เช่น Bluetooth หรือระบุชื่อบางส่วน/เลขอุปกรณ์ |
| `WAKE_WORD` | `จางวิท` | คำปลุกระบบ (`off` เพื่อฟังทุกคำพูด) |
| `CONF_MIN` | `0.65` | ระดับความเชื่อมั่นขั้นต่ำของ Jev |
| `HUD` | `on` | หน้าจอแสดงสถานะ HUD (`off` สำหรับรันแบบ console) |

## การทดสอบระบบ (Selftest)

รันคำสั่งทดสอบการควบคุมเครื่อง:
```bash
./run_app.sh --selftest
```
โปรแกรมจะตรวจสอบ:
1. การเชื่อมต่อ AT-SPI2 Accessibility bus
2. กลไกการจับภาพหน้าจอ (Screen capture capability)
3. เครื่องมือ OCR (Tesseract) และการอ่านข้อความ
4. การสังเคราะห์การกดคีย์บอร์ดและการคลิกเมาส์
5. หากไม่มีหน้าต่าง GUI ต่ออยู่ (เช่น Headless / Sandbox) ระบบจะรันการตรวจสอบระบบแบบ Headless และบันทึกผลลง `logs/selftest.log` โดยไม่แครช
