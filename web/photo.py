"""Photo handling: decode, re-encode, throw the original bytes away.

An uploaded image is never stored or passed through. It is decoded, redrawn at
a fixed size and re-encoded as JPEG, so what ends up in the document is bytes
this server produced. That drops EXIF (including any GPS coordinates), any
trailing payload appended to a valid image, and anything a polyglot file was
carrying alongside its image data.
"""

from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps

# A 400x400 photo is what the template wants at print resolution.
SIZE = 400
QUALITY = 88
MAX_UPLOAD = 2 * 1024 * 1024

# Pillow's own guard against decompression bombs: a 20 MP source is already far
# more than a CV photo needs, and refusing early keeps a small upload from
# turning into gigabytes of pixels.
Image.MAX_IMAGE_PIXELS = 20_000_000

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "BMP", "TIFF"}

PREFIX = "data:image/jpeg;base64,"


class PhotoError(ValueError):
    """An upload we will not turn into a photo. The message is safe to show."""


def _decode(raw: bytes) -> Image.Image:
    if len(raw) > MAX_UPLOAD:
        raise PhotoError(f"Image is larger than {MAX_UPLOAD // 1024 // 1024} MB.")
    if not raw:
        raise PhotoError("Empty upload.")

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            fmt = probe.format
            probe.verify()
    except PhotoError:
        raise
    except Exception:
        raise PhotoError("That file is not an image we can read.")

    if fmt not in ALLOWED_FORMATS:
        raise PhotoError(f"Unsupported image format: {fmt}.")

    # verify() consumes the file, so open it a second time for the pixels.
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception:
        raise PhotoError("That image is damaged and cannot be read.")
    return image


def to_data_uri(raw: bytes) -> str:
    """Turn uploaded bytes into a square JPEG data: URI of our own making."""
    image = _decode(raw)
    try:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        image = ImageOps.fit(image, (SIZE, SIZE), method=Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=QUALITY, optimize=True)
    finally:
        image.close()
    return PREFIX + base64.b64encode(buffer.getvalue()).decode("ascii")


def resanitize(data_uri: str) -> str:
    """Re-run a data: URI through the pipeline before it reaches the renderer.

    /api/photo is not the only way bytes can arrive here — a request can post
    straight to /api/render with a photo field of its own, and an imported JSON
    file carries one too. Treating an incoming URI as raw upload bytes again
    means the renderer only ever sees an image this server encoded.
    """
    if not data_uri:
        return ""
    if not data_uri.startswith(PREFIX):
        raise PhotoError("Unsupported photo encoding.")
    try:
        raw = base64.b64decode(data_uri[len(PREFIX):], validate=True)
    except Exception:
        raise PhotoError("Photo data is not valid base64.")
    return to_data_uri(raw)
