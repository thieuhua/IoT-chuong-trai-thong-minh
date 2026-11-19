# Windows / PowerShell. Run `just` to list commands; use separate terminals for servers.
# Examples: just up | just backend --reload | just test-backend -k config | just ota esp32-ID
# Override interpreters when needed: just --set backend_python C:/path/python.exe backend
# Windows PowerShell 5.1 ships with Windows (pwsh 7 is not required). Bypass applies to this
# process only, so the repo's .ps1 tools run without changing the machine execution policy.
set shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]
set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]

compose := "docker compose -f deployment/compose.yaml --profile app"

python := justfile_directory() / ".venv/Scripts/python.exe"
backend_python := justfile_directory() / "backend/.venv/Scripts/python.exe"
firmware_python := justfile_directory() / "firmware/.venv/Scripts/python.exe"

# List available commands (also: just --list).
default:
    @just --list

# Build and start broker + backend (:8000) + frontend (http://localhost:8080) in Docker; MySQL stays on the laptop.
up:
    {{ compose }} up -d --build --wait

# Stop and remove the Docker stack (broker, backend, frontend); keeps volumes.
down:
    {{ compose }} down

# Show the Docker stack status.
status:
    {{ compose }} ps

# Follow Docker logs: all services, or e.g. `just logs backend`; Ctrl+C to exit.
logs *services:
    {{ compose }} logs --tail 100 -f {{ services }}

# Start the LAN MQTT broker and wait until healthy.
broker-up:
    docker compose -f deployment/compose.yaml up -d --wait

# Stop the broker; keep its data volume.
broker-down:
    docker compose -f deployment/compose.yaml down

# Show broker status.
broker-status:
    docker compose -f deployment/compose.yaml ps

# Follow the last 100 broker log lines; Ctrl+C to exit.
broker-logs:
    docker compose -f deployment/compose.yaml logs --tail 100 -f mosquitto

# Start FastAPI at http://localhost:8000 (API docs: /docs); accepts uvicorn flags.
[working-directory('backend')]
backend *args:
    & '{{ backend_python }}' -m uvicorn app.main:app --host 0.0.0.0 --port 8000 {{ args }}

# Start Vite at http://localhost:5173; accepts Vite flags.
[working-directory('frontend')]
frontend *args:
    npm.cmd run dev -- {{ args }}

# Build the frontend into frontend/dist.
[working-directory('frontend')]
build:
    npm.cmd run build

# Preview the frontend build; run `just build` first.
[working-directory('frontend')]
preview *args:
    npm.cmd run preview -- {{ args }}

# Run host tests in separate processes, excluding real brokers and performance measurements.
test: test-backend test-firmware test-system

# Backend tests without a real broker; accepts pytest flags.
[working-directory('backend')]
test-backend *args:
    & '{{ backend_python }}' -m pytest tests -q -m 'not integration' {{ args }}

# Backend integration tests (requires the configured local broker).
[working-directory('backend')]
test-backend-integration *args:
    & '{{ backend_python }}' -m pytest tests -q -m integration {{ args }}

# Firmware host tests; does not access the ESP32.
test-firmware *args:
    & '{{ firmware_python }}' -m pytest firmware/tests -q {{ args }}

# System tests without a real broker or performance measurements; accepts pytest flags.
test-system *args:
    & '{{ backend_python }}' -m pytest tests -q -m 'not broker_that and not hieu_nang' {{ args }}

# Full system suite, including performance measurements and available real-broker tests.
test-system-full *args:
    & '{{ backend_python }}' -m pytest tests -q {{ args }}

# Start simulated devices (default: 3); accepts simulator flags after count.
[working-directory('backend')]
simulate count='3' *args:
    & '{{ backend_python }}' tools/sim_device.py --count '{{ count }}' {{ args }}

# ESP32 USB utility: ports, monitor, info, scan, backup or reset (default: info COM3).
board command='info' port='COM3':
    & ./firmware/tools/board.ps1 -Command '{{ command }}' -Port '{{ port }}'

# Deploy firmware over USB; add -Config explicitly to copy config.json.
deploy port='COM3' *args:
    & ./firmware/tools/deploy.ps1 -Port '{{ port }}' {{ args }}

# Push firmware over Wi-Fi to an online device; accepts OTA tool flags.
[working-directory('backend')]
ota device *args:
    & '{{ backend_python }}' tools/ota_push.py --device '{{ device }}' --src ../firmware/src {{ args }}

# Firmware config utility (help by default); writes config only when explicitly requested.
config *args='--help':
    & '{{ python }}' firmware/tools/make_config.py {{ args }}
