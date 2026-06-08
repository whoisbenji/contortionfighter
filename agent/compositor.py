"""
Image compositor for the monthly performance review.

Reads performer photos from Notion ICPDB, composites them into the Figma
template layout (scattered rotated rounded-rect cards on a dark background),
and outputs two formats:
  • Instagram Story  — 1080 × 1920 px  (9:16)  — frame 1:21, has title text
  • Article header   — 1500 × 844 px   (16:9)  — frame 1:2,  no text

Template geometry derived from Figma file LzSysRugmbHEVMdCAVDe4k.
"""

from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import NamedTuple

import requests
from PIL import Image, ImageDraw, ImageFont

from .config import NOTION_BASE, NOTION_ICPDB_DS


# ── Template geometry (native px, from Figma) ────────────────────────────────

class Slot(NamedTuple):
    cx: float    # centre-x in native coords
    cy: float    # centre-y in native coords
    size: float  # card side length (square, before rotation)
    radius: float


CARD_ROTATION = 30  # degrees, same for all slots
BG_COLOUR     = "#090909"
TEXT_COLOUR   = (255, 255, 255)


# Frame 1:21 — Social / Story template, native 496×1073, title at (26, 816)
STORY_NATIVE_W = 496
STORY_NATIVE_H = 1073
STORY_TITLE_LEFT  = 26
STORY_TITLE_TOP   = 816
STORY_FONT_SIZE_NATIVE = 44

STORY_SLOTS: list[Slot] = [
    Slot(419.85,  65.65, 168.50, 24),
    Slot( 98.23,  62.83, 166.86, 24),
    Slot(206.37, 442.47, 175.75, 24),
    Slot(302.17, 598.87, 175.75, 24),
    Slot(257.83,  66.53, 166.86, 24),
    Slot(270.23, 314.93, 166.86, 24),
    Slot(105.93, 314.93, 166.86, 24),
    Slot(190.57, 707.87, 157.75, 24),
    Slot(496.03, 186.43, 166.86, 24),
    Slot(182.53, 186.43, 166.86, 24),
    Slot(349.77, 194.07, 152.15, 24),
    Slot(439.61, 319.11, 176.22, 24),
    Slot(361.61, 783.11, 176.22, 24),
    Slot(462.61, 657.11, 176.22, 24),
    Slot(363.61, 442.11, 176.22, 24),
    Slot(505.61, 495.11, 176.22, 24),
]

# Frame 1:2 — Header template, native 1956×911, no text
HEADER_NATIVE_W = 1956
HEADER_NATIVE_H = 911

HEADER_SLOTS: list[Slot] = [
    Slot(1083.75, 108.45, 393.70, 24),
    Slot( 332.34, 101.94, 389.88, 24),
    Slot(1514.22,  16.32, 410.63, 24),
    Slot(1869.92, 112.32, 410.63, 24),
    Slot( 705.24, 110.44, 389.88, 24),
    Slot( 757.44, 690.84, 389.88, 24),
    Slot( 373.64, 690.84, 389.88, 24),
    Slot(1332.69, 312.00, 368.57, 24),
    Slot( 911.14, 390.54, 389.88, 24),
    Slot( 178.64, 390.54, 389.88, 24),
    Slot( 514.75, 399.05, 355.49, 24),
    Slot(1192.17, 596.47, 411.73, 24),
    Slot(1698.47, 427.17, 411.73, 24),
    Slot(1951.97, 727.57, 411.73, 24),
    Slot(1493.27, 782.87, 411.73, 24),
    Slot(1034.57, 885.87, 411.73, 24),
]


# ── Font loading ──────────────────────────────────────────────────────────────

FONT_CACHE_DIR = Path(__file__).parent / "_fonts"


def _load_font(size_px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    FONT_CACHE_DIR.mkdir(exist_ok=True)
    ttf_path = FONT_CACHE_DIR / "Unbounded-Bold.ttf"
    if not ttf_path.exists():
        try:
            css_url = "https://fonts.googleapis.com/css2?family=Unbounded:wght@700"
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(css_url, headers=headers, timeout=10)
            urls = re.findall(r"url\((https://[^)]+\.ttf)\)", resp.text)
            if not urls:
                urls = re.findall(r"url\((https://[^)]+)\)", resp.text)
            if urls:
                font_bytes = requests.get(urls[0], timeout=10).content
                ttf_path.write_bytes(font_bytes)
        except Exception:
            pass

    try:
        if ttf_path.exists():
            return ImageFont.truetype(str(ttf_path), size_px)
        for sys_font in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "arial.ttf",
            "arialbd.ttf",
        ]:
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
    card_px   = max(4, int(slot.size   * scale))
    radius_px = max(2, int(slot.radius * scale))

    w, h = photo.size
    min_side = min(w, h)
    left = (w - min_side) // 2
    top  = (h - min_side) // 2
    photo = photo.crop((left, top, left + min_side, top + min_side))
    photo = photo.resize((card_px, card_px), Image.LANCZOS).convert("RGBA")

    mask = _rounded_mask(card_px, radius_px)
    photo.putalpha(mask)

    rotated = photo.rotate(-CARD_ROTATION, expand=True, resample=Image.BICUBIC)

    cx = int(slot.cx * scale) + x_offset
    cy = int(slot.cy * scale) + y_offset

    paste_x = cx - rotated.width  // 2
    paste_y = cy - rotated.height // 2

    canvas.paste(rotated, (paste_x, paste_y), rotated)


def _build_canvas(
    photos: list[Image.Image | None],
    slots: list[Slot],
    out_w: int,
    out_h: int,
    scale: float,
    x_offset: int,
    y_offset: int,
    month_label: str | None = None,
    title_left_native: float = 0,
    title_top_native: float = 0,
    font_size_native: int = 44,
) -> Image.Image:
    canvas = Image.new("RGBA", (out_w, out_h), BG_COLOUR)

    for i, slot in enumerate(slots):
        if i >= len(photos):
            break
        photo = photos[i]
        if photo is None:
            continue
        try:
            _paste_card(canvas, photo, slot, scale, x_offset, y_offset)
        except Exception as exc:
            print(f"  ⚠ Skipped slot {i}: {exc}")

    if month_label is not None:
        draw = ImageDraw.Draw(canvas)
        font_size = max(12, int(font_size_native * scale))
        font = _load_font(font_size)
        x = int(title_left_native * scale) + x_offset
        y = int(title_top_native  * scale) + y_offset
        draw.text((x, y), f"{month_label}\nperformances", font=font, fill=TEXT_COLOUR)

    return canvas.convert("RGB")


# ── Public render functions ───────────────────────────────────────────────────

def render_story(
    month_label: str,
    photos: list[Image.Image | None],
    output_path: str | Path,
) -> Path:
    """Render a 1080 × 1920 Instagram Story PNG (frame 1:21, with title text)."""
    out_w, out_h = 1080, 1920
    scale    = out_h / STORY_NATIVE_H                      # ≈ 1.789
    x_offset = (out_w - int(STORY_NATIVE_W * scale)) // 2  # centres horizontally

    canvas = _build_canvas(
        photos=photos,
        slots=STORY_SLOTS,
        out_w=out_w,
        out_h=out_h,
        scale=scale,
        x_offset=x_offset,
        y_offset=0,
        month_label=month_label,
        title_left_native=STORY_TITLE_LEFT,
        title_top_native=STORY_TITLE_TOP,
        font_size_native=STORY_FONT_SIZE_NATIVE,
    )
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(str(output_path), "PNG", optimize=True)
    return output_path


def render_header(
    month_label: str,
    photos: list[Image.Image | None],
    output_path: str | Path,
) -> Path:
    """Render a 1500 × 844 article header PNG (frame 1:2, no text)."""
    out_w, out_h = 1500, 844
    scale    = out_w / HEADER_NATIVE_W                      # ≈ 0.767, width-constrained
    y_offset = (out_h - int(HEADER_NATIVE_H * scale)) // 2  # centres vertically

    canvas = _build_canvas(
        photos=photos,
        slots=HEADER_SLOTS,
        out_w=out_w,
        out_h=out_h,
        scale=scale,
        x_offset=0,
        y_offset=y_offset,
        month_label=None,  # no title on header
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


def check_performer_photos(performer_ids: list[str]) -> list[dict]:
    """
    For each performer ID fetch their name and Main photo URL — without downloading images.
    Returns list of {page_id, name, has_photo, photo_url}.
    """
    results: list[dict] = []
    for page_id in performer_ids[:16]:
        try:
            resp = requests.get(
                f"{NOTION_BASE}/pages/{page_id}",
                headers=_notion_headers(),
                timeout=15,
            )
            resp.raise_for_status()
            page  = resp.json()
            props = page.get("properties", {})

            # Extract name from whichever property is the title
            name = ""
            for prop in props.values():
                if prop.get("type") == "title":
                    texts = prop.get("title", [])
                    name = texts[0].get("plain_text", "") if texts else ""
                    break

            files = props.get("Main photo", {}).get("files", [])
            photo_url: str | None = None
            if files:
                f = files[0]
                if f.get("type") == "file":
                    photo_url = f["file"]["url"]
                elif f.get("type") == "external":
                    photo_url = f["external"]["url"]

            ig_texts = props.get("Instagram", {}).get("rich_text", [])
            instagram = ig_texts[0].get("plain_text", "").lstrip("@") if ig_texts else ""

            results.append({
                "page_id":   page_id,
                "name":      name or page_id,
                "has_photo": photo_url is not None,
                "photo_url": photo_url,
                "instagram": instagram,
            })
        except Exception as exc:
            print(f"  ⚠ check_performer_photos failed for {page_id}: {exc}")
            results.append({
                "page_id":   page_id,
                "name":      page_id,
                "has_photo": False,
                "photo_url": None,
            })
    return results


def fetch_performer_photos(performer_ids: list[str], limit: int = 16) -> list[Image.Image | None]:
    """Download the 'Main photo' for each Notion performer page ID."""
    photos: list[Image.Image | None] = []

    for page_id in performer_ids[:limit]:
        try:
            resp = requests.get(
                f"{NOTION_BASE}/pages/{page_id}",
                headers=_notion_headers(),
                timeout=15,
            )
            resp.raise_for_status()
            page  = resp.json()
            props = page.get("properties", {})
            files = props.get("Main photo", {}).get("files", [])

            if not files:
                photos.append(None)
                continue

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

    while len(photos) < limit:
        photos.append(None)

    return photos


# ── Webflow asset upload ──────────────────────────────────────────────────────

def upload_to_webflow(image_path: Path, asset_name: str) -> dict:
    """Upload an image file to Webflow Assets (v2). Returns {"asset_id", "url"}."""
    from .config import WEBFLOW_BASE, WEBFLOW_SITE_ID
    import hashlib

    webflow_key = os.environ["WEBFLOW_API_KEY"]
    headers = {"Authorization": f"Bearer {webflow_key}"}

    file_bytes = image_path.read_bytes()
    file_hash  = hashlib.md5(file_bytes).hexdigest()

    meta_resp = requests.post(
        f"{WEBFLOW_BASE}/sites/{WEBFLOW_SITE_ID}/assets",
        headers={**headers, "Content-Type": "application/json"},
        json={"fileName": asset_name, "fileHash": file_hash},
        timeout=30,
    )
    meta_resp.raise_for_status()
    meta = meta_resp.json()

    fields = {k: str(v) for k, v in meta["uploadDetails"].items()}
    upload_resp = requests.post(
        meta["uploadUrl"],
        data=fields,
        files={"file": (asset_name, file_bytes, "image/png")},
        timeout=60,
    )
    if upload_resp.status_code not in (200, 201, 204):
        raise RuntimeError(f"S3 upload failed: {upload_resp.status_code} {upload_resp.text[:200]}")

    return {"asset_id": meta["id"], "url": meta.get("hostedUrl", "")}


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
      3. Upload header to Webflow Assets
    Returns dict with local paths and Webflow asset info.
    """
    if output_dir is None:
        slug = month_label.lower().replace(" ", "-")
        output_dir = Path(__file__).parent.parent / "output" / slug
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"  📸 Fetching performer photos from Notion ({len(performer_ids)} performers)…")
    photos  = fetch_performer_photos(performer_ids, limit=16)
    present = sum(1 for p in photos if p is not None)
    print(f"     {present}/{min(len(performer_ids), 16)} photos fetched successfully.")

    slug        = month_label.lower().replace(" ", "-")
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
        "story_path":        str(story_path),
        "header_path":       str(header_path),
        "webflow_asset_id":  asset_info["asset_id"],
        "webflow_asset_url": asset_info["url"],
    }
