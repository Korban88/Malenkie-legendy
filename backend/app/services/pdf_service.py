import logging
import random
import struct
import uuid
from pathlib import Path

from fpdf import FPDF

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# ── Font paths ───────────────────────────────────────────────────────────────
_FONTS_DIR = Path('/opt/malenkie-legendy/backend/app/fonts')

_REGULAR_CANDIDATES = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans.ttf',
    '/usr/share/fonts/truetype/DejaVuSans.ttf',
    '/usr/share/fonts/TTF/DejaVuSans.ttf',
]
_BOLD_CANDIDATES = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/truetype/DejaVuSans-Bold.ttf',
    '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf',
]
_ITALIC_CANDIDATES = [
    '/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf',
    '/usr/share/fonts/dejavu/DejaVuSans-Oblique.ttf',
    '/usr/share/fonts/truetype/DejaVuSans-Oblique.ttf',
    '/usr/share/fonts/TTF/DejaVuSans-Oblique.ttf',
]

# Fairy-tale Cyrillic font (Neucha — handwritten, child-friendly)
_FAIRY_FONT_PATH = _FONTS_DIR / 'Neucha-Regular.ttf'


def _ensure_fairy_font() -> str | None:
    """Return path to Neucha font if present on disk."""
    if _FAIRY_FONT_PATH.exists():
        return str(_FAIRY_FONT_PATH)
    logger.warning('Neucha font not found at %s', _FAIRY_FONT_PATH)
    return None


# ── Page geometry (A4) ───────────────────────────────────────────────────────
PAGE_W = 210
PAGE_H = 297
MARGIN_OUTER = 18
MARGIN_TOP = 22
MARGIN_BOTTOM = 22
CONTENT_W = PAGE_W - 2 * MARGIN_OUTER   # 174 mm

# Image display width = full content width
IMG_W = CONTENT_W          # 174 mm
# IMG_H is computed per-image from actual pixel dimensions (see _get_img_display_h)
# Fallback ratio used only for space estimation
_IMG_H_FALLBACK = IMG_W    # assume square (1024×1024) by default
IMG_TOTAL = _IMG_H_FALLBACK + 4 + 4 + 10   # used for rough space checks

# ── Universal noble "old book" palette ───────────────────────────────────────
# Warm parchment background with antique mahogany / gold accents.
# Same for all genders — "общий благородный цвет".
_BOOK = {
    'BG':       (252, 248, 233),   # aged parchment
    'HDR':      (48,  28,  12),    # deep mahogany (like old leather cover)
    'HDR_TXT':  (252, 248, 233),   # cream text on dark header
    'BODY':     (28,  16,   8),    # very dark warm brown body text
    'ACC':      (148, 108,  40),   # antique gold accents
    'RHD':      (95,  65,  30),    # warm medium brown running header
    'TTL':      (68,  32,  10),    # dark mahogany title
    'IMG_BRD':  (168, 120,  46),   # antique gold frame
    'HOOK_BG':  (244, 238, 215),   # slightly darker parchment
    'TEX':      (228, 216, 196),   # paper grain dots (clearly darker than BG)
}
_PALETTE = {
    'female':  _BOOK,
    'male':    _BOOK,
    'neutral': _BOOK,
}

# Pre-computed texture points with fixed seed — same grain on every page
_TEX_RNG = random.Random(2025)
_TEX_POINTS = [
    (_TEX_RNG.uniform(1, PAGE_W - 1), _TEX_RNG.uniform(1, PAGE_H - 1),
     _TEX_RNG.uniform(0.5, 1.2))
    for _ in range(500)
]


def _to_genitive(name: str) -> str:
    if not name:
        return name
    n = name.strip()
    if len(n) < 2:
        return n
    last = n[-1].lower()
    if last == 'а':
        return n[:-1] + 'и'
    if last == 'я':
        return n[:-1] + 'и'
    if last == 'й':
        return n[:-1] + 'я'
    if last == 'ь':
        return n[:-1] + 'я'
    consonants = 'бвгджзклмнпрстфхцчшщ'
    if last in consonants:
        return n + 'а'
    return n


def _find_font(candidates: list[str], label: str) -> str:
    for path in candidates:
        if Path(path).exists():
            return path
    raise RuntimeError(f'Font {label} not found. Run: apt-get install fonts-dejavu-core')


def _get_img_display_h(path: Path, display_w: float) -> float:
    """Return display height that preserves the image's actual aspect ratio."""
    try:
        with open(path, 'rb') as f:
            header = f.read(24)
        # PNG: signature (8) + chunk length (4) + 'IHDR' (4) + width (4) + height (4)
        if header[:8] == b'\x89PNG\r\n\x1a\n' and header[12:16] == b'IHDR':
            px_w = struct.unpack('>I', header[16:20])[0]
            px_h = struct.unpack('>I', header[20:24])[0]
            if px_w > 0:
                return display_w * px_h / px_w
    except Exception:
        pass
    return _IMG_H_FALLBACK  # fallback: assume square


def _url_to_local_path(url: str) -> Path | None:
    try:
        filename = url.rstrip('/').split('/')[-1]
        path = Path(settings.images_dir) / filename
        return path if path.exists() else None
    except Exception:
        return None


# ── Drawing helpers ──────────────────────────────────────────────────────────

def _fill_bg(pdf: FPDF, C: dict) -> None:
    """Fill page with parchment color, then overlay subtle paper grain texture."""
    r, g, b = C['BG']
    pdf.set_fill_color(r, g, b)
    pdf.rect(0, 0, PAGE_W, PAGE_H, style='F')
    # Paper grain — visible dots, fixed pattern
    tr, tg, tb = C['TEX']
    pdf.set_fill_color(tr, tg, tb)
    for (x, y, size) in _TEX_POINTS:
        pdf.ellipse(x, y, size, size, style='F')


def _draw_corner_ornaments(pdf: FPDF, C: dict, margin: float = 10.0, size: float = 8.0) -> None:
    r, g, b = C['ACC']
    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(0.5)
    for (cx, cy, sx, sy) in [
        (margin, margin, size, size),
        (PAGE_W - margin, margin, -size, size),
        (margin, PAGE_H - margin, size, -size),
        (PAGE_W - margin, PAGE_H - margin, -size, -size),
    ]:
        pdf.line(cx, cy, cx + sx, cy)
        pdf.line(cx, cy, cx, cy + sy)


def _draw_ornament_divider(pdf: FPDF, C: dict) -> None:
    cy = pdf.get_y() + 3
    cx = PAGE_W / 2
    r, g, b = C['ACC']
    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(0.3)
    pdf.line(cx - 30, cy, cx - 6, cy)
    pdf.line(cx + 6,  cy, cx + 30, cy)
    pdf.set_fill_color(r, g, b)
    pdf.ellipse(cx - 2, cy - 2, 4, 4, style='F')
    pdf.set_y(pdf.get_y() + 8)


def _draw_page_number(pdf: FPDF, C: dict, page_num: int) -> None:
    r, g, b = C['RHD']
    pdf.set_y(PAGE_H - MARGIN_BOTTOM + 4)
    pdf.set_font('DejaVu', style='', size=8)
    pdf.set_text_color(r, g, b)
    pdf.set_x(MARGIN_OUTER)
    pdf.cell(CONTENT_W, 5, f'— {page_num} —', align='C')


def _draw_running_header(pdf: FPDF, C: dict, title: str) -> None:
    r, g, b = C['RHD']
    pdf.set_y(10)
    pdf.set_font('DejaVu', style='', size=7.5)
    pdf.set_text_color(r, g, b)
    pdf.set_x(MARGIN_OUTER)
    display = title if len(title) <= 50 else title[:47] + '...'
    pdf.cell(CONTENT_W, 5, display, align='C')
    ar, ag, ab = C['ACC']
    pdf.set_draw_color(ar, ag, ab)
    pdf.set_line_width(0.2)
    y = pdf.get_y() + 5
    pdf.line(MARGIN_OUTER, y, PAGE_W - MARGIN_OUTER, y)


def _draw_framed_image(pdf: FPDF, C: dict, img_path: Path,
                       x: float, y: float, w: float, h: float,
                       frame_pad: float = 2.0) -> None:
    r, g, b = C['IMG_BRD']
    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(0.8)
    pdf.rect(x - frame_pad, y - frame_pad, w + frame_pad * 2, h + frame_pad * 2)
    pdf.set_line_width(0.2)
    pdf.rect(x - frame_pad - 2, y - frame_pad - 2,
             w + (frame_pad + 2) * 2, h + (frame_pad + 2) * 2)
    try:
        pdf.image(str(img_path), x=x, y=y, w=w, h=h)
    except Exception as e:
        logger.warning('Image render failed: %s', e)


def _draw_wide_image(pdf: FPDF, C: dict, img_path: Path) -> None:
    """Draw image at full content width, preserving the image's actual aspect ratio."""
    display_h = _get_img_display_h(img_path, IMG_W)
    iy = pdf.get_y() + 3
    _draw_framed_image(pdf, C, img_path, MARGIN_OUTER, iy, IMG_W, display_h, frame_pad=2)
    pdf.set_y(iy + display_h + 4 + 8)


def _draw_hook_box(pdf: FPDF, C: dict, hook_text: str) -> None:
    pdf.set_font('DejaVu', style='', size=10)
    lines = pdf.multi_cell(CONTENT_W - 12, 7, hook_text, align='C',
                           dry_run=True, output='LINES',
                           new_x='LMARGIN', new_y='NEXT')
    text_h = len(lines) * 7
    box_h = text_h + 20

    bx = MARGIN_OUTER
    by = pdf.get_y() + 4
    hr, hg, hb = C['HOOK_BG']
    pdf.set_fill_color(hr, hg, hb)
    pdf.rect(bx, by, CONTENT_W, box_h, style='F')
    ar, ag, ab = C['ACC']
    pdf.set_draw_color(ar, ag, ab)
    pdf.set_line_width(0.6)
    pdf.rect(bx, by, CONTENT_W, box_h)
    pdf.set_line_width(0.2)
    pdf.rect(bx + 2, by + 2, CONTENT_W - 4, box_h - 4)

    pdf.set_y(by + 5)
    pdf.set_font('DejaVu', style='B', size=8)
    pdf.set_text_color(ar, ag, ab)
    pdf.set_x(MARGIN_OUTER)
    pdf.cell(CONTENT_W, 5, '✦  Что будет в следующий раз...  ✦', align='C')
    pdf.ln(5)

    tr, tg, tb = C['TTL']
    pdf.set_font('DejaVu', style='I', size=10)
    pdf.set_text_color(tr, tg, tb)
    pdf.set_x(MARGIN_OUTER + 6)
    pdf.multi_cell(CONTENT_W - 12, 7, hook_text, align='C',
                   new_x='LMARGIN', new_y='NEXT')
    pdf.set_y(by + box_h + 6)


# ── Main generator ───────────────────────────────────────────────────────────

def generate_pdf(title: str, story_text: str, image_urls: list[str],
                 episode_number: int = 1, child_name: str = '',
                 next_hook: str = '', gender: str = 'neutral') -> str:
    out_dir = Path(settings.stories_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.pdf'
    full_path = out_dir / filename

    C = _PALETTE.get(gender, _BOOK)

    try:
        regular = _find_font(_REGULAR_CANDIDATES, 'regular')
        bold = _find_font(_BOLD_CANDIDATES, 'bold')
        italic_path = next((c for c in _ITALIC_CANDIDATES if Path(c).exists()), regular)
        fairy_font = _ensure_fairy_font()

        pdf = FPDF()
        pdf.set_auto_page_break(auto=False)
        pdf.add_font('DejaVu', style='',  fname=regular)
        pdf.add_font('DejaVu', style='B', fname=bold)
        pdf.add_font('DejaVu', style='I', fname=italic_path)
        has_fairy = False
        if fairy_font:
            try:
                pdf.add_font('Fairy', style='', fname=fairy_font)
                has_fairy = True
            except Exception as e:
                logger.warning('Fairy font load failed: %s', e)

        local_images: list[Path | None] = [_url_to_local_path(u) for u in image_urls]

        # ── Image slot assignments ───────────────────────────────────────────
        # [0] = cover character portrait
        # [1-5] = one image per chapter (chapters 0-4)
        # [6] = animal companion (shown once at end)
        # [7] = final/triumph scene
        def _img(idx: int) -> Path | None:
            return local_images[idx] if idx < len(local_images) else None

        # Image slots: [0]=cover, [1-5]=one per chapter (5 chapters)
        cover_img    = _img(0)
        chapter_imgs = [_img(i) for i in range(1, 6)]   # one image per chapter

        rr, rg, rb = C['RHD']
        ar, ag, ab = C['ACC']
        tr, tg, tb = C['TTL']
        br, bg, bb = C['BODY']
        hr2, hg2, hb2 = C['HDR']
        ht_r, ht_g, ht_b = C['HDR_TXT']

        def _title_font(size: float) -> None:
            if has_fairy:
                pdf.set_font('Fairy', style='', size=size)
            else:
                pdf.set_font('DejaVu', style='B', size=size)

        # ── PAGE 1: Cover ─────────────────────────────────────────────────────
        pdf.add_page()
        _fill_bg(pdf, C)
        _draw_corner_ornaments(pdf, C, margin=12, size=14)

        # Series label
        pdf.set_y(18)
        pdf.set_font('DejaVu', style='I', size=10)
        pdf.set_text_color(rr, rg, rb)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 7, 'Маленькие легенды', align='C', new_x='LMARGIN', new_y='NEXT')
        pdf.set_draw_color(ar, ag, ab)
        pdf.set_line_width(0.4)
        cx = PAGE_W / 2
        y0 = pdf.get_y() + 2
        pdf.line(cx - 55, y0, cx + 55, y0)
        pdf.set_y(y0 + 6)

        if episode_number > 1:
            pdf.set_font('DejaVu', style='', size=9)
            pdf.set_text_color(ar, ag, ab)
            pdf.set_x(MARGIN_OUTER)
            pdf.multi_cell(CONTENT_W, 6, f'✦  Эпизод {episode_number}  ✦', align='C',
                           new_x='LMARGIN', new_y='NEXT')
            pdf.ln(4)

        # Cover: actual aspect ratio (no squishing)
        if cover_img:
            cov_w = CONTENT_W
            cov_h = _get_img_display_h(cover_img, cov_w)
            cov_x = MARGIN_OUTER
            cov_y = pdf.get_y() + 2
            try:
                pdf.image(str(cover_img), x=cov_x, y=cov_y, w=cov_w, h=cov_h)
            except Exception as e:
                logger.warning('Cover image render failed: %s', e)
            pdf.set_y(cov_y + cov_h + 6)
        else:
            pdf.ln(30)

        # Title — fairy-tale font on cover
        _title_font(26)
        pdf.set_text_color(tr, tg, tb)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 14, title, align='C', new_x='LMARGIN', new_y='NEXT')
        pdf.ln(6)

        _draw_ornament_divider(pdf, C)

        name_gen = _to_genitive(child_name) if child_name else ''
        dedication = f'Персональная сказка для {name_gen}' if name_gen else 'Персональная сказка'
        pdf.set_font('DejaVu', style='I', size=9.5)
        pdf.set_text_color(rr, rg, rb)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 6, dedication, align='C', new_x='LMARGIN', new_y='NEXT')
        pdf.ln(3)
        pdf.set_font('DejaVu', style='', size=8)
        pdf.set_text_color(ar, ag, ab)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 5, '✦  Маленькие легенды  ✦', align='C', new_x='LMARGIN', new_y='NEXT')

        # ── Parse story into chapters ─────────────────────────────────────────
        paragraphs = [p.strip() for p in story_text.split('\n\n') if p.strip()]
        chapters: list[tuple[str, list[str]]] = []
        current_chapter_title = ''
        current_paras: list[str] = []

        for para in paragraphs:
            if para.startswith('Глава'):
                if current_chapter_title or current_paras:
                    chapters.append((current_chapter_title, current_paras))
                current_chapter_title = para
                current_paras = []
            else:
                current_paras.append(para)
        if current_chapter_title or current_paras:
            chapters.append((current_chapter_title, current_paras))

        page_num = 1

        def new_story_page():
            nonlocal page_num
            page_num += 1
            pdf.add_page()
            _fill_bg(pdf, C)
            _draw_running_header(pdf, C, title)
            _draw_page_number(pdf, C, page_num)
            pdf.set_y(MARGIN_TOP + 8)

        def content_bottom() -> float:
            return PAGE_H - MARGIN_BOTTOM - 12

        def space_left() -> float:
            return content_bottom() - pdf.get_y()

        for ch_idx, (chapter_title, paras) in enumerate(chapters):
            new_story_page()

            # Chapter header — visually distinct: larger, bolder, framed with rules
            if chapter_title:
                pdf.ln(10)
                # Top decorative rule
                ar2, ag2, ab2 = C['ACC']
                pdf.set_draw_color(ar2, ag2, ab2)
                pdf.set_line_width(0.6)
                pdf.line(MARGIN_OUTER, pdf.get_y(), PAGE_W - MARGIN_OUTER, pdf.get_y())
                pdf.ln(5)
                if has_fairy:
                    pdf.set_font('Fairy', style='', size=23)
                else:
                    pdf.set_font('DejaVu', style='B', size=23)
                pdf.set_text_color(tr, tg, tb)
                pdf.set_x(MARGIN_OUTER)
                pdf.multi_cell(CONTENT_W, 14, chapter_title, align='C', new_x='LMARGIN', new_y='NEXT')
                pdf.ln(4)
                # Bottom decorative rule
                pdf.set_draw_color(ar2, ag2, ab2)
                pdf.set_line_width(0.4)
                pdf.line(MARGIN_OUTER + 20, pdf.get_y(), PAGE_W - MARGIN_OUTER - 20, pdf.get_y())
                pdf.ln(10)

            # ── Chapter image: ONE unique image per chapter, shown ONCE ───────
            # chapter[0]→img[1], chapter[1]→img[2], ..., chapter[4]→img[5]
            ch_img = chapter_imgs[ch_idx] if ch_idx < len(chapter_imgs) else None
            if ch_img and space_left() >= IMG_TOTAL:
                _draw_wide_image(pdf, C, ch_img)
            elif ch_img:
                # Not enough space — start new page for image
                new_story_page()
                _draw_wide_image(pdf, C, ch_img)

            # Body paragraphs — continuation pages get NO image (pure text)
            for para in paras:
                # Set body font BEFORE dry_run so line-count estimate matches actual render font
                pdf.set_font('DejaVu', style='', size=12)
                pdf.set_text_color(br, bg, bb)
                lines = pdf.multi_cell(CONTENT_W, 7.5, para, align='J',
                                       new_x='LMARGIN', new_y='NEXT', dry_run=True, output='LINES')
                text_h = len(lines) * 7.5 + 4

                if space_left() < text_h:
                    new_story_page()

                # Always re-set font right before actual render (guard against any state drift)
                pdf.set_font('DejaVu', style='', size=12)
                pdf.set_text_color(br, bg, bb)
                pdf.set_x(MARGIN_OUTER)
                pdf.multi_cell(CONTENT_W, 7.5, para, align='J', new_x='LMARGIN', new_y='NEXT')
                pdf.ln(4)

        # ── Next-hook teaser ─────────────────────────────────────────────────
        if next_hook:
            if space_left() < 60:
                new_story_page()
            _draw_hook_box(pdf, C, next_hook)

        # ── "The End" ─────────────────────────────────────────────────────────
        if space_left() < 45:
            new_story_page()
        _draw_ornament_divider(pdf, C)
        _title_font(22)
        pdf.set_text_color(tr, tg, tb)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 14, '✦  Конец  ✦', align='C', new_x='LMARGIN', new_y='NEXT')
        pdf.ln(6)
        farewell = f'{child_name}, до встречи в будущих приключениях!' if child_name else 'До встречи в будущих приключениях!'
        pdf.set_font('DejaVu', style='I', size=11)
        pdf.set_text_color(rr, rg, rb)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 7, farewell, align='C', new_x='LMARGIN', new_y='NEXT')

        pdf.output(str(full_path))
        logger.info('PDF generated: %s (%d bytes, %d pages)', filename, full_path.stat().st_size, page_num)

    except Exception as exc:
        logger.exception('PDF generation failed: %s', exc)
        raise

    return f'{settings.public_base_url}/files/stories/{filename}'
