#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv/bin/python"
PIP="$ROOT/.venv/bin/pip"
CTRANSLATE2_ROOT="$ROOT/.venv/ctranslate2"
CMAKE="${CMAKE:-cmake}"

if [ "$(uname -m)" != "aarch64" ]; then
    echo "This installer targets Jetson aarch64 only." >&2
    exit 1
fi

if [ ! -x "$PYTHON" ] || [ ! -x "$PIP" ]; then
    echo "Create the project .venv and install requirements.txt first." >&2
    exit 1
fi

for tool in "$CMAKE" git nvcc; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "Missing build tool: $tool (install cmake, git, and the JetPack CUDA toolkit)." >&2
        exit 1
    fi
done

PYTHON_INCLUDE="$("$PYTHON" -c 'import sysconfig; print(sysconfig.get_config_var("INCLUDEPY") or "")')"
if [ -z "$PYTHON_INCLUDE" ] || [ ! -f "$PYTHON_INCLUDE/Python.h" ]; then
    echo "Python development headers are missing; install python3-dev for this Python version." >&2
    exit 1
fi

BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/jarvis-ctranslate2.XXXXXX")"
trap 'rm -rf -- "$BUILD_DIR"' EXIT

git clone --depth 1 --branch v4.9.0 --recurse-submodules \
    https://github.com/OpenNMT/CTranslate2.git "$BUILD_DIR/source"

"$CMAKE" -S "$BUILD_DIR/source" -B "$BUILD_DIR/build" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$CTRANSLATE2_ROOT" \
    -DCMAKE_CUDA_ARCHITECTURES=87 \
    -DWITH_CUDA=ON \
    -DWITH_CUDNN=ON \
    -DWITH_MKL=OFF \
    -DOPENMP_RUNTIME=COMP \
    -DBUILD_CLI=OFF \
    -DBUILD_TESTS=OFF
"$CMAKE" --build "$BUILD_DIR/build" --parallel 1
"$CMAKE" --install "$BUILD_DIR/build"

"$PYTHON" -m venv "$BUILD_DIR/python-build-venv"
BUILD_PYTHON="$BUILD_DIR/python-build-venv/bin/python"
"$BUILD_PYTHON" -m pip install pybind11==2.13.6 setuptools wheel

(
    cd "$BUILD_DIR/source/python"
    CTRANSLATE2_ROOT="$CTRANSLATE2_ROOT" \
        CMAKE_BUILD_PARALLEL_LEVEL=1 \
        "$BUILD_PYTHON" setup.py bdist_wheel
)

WHEEL="$(find "$BUILD_DIR/source/python/dist" -maxdepth 1 -type f -name 'ctranslate2*.whl' -print -quit)"
if [ -z "$WHEEL" ]; then
    echo "CTranslate2 build did not produce a Python wheel." >&2
    exit 1
fi

TEST_SITE="$BUILD_DIR/testsite"
"$PIP" install --no-deps --target "$TEST_SITE" "$WHEEL"
PYTHONPATH="$TEST_SITE" "$PYTHON" - <<'PY'
import ctranslate2

devices = ctranslate2.get_cuda_device_count()
print(f"Test CTranslate2 {ctranslate2.__version__}: CUDA devices={devices}")
if devices < 1:
    raise SystemExit("The test wheel does not detect a CUDA device; active CTranslate2 was not replaced.")
print("CUDA compute types:", ", ".join(sorted(ctranslate2.get_supported_compute_types("cuda"))))
PY

"$PIP" install --no-deps --force-reinstall "$WHEEL"
echo "CUDA-enabled CTranslate2 installed in the project virtual environment."
