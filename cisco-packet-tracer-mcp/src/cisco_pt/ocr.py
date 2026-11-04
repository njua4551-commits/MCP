"""OCR local con el motor nativo de Windows (Windows.Media.Ocr).

No envía imágenes a ningún servicio externo. Se usa para leer etiquetas de
dispositivos y, más adelante, la salida de la CLI.
"""

from __future__ import annotations

import asyncio
from typing import Any

from PIL import Image
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

_DEFAULT_LANG = "es-ES"


def _to_software_bitmap(img: Image.Image) -> SoftwareBitmap:
    rgb = img.convert("RGBA")
    data = rgb.tobytes("raw", "BGRA")
    writer = DataWriter()
    writer.write_bytes(data)
    buffer = writer.detach_buffer()
    return SoftwareBitmap.create_copy_from_buffer(
        buffer, BitmapPixelFormat.BGRA8, rgb.width, rgb.height, BitmapAlphaMode.PREMULTIPLIED
    )


def _engine(lang: str | None) -> OcrEngine:
    tag = lang or _DEFAULT_LANG
    try:
        return OcrEngine.try_create_from_language(Language(tag))
    except Exception:
        return OcrEngine.try_create_from_user_profile_languages()


async def _recognize(img: Image.Image, lang: str | None) -> Any:
    engine = _engine(lang)
    if engine is None:
        raise RuntimeError("no hay motor OCR disponible en Windows")
    return await engine.recognize_async(_to_software_bitmap(img))


def read_words(img: Image.Image, lang: str | None = None) -> list[dict[str, Any]]:
    """Palabras reconocidas con su caja en coordenadas de la imagen."""
    result = asyncio.run(_recognize(img, lang))
    words: list[dict[str, Any]] = []
    for line in result.lines:
        for word in line.words:
            r = word.bounding_rect
            words.append(
                {
                    "text": word.text,
                    "x": int(r.x),
                    "y": int(r.y),
                    "w": int(r.width),
                    "h": int(r.height),
                    "cx": int(r.x + r.width / 2),
                    "cy": int(r.y + r.height / 2),
                }
            )
    return words


def read_text(img: Image.Image, lang: str | None = None) -> str:
    result = asyncio.run(_recognize(img, lang))
    return "\n".join(line.text for line in result.lines)


# Etiquetas típicas de Packet Tracer: PC0, R1, SW1, Switch0, Router1, Laptop2...
_LABEL_PREFIXES = ("pc", "r", "sw", "switch", "router", "laptop", "server", "srv", "ap", "asa", "isp", "dns", "dhcp", "fa")


def looks_like_device_label(text: str) -> bool:
    t = text.strip().replace(" ", "")
    if not (1 <= len(t) <= 14) or not any(ch.isdigit() for ch in t):
        return False
    low = t.lower()
    return any(low.startswith(p) and (len(low) == len(p) or not low[len(p)].isalpha()) for p in _LABEL_PREFIXES)


def find_labels(img: Image.Image, lang: str | None = None) -> list[dict[str, Any]]:
    """Etiquetas de dispositivos detectadas en una captura del lienzo."""
    return [w for w in read_words(img, lang) if looks_like_device_label(w["text"])]
