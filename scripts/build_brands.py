"""Build the Home Assistant brand images from the raw artwork.

Sources (repository root): icon_raw.jpeg, logo_raw.jpeg

Outputs go to custom_components/mysql_query/brand/, which Home Assistant 2026.3+ reads
directly; local brand images take priority over the brands CDN. Sizes follow the
home-assistant/brands conventions:

  icon.png       256x256   outer black background keyed out, 1:1
  icon@2x.png    512x512   same, hDPI
  logo.png       256x64    icon mark from logo_raw plus a typeset wordmark
  logo@2x.png    512x128   same, hDPI

Run it with any Python that has Pillow and numpy available:  python scripts/build_brands.py
"""

import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
BRAND_DIR = REPO / "custom_components" / "mysql_query" / "brand"

# Alpha ramp over the max colour channel: transparent at/below LO, opaque at/above HI.
LO, HI = 8, 38
# Only pixels connected to the border and at/below this value count as background.
FLOOD = 38
BBOX_ALPHA = 48

TEXT = "MySQL Query"
TEXT_COLOR = (3, 169, 244)  # #03A9F4 - readable on both light and dark backgrounds
FONT_CANDIDATES = (
    "segoeui.ttf",
    "arial.ttf",
    "VerdanaPro-Regular.ttf",
    "DejaVuSans.ttf",
)
SS = 4  # supersampling factor for crisp glyph edges


def find_font(size: int) -> ImageFont.FreeTypeFont:
    fonts_dir = Path(os.environ.get("WINDIR", "/usr/share")) / "Fonts"
    for name in FONT_CANDIDATES:
        for candidate in (str(fonts_dir / name), name):
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    raise RuntimeError("no usable sans-serif font found")


def flood(candidate: np.ndarray, seeds) -> np.ndarray:
    """Scanline flood fill of `candidate` starting from `seeds`."""
    h, w = candidate.shape
    filled = np.zeros_like(candidate)
    stack = [s for s in seeds if candidate[s]]

    while stack:
        y, x = stack.pop()
        if filled[y, x] or not candidate[y, x]:
            continue
        left = x
        while left > 0 and candidate[y, left - 1] and not filled[y, left - 1]:
            left -= 1
        right = x
        while right < w - 1 and candidate[y, right + 1] and not filled[y, right + 1]:
            right += 1
        filled[y, left : right + 1] = True
        for ny in (y - 1, y + 1):
            if not 0 <= ny < h:
                continue
            open_run = candidate[ny, left : right + 1] & ~filled[ny, left : right + 1]
            idx = np.nonzero(open_run)[0]
            if idx.size:
                starts = idx[np.concatenate(([True], np.diff(idx) > 1))]
                stack.extend((ny, left + int(s)) for s in starts)
    return filled


def border_seeds(shape) -> list:
    h, w = shape
    return (
        [(0, x) for x in range(w)]
        + [(h - 1, x) for x in range(w)]
        + [(y, 0) for y in range(h)]
        + [(y, w - 1) for y in range(h)]
    )


def soft_alpha(lum: np.ndarray) -> np.ndarray:
    """Alpha ramp over the max colour channel, so anti-aliased edges stay smooth."""
    return np.clip((lum - LO) / (HI - LO), 0.0, 1.0)


def compose(rgb: np.ndarray, alpha: np.ndarray) -> Image.Image:
    """Build an RGBA image, un-premultiplying edges (source was composited over black)."""
    out = rgb.copy()
    edge = (alpha > 0.0) & (alpha < 1.0)
    out[edge] = np.clip(rgb[edge] / alpha[edge][:, None], 0, 255)
    return Image.fromarray(
        np.dstack([out, alpha * 255.0]).round().astype(np.uint8), "RGBA"
    )


def key_black(path: Path) -> Image.Image:
    """Make only the OUTER black background transparent.

    Dark pixels enclosed by the artwork are unreachable from the border, so they stay
    opaque here; `drop_enclosed_background` decides afterwards which of those pockets
    are design detail and which are background showing through open line art.
    """
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.float32)
    lum = rgb.max(axis=2)

    outer = flood(lum <= FLOOD, border_seeds(lum.shape))
    print(
        f"  outer background {outer.mean():.1%} -> transparent; enclosed dark {((lum <= FLOOD) & ~outer).mean():.2%} -> pending"
    )

    return compose(rgb, np.where(outer, soft_alpha(lum), 1.0))


def drop_enclosed_background(
    img: Image.Image, rel_threshold: float = 0.001
) -> Image.Image:
    """Clear enclosed black pockets that are background, keeping small black details.

    The wireframe cube and the network web are open line art: the black between their
    strokes is background that the border fill cannot reach. Genuine black details
    (the dolphin eye) are tiny by comparison, so area relative to the artwork decides.
    Coloured dark elements (rings, window panes, nodes) sit above FLOOD and are never
    candidates in the first place.
    """
    arr = np.asarray(img).astype(np.float32)
    rgb, alpha = arr[:, :, :3], arr[:, :, 3] / 255.0
    lum = rgb.max(axis=2)

    ys, xs = np.nonzero(alpha * 255 >= BBOX_ALPHA)
    area = (xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)
    min_size = max(2, round(area * rel_threshold))

    remaining = (alpha >= 1.0) & (lum <= FLOOD)
    dropped = np.zeros_like(remaining)
    kept = []
    while remaining.any():
        cy, cx = np.nonzero(remaining)
        pocket = flood(remaining, [(int(cy[0]), int(cx[0]))])
        size = int(pocket.sum())
        if size >= min_size:
            dropped |= pocket
        elif size > 1:
            kept.append(size)
        remaining &= ~pocket

    print(
        f"  enclosed pockets: cleared {int(dropped.sum())}px above the {min_size}px threshold, kept {len(kept)} small detail(s) {sorted(kept, reverse=True)}"
    )
    return compose(rgb, np.where(dropped, soft_alpha(lum), alpha))


def trim(img: Image.Image, threshold: int = BBOX_ALPHA) -> Image.Image:
    ys, xs = np.nonzero(np.asarray(img)[:, :, 3] >= threshold)
    return img.crop(
        (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    )


def split_off_mark(img: Image.Image) -> Image.Image:
    """Return just the icon mark: everything left of the widest empty column gap."""
    empty = np.asarray(img)[:, :, 3].max(axis=0) < BBOX_ALPHA
    runs, start = [], None
    for x, is_empty in enumerate(empty):
        if is_empty and start is None:
            start = x
        elif not is_empty and start is not None:
            runs.append((start, x))
            start = None
    if start is not None:
        runs.append((start, len(empty)))
    gap = max(runs, key=lambda run: run[1] - run[0])
    print(
        f"  widest empty gap: x {gap[0]}-{gap[1]} ({gap[1] - gap[0]}px) -> mark is everything left of it"
    )
    return trim(img.crop((0, 0, gap[0], img.height)))


def fit_center(img: Image.Image, width: int, height: int) -> Image.Image:
    scale = min(width / img.width, height / img.height)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(
        img.resize(size, Image.LANCZOS),
        ((width - size[0]) // 2, (height - size[1]) // 2),
    )
    print(f"  artwork {size[0]}x{size[1]} centred on {width}x{height}")
    return canvas


def render_text(text: str, max_width: int, max_height: int) -> Image.Image:
    """Typeset `text` as large as fits the box, returned tightly cropped."""
    size = 8
    while size < 400:
        probe = find_font((size + 1) * SS)
        left, top, right, bottom = probe.getbbox(text)
        if (right - left) / SS > max_width or (bottom - top) / SS > max_height:
            break
        size += 1

    font = find_font(size * SS)
    left, top, right, bottom = font.getbbox(text)
    pad = 2 * SS
    layer = Image.new(
        "RGBA", (right - left + 2 * pad, bottom - top + 2 * pad), (0, 0, 0, 0)
    )
    ImageDraw.Draw(layer).text(
        (pad - left, pad - top), text, font=font, fill=(*TEXT_COLOR, 255)
    )
    layer = trim(layer, threshold=1)
    layer = layer.resize(
        (max(1, round(layer.width / SS)), max(1, round(layer.height / SS))),
        Image.LANCZOS,
    )
    print(f"  wordmark at {size}px -> {layer.width}x{layer.height}")
    return layer


def build_logo(mark: Image.Image, width: int, height: int) -> Image.Image:
    """Lay out the mark and the wordmark on a transparent canvas of the given size."""
    scale = height / 128
    mark_height, gap, margin = round(104 * scale), round(22 * scale), round(12 * scale)

    mark = mark.resize(
        (max(1, round(mark.width * mark_height / mark.height)), mark_height),
        Image.LANCZOS,
    )
    text_layer = render_text(
        TEXT, width - mark.width - gap - 2 * margin, round(74 * scale)
    )

    block = mark.width + gap + text_layer.width
    x = (width - block) // 2
    logo = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    logo.alpha_composite(mark, (x, (height - mark.height) // 2))
    logo.alpha_composite(
        text_layer, (x + mark.width + gap, (height - text_layer.height) // 2)
    )
    print(
        f"  mark {mark.width}px + gap {gap} + text {text_layer.width}px = {block}px block, centred on {width}x{height}"
    )
    return logo


def save(img: Image.Image, name: str) -> None:
    """Write the image to the integration's brand/ folder."""
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    img.save(BRAND_DIR / name, "PNG", optimize=True)
    a = np.asarray(img)[:, :, 3]
    print(
        f"  {name:<14} {img.width}x{img.height} RGBA, corner alpha {a[0, 0]}/{a[0, -1]}/{a[-1, 0]}/{a[-1, -1]}, {(a == 0).mean():.1%} transparent"
    )


print("icon_raw.jpeg -> icon.png, icon@2x.png")
icon_art = drop_enclosed_background(trim(key_black(REPO / "icon_raw.jpeg")))
save(fit_center(icon_art, 256, 256), "icon.png")
save(fit_center(icon_art, 512, 512), "icon@2x.png")

print("logo_raw.jpeg -> logo.png, logo@2x.png")
# Trim the mark out first: the pocket threshold is relative to the artwork it belongs to.
mark_art = trim(
    drop_enclosed_background(split_off_mark(trim(key_black(REPO / "logo_raw.jpeg"))))
)
save(build_logo(mark_art, 256, 64), "logo.png")
save(build_logo(mark_art, 512, 128), "logo@2x.png")
