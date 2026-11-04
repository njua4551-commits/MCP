"""Configuración global del MCP Cisco Packet Tracer (Fase 0)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
EVIDENCE_DIR = ROOT / "evidence"
LOGS_DIR = ROOT / "logs"
TESTS_DIR = ROOT / "tests"

for _d in (DATA_DIR, EVIDENCE_DIR, LOGS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Packet Tracer -----------------------------------------------------------
PT_PROCESS_NAME = "PacketTracer"
PT_TITLE_HINTS = ("packet tracer",)
PT_INSTALL_GLOBS = (
    r"C:\Program Files\Cisco Packet Tracer*",
    r"C:\Program Files (x86)\Cisco Packet Tracer*",
)
PT_EXE_RELATIVE = ("bin\\PacketTracer.exe", "PacketTracer.exe")

# --- Seguridad ---------------------------------------------------------------
READ_ONLY = True  # Fase 0: nunca escribir ni hacer clic
MAX_CLI_OUTPUT_CHARS = 2000

# --- Captura -----------------------------------------------------------------
# Un frame se considera inválido si es casi uniforme (negro, blanco o gris plano).
CAPTURE_MIN_STDDEV = 3.0
CAPTURE_MIN_UNIQUE_COLORS = 12
CAPTURE_BLACK_RATIO_MAX = 0.995
