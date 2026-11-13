# รายละเอียดเชิงเทคนิค — จางวิท (Jarvis ไทย) บน Raspberry Pi OS 64-bit และ Ubuntu

> สำหรับนักพัฒนาที่สนใจสถาปัตยกรรมภายใน · คู่มือการใช้งานทั่วไปอยู่ที่ [README](../README.md)

ผู้ช่วยเสียงภาษาไทยบน Raspberry Pi OS 64-bit Desktop (X11) และ Ubuntu แบบ **full duplex**: ฟังตลอดเวลา ไม่ต้องกดปุ่ม เรียก **"จางวิท"** แล้วคุยต่อเนื่องได้เหมือนเพื่อน
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
   ─► ส่งเสียงประโยคเป็น WAV ไปถอดเสียงผ่าน Typhoon ASR API (`typhoon-asr-realtime`)
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

- **คุยต่อเนื่องแบบเพื่อน**: หลังเรียกชื่อแล้วคุยต่อได้ 30 วินาทีโดยไม่ต้องเรียกซ้ำ จำบริบท 6 รอบล่าสุด
- **ตอบสนองรวดเร็ว**: จบประโยคหลังเงียบ 0.55 วิ · Jev ~0.4 วิ · แคชเสียงสังเคราะห์ล่วงหน้าใน `.tts-cache/`
- **พูดแทรก (Barge-in)**: เมื่อผู้ใช้เริ่มพูดแทรก ระบบจะหยุดเสียงที่กำลังเล่นทันที
- **คำปลุก "จางวิท"**: รองรับคำที่โมเดลถอดเสียงอาจได้ยินเพี้ยนเล็กน้อย (น้อง จาง, ท่านจาง, น้องจ้าง) และรองรับการปิดคำปลุกด้วย `WAKE_WORD=off`
- **ท่องเว็บอัตโนมัติ**: ควบคุมเบราว์เซอร์ผ่าน Playwright โดยแยก Profile (`.browser-profile`) เพื่อความปลอดภัย
- **J.A.R.V.I.S HUD**: หน้าต่างโปร่งใส (Alpha channel) สร้างด้วย GTK3 + WebKit2 พร้อม WebGL/Canvas ring visualization

## การควบคุมระบบปฏิบัติการบน Linux

| การควบคุม | เครื่องมือที่ใช้ | คำอธิบาย |
|---|---|---|
| ระดับเสียง (Volume) | `wpctl` (WirePlumber) / `pactl` | รองรับ PipeWire แบบ native ปรับเสียงตามเปอร์เซ็นต์หรือปิดเสียง |
| ควบคุมเพลง (Media) | MPRIS 2.0 D-Bus / `playerctl` | เล่น, หยุด, ข้ามเพลง, ย้อนกลับ กับโปรแกรมเล่นสื่อที่รองรับ |
| โหมดมืด (Dark Mode) | `gsettings` | `org.gnome.desktop.interface color-scheme` ('prefer-dark' / 'default') |
| ล็อกหน้าจอ / พักเครื่อง | `loginctl` / `systemctl` | `loginctl lock-session`, `systemctl suspend` |
| รายชื่อและการเปิดแอป | XDG `.desktop` specifications | สแกน `/usr/share/applications` และ `~/.local/share/applications` |
| จับภาพหน้าจอ | GNOME Shell Screenshot DBus | `org.gnome.Shell.Screenshot` หรือ `gnome-screenshot` / `grim` / `scrot` |
| การอ่านส่วนติดต่อผู้ใช้ | AT-SPI2 (`gir1.2-atspi-2.0`) | ดึง Accessibility Tree เพื่อคลิกปุ่ม อ่านข้อความ และเข้าถึงเมนู |

## การตั้งค่า Environment (`.env`)

ดูคำอธิบายเต็มใน [`.env.example`](../.env.example)

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `TYPESAFE_API_KEY` | – (**จำเป็น**) | API Key สำหรับ Jev decision routing |
| `TYPHOON_API_KEY` | – (**จำเป็นสำหรับเสียง**) | API Key สำหรับ Typhoon ASR; เสียงแต่ละประโยคจะถูกส่งไปยัง API |
| `TYPHOON_ASR_MODEL` | `typhoon-asr-realtime` | โมเดลถอดเสียงของ Typhoon |
| `LLM_MODE` | `local` | `local` = Ollama ในเครื่อง, `cloud` = Gemini หรือ OpenRouter |
| `OLLAMA_MODEL` | `typhoon2:latest` | โมเดลภาษาไทยใน Ollama |
| `TTS_VOICE` | `th-TH-NiwatNeural` | เสียงภาษาไทยของ Edge TTS |
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
