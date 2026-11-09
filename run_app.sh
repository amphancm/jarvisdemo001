#!/usr/bin/env bash
# จางวิท (Jarvis) — Thai Voice & Automation Assistant บน Ubuntu 26.04 LTS
# รันโปรแกรมในเทอร์มินัลนี้ (กด Ctrl+C เพื่อหยุดการทำงานอย่างปลอดภัย)

set -e
cd "$(dirname "$0")"

mkdir -p logs

# เลือก Python จาก .venv หากมีอยู่ มิฉะนั้นใช้ python3 ของระบบ
if [ -x ".venv/bin/python3" ]; then
    PYTHON=".venv/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="python3"
else
    echo "❌ ไม่พบ python3 ในระบบ กรุณาติดตั้ง python3"
    exit 1
fi

export PYTHONUNBUFFERED=1

# หากระบุ --selftest ให้รัน selftest.py ทันที
if [ "$1" = "--selftest" ]; then
    shift
    echo "🧪 กำลังเริ่มการทดสอบระบบ (Selftest)..."
    exec "$PYTHON" selftest.py "$@"
fi

# ตรวจสอบแพ็กเกจถอดเสียงและระบบเสียง (faster-whisper, sounddevice, edge-tts)
if ! "$PYTHON" -c "import faster_whisper, sounddevice, edge_tts" >/dev/null 2>&1; then
    echo "⚠️  ตรวจพบว่ายังไม่ได้ติดตั้งแพ็กเกจ Python ที่จำเป็น (เช่น faster-whisper, sounddevice, edge-tts)"
    if [ -x ".venv/bin/pip" ]; then
        echo "📦 กำลังติดตั้งแพ็กเกจจาก requirements.txt อัตโนมัติด้วย .venv/bin/pip..."
        .venv/bin/pip install -r requirements.txt
    elif command -v pip3 >/dev/null 2>&1; then
        echo "📦 กำลังติดตั้งแพ็กเกจจาก requirements.txt ด้วย pip3..."
        pip3 install -r requirements.txt
    else
        echo ""
        echo "❌ ยังไม่มี pip และแพ็กเกจที่จำเป็นบนระบบ Ubuntu 26.04"
        echo "กรุณารัน 3 คำสั่งนี้ในเทอร์มินัลเพื่อติดตั้ง:"
        echo ""
        echo "    sudo apt update && sudo apt install -y python3-pip python3-venv libportaudio2 ffmpeg"
        echo "    rm -rf .venv && python3 -m venv --system-site-packages .venv"
        echo "    .venv/bin/pip install -r requirements.txt"
        echo ""
        exit 1
    fi
fi

# จัดการสัญญาณหยุดโปรแกรมอย่างนุ่มนวล
JARVIS_PID=""
cleanup() {
    echo ""
    echo "👋 ได้รับสัญญาณหยุด กำลังปิดจางวิท..."
    if [ -n "$JARVIS_PID" ] && kill -0 "$JARVIS_PID" 2>/dev/null; then
        kill -TERM "$JARVIS_PID" 2>/dev/null || true
        wait "$JARVIS_PID" 2>/dev/null || true
    fi
    echo "👋 ปิดจางวิทเรียบร้อยแล้ว"
    exit 0
}
trap cleanup INT TERM HUP

# รันจางวิทและส่งต่อพารามิเตอร์ทั้งหมด (เช่น --text, --eval, --wav, --mic)
"$PYTHON" jarvis.py "$@" &
JARVIS_PID=$!

wait "$JARVIS_PID"
