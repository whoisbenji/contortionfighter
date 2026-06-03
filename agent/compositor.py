"""
Image compositor for the monthly performance review.

Reads performer photos from Notion ICPDB, composites them into the Figma
template layout (scattered rotated rounded-rect cards on a dark background),
and outputs two formats:
  • Instagram Story  — 1080 × 1920 px  (9:16)
  • Article header   — 1500 × 844 px   (16:9)

The template geometry is derived directly from the Figma file
(LzSysRugmbHEVMdCAVDe4k, node 1:21).
"""

from __future__ import annotations

import io
import math
import os
import re
import urllib.request
from pathlib import Path
from typing import NamedTuple

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import NOTION_BASE, NOTION_ICPDB_DS


# ── Template geometry (native px, from Figma) ────────────────────────────────

class Slot(NamedTuple):
    cx: float   # centre-x in native coords
    cy: float   # centre-y in native coords
    size: float # card side length (square, before rotation)
    radius: float  # corner radius


NATIVE_W = 496
NATIVE_H = 1073
CARD_ROTATION = 30  # degrees, all slots identical


def _slot(container_left, container_top, container_size, card_size, radius=24):
    cx = container_left + container_size / 2
    cy = container_top + container_size / 2
    return Slot(cx, cy, card_size, radius)


# 16 slots extracted from Figma node positions
SLOTS: list[Slot] = [
    _slot(273.95, -18.58,  168.502, 123.352),   # 0
    _slot(-46.23, -20.58,  166.863, 122.152),   # 1
    _slot( 54.13, 354.55,  175.746, 128.655),   # 2
    _slot(150.00, 511.00,  175.746, 128.655),   # 3
    _slot(113.36, -16.91,  166.863, 122.152),   # 4
    _slot(125.73, 231.49,  166.863, 122.152),   # 5
    _slot(-38.53, 231.49,  166.863, 122.152),   # 6
    _slot( 54.00, 629.00,  157.746, 115.478),   # 7
    _slot(351.50, 102.95,  166.863, 122.152),   # 8
    _slot( 38.00, 102.95,  166.863, 122.152),   # 9
    _slot(218.00, 118.00,  152.146, 111.379),   # 10
    _slot(287.00, 231.00,  176.217, 129.000),   # 11
    _slot(209.00, 695.00,  176.217, 129.000),   # 12
    _slot(310.00, 569.00,  176.217, 129.000),   # 13
    _slot(211.00, 354.00,  176.217, 129.000),   # 14
    _slot(353.00, 407.00,  176.217, 129.000),   # 15
]

# Title text geometry (native px)
TITLE_LEFT   = 26
TITLE_TOP    = 816
TITLE_WIDTH  = 460
FONT_SIZE_NATIVE = 44
BG_COLOUR    = "#090909"
TEXT_COLOUR  = (255, 255, 255)


# ── Font loading ──────────────────────────────────────────────────────────────

FONT_CACHE_DIR = Path(__file__).parent / "_fonts"
FONT_URL = (
    "https://fonts.gstatic.com/s/unbounded/v11/"
    "d3p-idDNMfFfseWMB-FIXh8h7g.woff2"
)
FONT_TTF_URL = (
    "https://fonts.gstatic.com/s/unbounded/v11/"
    "d3p-idDNMfFfseWMBPFI.ttf"
)


def _load_font(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    FONT_CACHE_DIR.mkdir(exist_ok=True)
    ttf_path = FONT_CACHE_DIR / "Unbounded-Bold.ttf"
    if not ttf_path.exists():
        try:
            # Try fetching a usable TTF subset from Google Fonts CSS
            css_url = (
                "https://fonts.googleapis.com/css2?family=Unbounded:wght@700"
            )
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(css_url, headers=headers, timeout=10)
            urls = re.findall(r"url\((https://[^)]+\.ttf)\)", resp.text)
            if not urls:
                urls = re.findall(r"url\((https://[^)]+)\)", resp.text)
            if urls:
                font_bytes = requests.get(urls[0], timeout=10).content
                ttf_path.write_bytes(font_bytes)
        except Exception:
            pass  # fall back to default below

    try:
        if ttf_path.exists():
            return ImageFont.truetype(str(ttf_path), size_px)
        # Try system bold fonts as fallback
        for sys_font in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                         "/System/Library/Fonts/Helvetica.ttc",
                         "arial.ttf", "arialbd.ttf"]:
            try:
                return ImageFont.truetype(sys_font, size_px)
            except OSError:
                continue
    except Exception:
        pass
    return ImageFont.load_default()


# ── Rounded-rectangle mask ────────────────────────────────────────────────────

def _rounded_mask(size: int, radius: int) -> Image.Image:
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


# ── Core compositing ──────────────────────────────────────────────────────────

def _paste_card(
    canvas: Image.Image,
    photo: Image.Image,
    slot: Slot,
    scale: float,
    x_offset: int = 0,
    y_offset: int = 0,
) -> None:
    """
    Resize, round-corner-mask, rotate a performer photo and paste it onto
    the canvas at the slot position (scaled by `scale`).
    """
    card_px   = max(4, int(slot.size   * scale))
    radius_px = max(2, int(slot.radius * scale))

    # Crop source photo to square (centre crop)
    w, h = photo.size
    min_side = min(w, h)
    left  = (w - min_side) // 2
    top   = (h - min_side) // 2
    photo = photo.crop((left, top, left + min_side, top + min_side))
    photo = photo.resize((card_px, card_px), Image.LANCZOS).convert("RGBA")

    # Apply rounded corner mask
    mask = _rounded_mask(card_px, radius_px)
    photo.putalpha(mask)

    # Rotate 30° with expand so corners don't clip
    rotated = photo.rotate(-CARD_ROTATION, expand=True, resample=Image.BICUBIC)

    # Centre of rotation on canvas
    cx = int(slot.cx * scale) + x_offset
    cy = int(slot.cy * scale) + y_offset

    paste_x = cx - rotated.width  // 2
    paste_y = cy - rotated.height // 2

    canvas.paste(rotated, (paste_x, paste_y), rotated)


def _draw_title(
    canvas: Image.Image,
    month_label: str,
    scale: float,
    x_offset: int = 0,
    y_offset: int = 0,
) -> None:
    draw = ImageDraw.Draw(canvas)
    font_size = max(12, int(FONT_SIZE_NATIVE * scale))
    font = _load_font(font_size)
    x = int(TITLE_LEFT * scale) + x_offset
    y = int(TITLE_TOP  * scale) + y_offset
    draw.text((x, y), f"{month_label}\nperformances", font=font, fill=TEXT_COLOUR)


def _build_canvas(
    photos: list[Image.Image],
    out_w: int,
    out_h: int,
    scale: float,
    x_offset: int,
    y_offset: int,
    month_label: str,
) -> Image.Image:
    canvas = Image.new("RGBA", (out_w, out_h), BG_COLOUR)

    for i, slot in enumerate(SLOTS):
        if i >= len(photos):
            break
        photo = photos[i]
        if photo is None:
            continue
        try:
            _paste_card(canvas, photo, slot, scale, x_offset, y_offset)
        except Exception as exc:
            print(f"  ⚠ Skipped slot {i}: {exc}")

    _draw_title(canvas, month_label, scale, x_offset, y_offset)
    return canvas.convert("RGB")


# ── Public render functions ───────────────────────────────────────────────────

def render_story(
    month_label: str,
    photos: list[Image.Image],
    output_path: str | Path,
) -> Path:
    """Render a 1080 × 1920 Instagram Story PNG."""
    out_w, out_h = 1080, 1920
    # Scale so the native template fills the height
    scale = out_h / NATIVE_H          # ≈ 1.789
    rendered_w = int(NATIVE_W * scale)  # ≈ 887
    x_offset = (out_w - rendered_w) // 2
    canvas = _build_canvas(photos, out_w, out_h, scale, x_offset, 0, month_label)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(output_path), "PNG", optimize=True)
    return output_path


def render_header(
    month_label: str,
    photos: list[Image.Image],
    output_path: str | Path,
) -> Path:
    """
    Render a 1500 × 844 article header PNG.

    Layout: the template collage fills the left ~40% of the canvas (scaled to
    full height). The right 60% is solid dark background with the title text
    repositioned for landscape reading.
    """
    out_w, out_h = 1500, 844
    scale = out_h / NATIVE_H          # ≈ 0.787
    rendered_w = int(NATIVE_W * scale)  # ≈ 390
    x_offset = 0
    canvas = _build_canvas(photos, out_w, out_h, scale, x_offset, 0, month_label)

    # Reposition title to right-side area for landscape feel
    draw = ImageDraw.Draw(canvas)
    font_size = max(12, int(72 * scale * 1.6))  # larger than native for landscape
    font = _load_font(font_size)
    title_x = rendered_w + 60
    title_y = out_h // 2 - font_size
    draw.text(
        (title_x, title_y),
        f"{month_label}\nperformances",
        font=font,
        fill=TEXT_COLOUR,
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(output_path), "PNG", optimize=True)
    return output_path


# ── Notion photo fetching ─────────────────────────────────────────────────────

def _notion_headers() -> dict:
    from .config import NOTION_VERSION
    return {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Notion-Version": NOTION_VERSION,
    }


def fetch_performer_photos(performer_ids: list[str], limit: int = 16) -> list[Image.Image | None]:
    """
    Download the 'Main photo' for each Notion performer page ID.
    Returns a list of PIL Images (or None where no photo is available),
    up to `limit` entries.
    """
    photos: list[Image.Image | None] = []

    for page_id in performer_ids[:limit]:
        try:
            resp = requests.get(
                f"{NOTION_BASE}/pages/{page_id}",
                headers=_notion_headers(),
                timeout=15,
            )
            resp.raise_for_status()
            page = resp.json()
            props = page.get("properties", {})
            main_photo = props.get("Main photo", {})

            files = main_photo.get("files", [])
            if not files:
                photos.append(None)
                continue

            # Notion files can be "file" (internal, has expiry URL) or "external"
            file_entry = files[0]
            if file_entry.get("type") == "file":
                url = file_entry["file"]["url"]
            elif file_entry.get("type") == "external":
                url = file_entry["external"]["url"]
            else:
                photos.append(None)
                continue

            img_resp = requests.get(url, timeout=20)
            img_resp.raise_for_status()
            img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
            photos.append(img)

        except Exception as exc:
            print(f"  ⚠ Could not fetch photo for {page_id}: {exc}")
            photos.append(None)

    # Pad to requested limit with None
    while len(photos) < limit:
        photos.append(None)

    return photos


# ── Webflow asset upload ──────────────────────────────────────────────────────

def upload_to_webflow(image_path: Path, asset_name: str) -> dict:
    """
    Upload an image file to Webflow Assets using the v2 data API.
    Returns {"asset_id": ..., "url": ...}.
    """
    from .config import WEBFLOW_BASE, WEBFLOW_SITE_ID

    webflow_key = os.environ["WEBFLOW_API_KEY"]
    headers = {"Authorization": f"Bearer {webflow_key}"}

    # Step 1: Create asset metadata entry
    file_bytes = image_path.read_bytes()
    import hashlib
    file_hash = hashlib.md5(file_bytes).hexdigest()

    meta_resp = requests.post(
        f"{WEBFLOW_BASE}/sites/{WEBFLOW_SITE_ID}/assets",
        headers={**headers, "Content-Type": "application/json"},
        json={"fileName": asset_name, "fileHash": file_hash},
        timeout=30,
    )
    meta_resp.raise_for_status()
    meta = meta_resp.json()

    upload_url     = meta["uploadUrl"]
    upload_details = meta["uploadDetails"]
    asset_id       = meta["id"]

    # Step 2: POST multipart to S3
    fields = {k: str(v) for k, v in upload_details.items()}
    upload_resp = requests.post(
        upload_url,
        data=fields,
        files={"file": (asset_name, file_bytes, "image/png")},
        timeout=60,
    )
    if upload_resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"S3 upload failed: {upload_resp.status_code} {upload_resp.text[:200]}")

    return {"asset_id": asset_id, "url": meta.get("hostedUrl", "")}


# ── Top-level orchestration ───────────────────────────────────────────────────

def generate_and_upload_images(
    month_label: str,
    performer_ids: list[str],
    output_dir: str | Path | None = None,
) -> dict:
    """
    Full pipeline:
      1. Fetch performer photos from Notion ICPDB
      2. Render Story (1080×1920) and Header (1500×844) PNGs
      3. Save to output_dir (default: ./output/<month-slug>/)
      4. Upload header to Webflow Assets

    Returns dict with local paths and Webflow asset info.
    """
    if output_dir is None:
        slug = month_label.lower().replace(" ", "-")
        output_dir = Path("output") / slug
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"  📸 Fetching performer photos from Notion ({len(performer_ids)} performers)…")
    photos = fetch_performer_photos(performer_ids, limit=16)
    present = sum(1 for p in photos if p is not None)
    print(f"     {present}/{min(len(performer_ids), 16)} photos fetched successfully.")

    slug = month_label.lower().replace(" ", "-")

    story_path  = output_dir / f"{slug}-story.png"
    header_path = output_dir / f"{slug}-header.png"

    print("  🖼  Rendering Instagram Story (1080×1920)…")
    render_story(month_label, photos, story_path)
    print(f"     Saved → {story_path}")

    print("  🖼  Rendering Article Header (1500×844)…")
    render_header(month_label, photos, header_path)
    print(f"     Saved → {header_path}")

    print("  ☁️  Uploading header to Webflow Assets…")
    try:
        asset_info = upload_to_webflow(header_path, f"{slug}-header.png")
        print(f"     Uploaded → asset ID: {asset_info['asset_id']}")
    except Exception as exc:
        print(f"  ⚠ Webflow upload failed: {exc}")
        asset_info = {"asset_id": None, "url": None}

    return {
        "story_path":     str(story_path),
        "header_path":    str(header_path),
        "webflow_asset_id": asset_info["asset_id"],
        "webflow_asset_url": asset_info["url"],
    }
