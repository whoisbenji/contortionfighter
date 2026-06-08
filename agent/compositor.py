"""
Image compositor for the monthly performance review.

Reads performer photos from Notion ICPDB, composites them into a dynamic
scattered-card layout on a dark background, and outputs two formats:
  • Instagram Story  — 1080 × 1920 px  (9:16)  — has title text
  • Article header   — 1500 × 844 px   (16:9)  — no text
"""

from __future__ import annotations

import io
import math
import os
import re
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from .config import NOTION_BASE, NOTION_ICPDB_DS


# ── Constants ─────────────────────────────────────────────────────────────────

CARD_ROTATION = 15   # degrees; alternated ±per card
BG_COLOUR     = "#090909"
TEXT_COLOUR   = (255, 255, 255)

# Bounding-box multiplier for a square rotated CARD_ROTATION degrees
_BB_MULT = math.cos(math.radians(CARD_ROTATION)) + math.sin(math.radians(CARD_ROTATION))


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


# ── Layout computation ────────────────────────────────────────────────────────

def _compute_layout(
    n: int,
    canvas_w: int,
    photo_area_h: int,
    max_card: int = 420,
) -> list[tuple[int, int, int]]:
    """
    Return (cx, cy, card_size_px) for n photos arranged without overlap.
    Cards are guaranteed non-overlapping accounting for rotation bounding boxes.
    """
    if n == 0:
        return []

    gap = 28       # minimum gap between bounding boxes in px
    nudge = 0.025  # max nudge as fraction of cell (keeps visual variety within safe bounds)

    best: tuple | None = None
    for cols in range(1, min(n + 1, 6)):
        rows = math.ceil(n / cols)
        # shrink usable area by 2*nudge on each axis to keep nudged cards from overlapping
        usable_w = canvas_w    * (1 - 2 * nudge)
        usable_h = photo_area_h * (1 - 2 * nudge)
        card_w = (usable_w  - gap * (cols + 1)) / cols / _BB_MULT
        card_h = (usable_h  - gap * (rows + 1)) / rows / _BB_MULT
        card = min(card_w, card_h, max_card)
        if card < 60:
            continue
        score = card * 10 - rows * 4 - abs(cols - rows) * 2
        if best is None or score > best[0]:
            best = (score, cols, rows, int(card))

    if best is None:
        return []

    _, cols, rows, card = best
    cell_w = canvas_w / cols
    cell_h = photo_area_h / rows

    # Deterministic nudges to break up the grid feel (bounded by nudge fraction)
    nudges = [
        ( 0.00,  0.00), ( 0.02, -0.02), (-0.02,  0.02),
        ( 0.02,  0.02), (-0.02, -0.02), ( 0.01,  0.02),
        (-0.02, -0.01), ( 0.02, -0.01),
    ]

    positions: list[tuple[int, int, int]] = []
    idx = 0
    for row in range(rows):
        n_in_row = min(cols, n - row * cols)
        row_w = n_in_row * cell_w
        x_start = (canvas_w - row_w) / 2 + cell_w / 2
        for col in range(n_in_row):
            cx = x_start + col * cell_w
            cy = cell_h * (row + 0.5)
            dx, dy = nudges[idx % len(nudges)]
            cx += dx * cell_w
            cy += dy * cell_h
            positions.append((int(cx), int(cy), card))
            idx += 1

    return positions


# ── Core compositing ──────────────────────────────────────────────────────────

def _paste_card(
    canvas: Image.Image,
    photo: Image.Image,
    cx: int,
    cy: int,
    card_px: int,
    radius_px: int,
    rotation: float,
) -> None:
    w, h = photo.size
    min_side = min(w, h)
    left = (w - min_side) // 2
    top  = (h - min_side) // 2
    photo = photo.crop((left, top, left + min_side, top + min_side))
    photo = photo.resize((card_px, card_px), Image.LANCZOS).convert("RGBA")

    mask = _rounded_mask(card_px, radius_px)
    photo.putalpha(mask)

    rotated = photo.rotate(-rotation, expand=True, resample=Image.BICUBIC)

    paste_x = cx - rotated.width  // 2
    paste_y = cy - rotated.height // 2
    canvas.paste(rotated, (paste_x, paste_y), rotated)


def _build_canvas(
    photos: list[Image.Image | None],
    out_w: int,
    out_h: int,
    photo_area_h: int,
    month_label: str | None = None,
    title_x: int = 80,
    title_y: int | None = None,
    font_size: int = 78,
) -> Image.Image:
    canvas = Image.new("RGBA", (out_w, out_h), BG_COLOUR)

    valid = [p for p in photos if p is not None]
    if valid:
        positions = _compute_layout(len(valid), out_w, photo_area_h)
        for i, (photo, (cx, cy, card_px)) in enumerate(zip(valid, positions)):
            rotation = CARD_ROTATION if i % 2 == 0 else -CARD_ROTATION
            radius_px = max(4, int(card_px * 0.10))
            try:
                _paste_card(canvas, photo, cx, cy, card_px, radius_px, rotation)
            except Exception as exc:
                print(f"  ⚠ Skipped card {i}: {exc}")

    if month_label is not None:
        draw = ImageDraw.Draw(canvas)
        font = _load_font(font_size)
        ty = title_y if title_y is not None else photo_area_h + 40
        draw.text((title_x, ty), f"{month_label}\nperformances", font=font, fill=TEXT_COLOUR)

    return canvas.convert("RGB")


# ── Public render functions ───────────────────────────────────────────────────

def render_story(
    month_label: str,
    photos: list[Image.Image | None],
    output_path: str | Path,
) -> Path:
    """Render a 1080 × 1920 Instagram Story PNG with title text."""
    out_w, out_h = 1080, 1920
    # Reserve bottom ~460px for the title block
    photo_area_h = 1460

    canvas = _build_canvas(
        photos=photos,
        out_w=out_w,
        out_h=out_h,
        photo_area_h=photo_area_h,
        month_label=month_label,
        title_x=80,
        title_y=1500,
        font_size=78,
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
    """Render a 1500 × 844 article header PNG (no text)."""
    out_w, out_h = 1500, 844

    canvas = _build_canvas(
        photos=photos,
        out_w=out_w,
        out_h=out_h,
        photo_area_h=out_h,
        month_label=None,
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
