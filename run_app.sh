#!/usr/bin/env bash
# จางวิท (Jarvis) — Thai Voice & Automation Assistant บน Raspberry Pi OS / Ubuntu
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

# ตรวจสอบแพ็กเกจแกนหลักสำหรับเสียง (numpy, sounddevice, edge-tts)
if ! "$PYTHON" -c "import importlib.util, numpy, requests, edge_tts; assert importlib.util.find_spec('sounddevice')" >/dev/null 2>&1; then
    echo "⚠️  ตรวจพบว่ายังไม่ได้ติดตั้งแพ็กเกจ Python ที่จำเป็น (เช่น numpy, sounddevice, edge-tts)"
    if [ ! -x ".venv/bin/python3" ]; then
        echo "📦 กำลังสร้าง Python virtual environment (.venv)..."
        if ! python3 -m venv --system-site-packages .venv; then
            echo ""
            echo "❌ สร้าง virtual environment ไม่สำเร็จ"
            echo "กรุณาติดตั้ง python3-venv แล้วลองอีกครั้ง:"
            echo ""
            echo "    sudo apt update && sudo apt install -y python3-venv python3-pip libportaudio2 ffmpeg"
            echo ""
            exit 1
        fi
    fi

    if [ -x ".venv/bin/python3" ]; then
        PYTHON=".venv/bin/python3"
        echo "📦 กำลังติดตั้งแพ็กเกจจาก requirements.txt ใน .venv..."
        "$PYTHON" -m pip install -r requirements.txt
    else
        echo ""
        echo "❌ ไม่พบ Python ใน virtual environment (.venv)"
        echo "กรุณารันคำสั่งนี้ในเทอร์มินัลเพื่อติดตั้ง:"
        echo ""
        echo "    sudo apt update && sudo apt install -y python3-venv python3-pip libportaudio2 ffmpeg"
        echo "    python3 -m venv --system-site-packages .venv"
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
