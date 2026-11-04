"""Captura de la ventana de Packet Tracer con validación local.

Estrategia escalonada (sección 6 del .md):
  1. PrintWindow con PW_RENDERFULLCONTENT
  2. BitBlt desde el DC de la ventana
  3. Recorte de escritorio del rectángulo de la ventana (último recurso)

Cada candidato se valida localmente (no vacío, no negro, no plano). Nunca se
devuelve la imagen al modelo salvo que se solicite explícitamente.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import ctypes
import numpy as np
import win32gui
import win32ui
from PIL import Image, ImageGrab

import config
from . import window_manager as wm

PW_RENDERFULLCONTENT = 0x00000002


def _window_size(hwnd: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = wm._window_rect(hwnd)
    return left, top, max(1, right - left), max(1, bottom - top)


def _capture_printwindow(hwnd: int) -> Image.Image:
    left, top, width, height = _window_size(hwnd)
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)
        ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        return Image.frombuffer(
            "RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1
        ).copy()
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)


def _capture_bitblt(hwnd: int) -> Image.Image:
    left, top, width, height = _window_size(hwnd)
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)
        save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con_SRCCOPY)
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        return Image.frombuffer(
            "RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1
        ).copy()
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)


win32con_SRCCOPY = 0x00CC0020


def _capture_desktop_crop(hwnd: int) -> Image.Image:
    left, top, width, height = _window_size(hwnd)
    return ImageGrab.grab(
        bbox=(left, top, left + width, top + height), all_screens=True
    ).convert("RGB")


def stats(img: Image.Image) -> dict[str, Any]:
    """Métricas locales para decidir si la captura es utilizable."""
    arr = np.asarray(img.convert("RGB"))
    gray = arr.mean(axis=2)
    small = arr[::4, ::4].reshape(-1, 3)
    unique = int(np.unique(small, axis=0).shape[0])
    return {
        "width": int(img.width),
        "height": int(img.height),
        "mean": round(float(gray.mean()), 2),
        "std": round(float(gray.std()), 2),
        "unique_colors": unique,
        "black_ratio": round(float((gray < 8).mean()), 4),
    }


def is_valid(st: dict[str, Any]) -> tuple[bool, str]:
    if st["width"] < 200 or st["height"] < 150:
        return False, "captura demasiado pequeña"
    if st["black_ratio"] > config.CAPTURE_BLACK_RATIO_MAX:
        return False, "captura negra"
    if st["std"] < config.CAPTURE_MIN_STDDEV:
        return False, "captura uniforme (posible ventana no renderizada)"
    if st["unique_colors"] < config.CAPTURE_MIN_UNIQUE_COLORS:
        return False, "pocos colores (posible contenido vacío)"
    return True, ""


METHODS = (
    ("printwindow", _capture_printwindow),
    ("bitblt", _capture_bitblt),
    ("desktop_crop", _capture_desktop_crop),
)


def changed_ratio(a: Image.Image, b: Image.Image, threshold: int = 24) -> float:
    """Proporción de píxeles que cambian de forma perceptible entre dos frames."""
    if a.size != b.size:
        return 1.0
    diff = np.abs(np.asarray(a.convert("RGB"), dtype=np.int16) - np.asarray(b.convert("RGB"), dtype=np.int16))
    return round(float((diff.max(axis=2) > threshold).mean()), 4)


def capture_window(
    hwnd: int, method: str = "auto", save_path: str | Path | None = None
) -> dict[str, Any]:
    """Captura validada. Devuelve metadatos; la imagen solo si se pide."""
    attempts: list[dict[str, Any]] = []
    chosen: Image.Image | None = None
    chosen_method = ""

    for name, fn in METHODS:
        if method != "auto" and method != name:
            continue
        try:
            img = fn(hwnd)
        except Exception as exc:  # fallo del método, se prueba el siguiente
            attempts.append({"method": name, "error": f"{type(exc).__name__}: {exc}"})
            continue
        st = stats(img)
        ok, reason = is_valid(st)
        attempts.append({"method": name, "ok": ok, "reason": reason, **st})
        if ok:
            chosen, chosen_method = img, name
            break

    if chosen is None:
        return {"ok": False, "hwnd": hwnd, "attempts": attempts, "method": None}

    saved = ""
    if save_path:
        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        chosen.save(path, "PNG")
        saved = str(path)

    return {
        "ok": True,
        "hwnd": hwnd,
        "method": chosen_method,
        "attempts": attempts,
        "saved": saved,
        "image": chosen,
    }
