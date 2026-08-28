#!/usr/bin/env bash
# Raspberry Pi deployment helper script.
# Transfer this entire project directory to the Pi and run this script.
#
# Prerequisites on the Pi:
#   - Raspberry Pi OS (64-bit recommended)
#   - Python 3.11+
#   - A USB camera connected and accessible at /dev/video0
#
# Usage:
#   chmod +x scripts/deploy-pi.sh
#   ./scripts/deploy-pi.sh
#
# This script:
#   1. Creates a virtual environment
#   2. Installs the project with OpenCV vision support
#   3. Downloads a Haar Cascade model for face detection
#   4. Runs the camera evaluation harness
#   5. Starts the Flask server for manual kiosk testing

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=== Lobby Attendance - Raspberry Pi Deployment ==="
echo "Project: $PROJECT_DIR"
echo "Date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# Step 1: Virtual environment
if [ ! -d ".venv" ]; then
    echo "[1/5] Creating virtual environment..."
    python3 -m venv .venv
else
    echo "[1/5] Virtual environment exists."
fi

source .venv/bin/activate
python -m pip install --upgrade pip --quiet

# Step 2: Install the project
echo "[2/5] Installing project with vision support..."
python -m pip install -e ".[dev,vision]" --quiet

# Step 3: Download Haar Cascade model if not present
MODEL_DIR="$PROJECT_DIR/models"
MODEL_PATH="$MODEL_DIR/haarcascade_frontalface_default.xml"

if [ ! -f "$MODEL_PATH" ]; then
    echo "[3/5] Downloading Haar Cascade face detection model..."
    mkdir -p "$MODEL_DIR"
    curl -sSL -o "$MODEL_PATH" \
        "https://raw.githubusercontent.com/opencv/opencv/4.10.0/data/haarcascades/haarcascade_frontalface_default.xml"
    echo "  Model saved to: $MODEL_PATH"
    echo "  SHA-256: $(sha256sum "$MODEL_PATH" | cut -d' ' -f1)"
else
    echo "[3/5] Model already present: $MODEL_PATH"
fi

MODEL_SHA256=$(sha256sum "$MODEL_PATH" | cut -d' ' -f1)

# Step 4: Run evaluation harness
echo "[4/5] Running camera and provider evaluation..."
echo ""

python -m lobby_attendance evaluate \
    --camera-index 0 \
    --model-path "$MODEL_PATH" \
    --model-directory "$MODEL_DIR" \
    --model-sha256 "$MODEL_SHA256" \
    --iterations 20 \
    --interaction-timeout 2.0 \
    --output "data/evaluation-report.json"

echo ""

# Step 5: Configuration and startup instructions
echo "[5/5] Setup complete. To start the server manually:"
echo ""
echo "  source .venv/bin/activate"
echo ""
echo "  export LOBBY_ATTENDANCE_DATABASE_PATH=data/pi-attendance.sqlite3"
echo "  export LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_KEY=\$(python -c 'import secrets; print(secrets.token_hex(32))')"
echo "  export LOBBY_ATTENDANCE_STORAGE_ENCRYPTION_REQUIRED=true"
echo "  export LOBBY_ATTENDANCE_ADMIN_TOKEN='replace-with-a-long-random-token'"
echo "  export LOBBY_ATTENDANCE_KIOSK_TOKEN='replace-with-a-long-random-kiosk-token'"
echo "  export LOBBY_ATTENDANCE_ADMIN_ROLES='enrollment-administrator,attendance-administrator,auditor,system-operator'"
echo "  export LOBBY_ATTENDANCE_COMPLIANCE_APPROVED=true"
echo "  export LOBBY_ATTENDANCE_DEVELOPMENT_MOCK_VISION=false"
echo "  export LOBBY_ATTENDANCE_VISION_MODEL_PATH=$MODEL_PATH"
echo "  export LOBBY_ATTENDANCE_VISION_MODEL_DIRECTORY=$MODEL_DIR"
echo "  export LOBBY_ATTENDANCE_VISION_MODEL_SHA256=$MODEL_SHA256"
echo "  export LOBBY_ATTENDANCE_CAMERA_INDEX=0"
echo ""
echo "  python -m flask --app lobby_attendance.api:create_app run --host 0.0.0.0 --port 5000"
echo ""
echo "  Then open http://<pi-ip>:5000/kiosk from a browser on the same network."
echo ""
echo "=== IMPORTANT ==="
echo "  - COMPLIANCE_APPROVED=true is a technical gate only, not privacy/legal approval."
echo "  - The Haar Cascade model is a demonstration detector, not an evaluated biometric."
echo "  - This does NOT claim pilot readiness, PAD evidence, or accuracy validation."
echo "  - Review data/evaluation-report.json for camera/latency evidence."
echo "================="
