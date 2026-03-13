import logging
import uuid
from pathlib import Path

from fpdf import FPDF

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# ── Font paths ───────────────────────────────────────────────────────────────
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

# ── Page geometry (A4) ───────────────────────────────────────────────────────
PAGE_W = 210
PAGE_H = 297
MARGIN_OUTER = 18   # left/right
MARGIN_TOP = 22
MARGIN_BOTTOM = 22
CONTENT_W = PAGE_W - 2 * MARGIN_OUTER

# ── Color palette ────────────────────────────────────────────────────────────
# Warm cream background
BG_R, BG_G, BG_B = 255, 252, 242
# Chapter header band
HDR_R, HDR_G, HDR_B = 120, 60, 20
# Header text (on dark band)
HDR_TXT_R, HDR_TXT_G, HDR_TXT_B = 255, 245, 225
# Body text
BODY_R, BODY_G, BODY_B = 35, 18, 8
# Accent / ornaments
ACC_R, ACC_G, ACC_B = 180, 110, 40
# Running header / page number
RHD_R, RHD_G, RHD_B = 160, 100, 50
# Title page title
TTL_R, TTL_G, TTL_B = 80, 35, 10
# Image border
IMG_BRD_R, IMG_BRD_G, IMG_BRD_B = 160, 110, 50


def _find_font(candidates: list[str], label: str) -> str:
    for path in candidates:
        if Path(path).exists():
            return path
    raise RuntimeError(f'Font {label} not found. Run: apt-get install fonts-dejavu-core')


def _url_to_local_path(url: str) -> Path | None:
    try:
        filename = url.rstrip('/').split('/')[-1]
        path = Path(settings.images_dir) / filename
        return path if path.exists() else None
    except Exception:
        return None


# ── Drawing helpers ──────────────────────────────────────────────────────────

def _fill_bg(pdf: FPDF) -> None:
    """Fill the entire page with warm cream background."""
    pdf.set_fill_color(BG_R, BG_G, BG_B)
    pdf.rect(0, 0, PAGE_W, PAGE_H, style='F')


def _draw_corner_ornaments(pdf: FPDF, margin: float = 10.0, size: float = 8.0) -> None:
    """Draw simple decorative L-shapes in all four corners."""
    pdf.set_draw_color(ACC_R, ACC_G, ACC_B)
    pdf.set_line_width(0.5)
    for (cx, cy, sx, sy) in [
        (margin, margin, size, size),
        (PAGE_W - margin, margin, -size, size),
        (margin, PAGE_H - margin, size, -size),
        (PAGE_W - margin, PAGE_H - margin, -size, -size),
    ]:
        pdf.line(cx, cy, cx + sx, cy)
        pdf.line(cx, cy, cx, cy + sy)


def _draw_ornament_divider(pdf: FPDF, y: float | None = None) -> None:
    """Draw a decorative center-line divider with ornament."""
    if y is not None:
        pdf.set_y(y)
    cy = pdf.get_y() + 3
    cx = PAGE_W / 2
    pdf.set_draw_color(ACC_R, ACC_G, ACC_B)
    pdf.set_line_width(0.3)
    pdf.line(cx - 30, cy, cx - 6, cy)
    pdf.line(cx + 6, cy, cx + 30, cy)
    # Center diamond
    pdf.set_fill_color(ACC_R, ACC_G, ACC_B)
    pdf.ellipse(cx - 2, cy - 2, 4, 4, style='F')
    pdf.set_y(pdf.get_y() + 8)


def _draw_page_number(pdf: FPDF, page_num: int) -> None:
    """Draw page number in small decorative style at bottom center."""
    pdf.set_y(PAGE_H - MARGIN_BOTTOM + 4)
    pdf.set_font('DejaVu', style='', size=8)
    pdf.set_text_color(RHD_R, RHD_G, RHD_B)
    pdf.set_x(MARGIN_OUTER)
    pdf.cell(CONTENT_W, 5, f'— {page_num} —', align='C')


def _draw_running_header(pdf: FPDF, title: str) -> None:
    """Draw small running header with story title at top of story pages."""
    pdf.set_y(10)
    pdf.set_font('DejaVu', style='', size=7.5)
    pdf.set_text_color(RHD_R, RHD_G, RHD_B)
    pdf.set_x(MARGIN_OUTER)
    # Truncate long titles
    display = title if len(title) <= 50 else title[:47] + '...'
    pdf.cell(CONTENT_W, 5, display, align='C')
    # Thin rule below
    pdf.set_draw_color(ACC_R, ACC_G, ACC_B)
    pdf.set_line_width(0.2)
    y = pdf.get_y() + 5
    pdf.line(MARGIN_OUTER, y, PAGE_W - MARGIN_OUTER, y)


def _draw_image_in_frame(pdf: FPDF, img_path: Path, caption: str = '') -> None:
    """Insert an image centered with a decorative border frame."""
    img_w = 120
    img_h = 82
    img_x = (PAGE_W - img_w) / 2

    # Check space
    remaining = PAGE_H - MARGIN_BOTTOM - pdf.get_y()
    if remaining < img_h + 20:
        return False  # signal caller to try on new page

    iy = pdf.get_y() + 3
    frame_pad = 2

    # Draw frame
    pdf.set_draw_color(IMG_BRD_R, IMG_BRD_G, IMG_BRD_B)
    pdf.set_line_width(0.8)
    pdf.rect(img_x - frame_pad, iy - frame_pad, img_w + frame_pad * 2, img_h + frame_pad * 2)
    pdf.set_line_width(0.2)
    pdf.rect(img_x - frame_pad - 2, iy - frame_pad - 2, img_w + (frame_pad + 2) * 2, img_h + (frame_pad + 2) * 2)

    try:
        pdf.image(str(img_path), x=img_x, y=iy, w=img_w, h=img_h)
    except Exception as e:
        logger.warning('Image render failed: %s', e)
        return True

    pdf.set_y(iy + img_h + frame_pad + 4)

    if caption:
        pdf.set_font('DejaVu', style='I', size=8)
        pdf.set_text_color(RHD_R, RHD_G, RHD_B)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 5, caption, align='C', new_x='LMARGIN', new_y='NEXT')

    pdf.ln(4)
    return True


# ── Main generator ───────────────────────────────────────────────────────────

def generate_pdf(title: str, story_text: str, image_urls: list[str],
                 episode_number: int = 1, child_name: str = '') -> str:
    out_dir = Path(settings.stories_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.pdf'
    full_path = out_dir / filename

    try:
        regular = _find_font(_REGULAR_CANDIDATES, 'regular')
        bold = _find_font(_BOLD_CANDIDATES, 'bold')
        italic_path = None
        for c in _ITALIC_CANDIDATES:
            if Path(c).exists():
                italic_path = c
                break

        pdf = FPDF()
        pdf.set_auto_page_break(auto=False)
        pdf.add_font('DejaVu', style='', fname=regular)
        pdf.add_font('DejaVu', style='B', fname=bold)
        if italic_path:
            pdf.add_font('DejaVu', style='I', fname=italic_path)
        else:
            pdf.add_font('DejaVu', style='I', fname=regular)  # fallback

        # ── Collect local image paths ─────────────────────────────────────
        local_images: list[Path] = []
        for url in image_urls:
            p = _url_to_local_path(url)
            if p:
                local_images.append(p)

        # ── PAGE 1: Cover ─────────────────────────────────────────────────
        pdf.add_page()
        _fill_bg(pdf)
        _draw_corner_ornaments(pdf, margin=12, size=12)

        # Series label
        pdf.set_y(28)
        pdf.set_font('DejaVu', style='I', size=10)
        pdf.set_text_color(RHD_R, RHD_G, RHD_B)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 7, 'Маленькие легенды', align='C', new_x='LMARGIN', new_y='NEXT')

        # Horizontal rule
        pdf.set_draw_color(ACC_R, ACC_G, ACC_B)
        pdf.set_line_width(0.6)
        cx = PAGE_W / 2
        y0 = pdf.get_y() + 2
        pdf.line(cx - 50, y0, cx + 50, y0)
        pdf.ln(10)

        # Episode badge (if serial)
        if episode_number > 1:
            pdf.set_font('DejaVu', style='', size=9)
            pdf.set_text_color(ACC_R, ACC_G, ACC_B)
            pdf.set_x(MARGIN_OUTER)
            pdf.multi_cell(CONTENT_W, 6, f'✦  Эпизод {episode_number}  ✦', align='C', new_x='LMARGIN', new_y='NEXT')
            pdf.ln(4)

        # Story title
        pdf.set_font('DejaVu', style='B', size=26)
        pdf.set_text_color(TTL_R, TTL_G, TTL_B)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 14, title, align='C', new_x='LMARGIN', new_y='NEXT')
        pdf.ln(8)

        # Cover illustration (first image)
        if local_images:
            cover_w = 140
            cover_h = 105
            cover_x = (PAGE_W - cover_w) / 2
            cover_y = pdf.get_y()
            frame_pad = 3
            # Outer frame
            pdf.set_draw_color(IMG_BRD_R, IMG_BRD_G, IMG_BRD_B)
            pdf.set_line_width(1.0)
            pdf.rect(cover_x - frame_pad, cover_y - frame_pad, cover_w + frame_pad * 2, cover_h + frame_pad * 2)
            pdf.set_line_width(0.3)
            pdf.rect(cover_x - frame_pad - 3, cover_y - frame_pad - 3,
                     cover_w + (frame_pad + 3) * 2, cover_h + (frame_pad + 3) * 2)
            try:
                pdf.image(str(local_images[0]), x=cover_x, y=cover_y, w=cover_w, h=cover_h)
            except Exception as e:
                logger.warning('Cover image failed: %s', e)
            pdf.set_y(cover_y + cover_h + frame_pad + 10)

        # Bottom ornament + dedication
        _draw_ornament_divider(pdf)
        pdf.set_font('DejaVu', style='I', size=9.5)
        pdf.set_text_color(RHD_R, RHD_G, RHD_B)
        pdf.set_x(MARGIN_OUTER)
        dedication = f'Персональная сказка для {child_name}' if child_name else 'Персональная сказка'
        pdf.multi_cell(CONTENT_W, 6, dedication, align='C', new_x='LMARGIN', new_y='NEXT')
        pdf.ln(3)
        pdf.set_font('DejaVu', style='', size=8)
        pdf.set_text_color(ACC_R, ACC_G, ACC_B)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 5, '✦  Маленькие легенды  ✦', align='C', new_x='LMARGIN', new_y='NEXT')

        # ── Story pages ───────────────────────────────────────────────────
        paragraphs = [p.strip() for p in story_text.split('\n\n') if p.strip()]
        story_images = local_images[1:] if len(local_images) > 1 else []

        # Spread images evenly through paragraphs (skip first para = chapter header usually)
        img_at_para: dict[int, int] = {}
        if story_images:
            non_chapter_paras = [i for i, p in enumerate(paragraphs) if not p.startswith('Глава')]
            step = max(1, len(non_chapter_paras) // len(story_images))
            for img_idx, para_pos in enumerate(range(step - 1, len(non_chapter_paras), step)):
                if img_idx < len(story_images):
                    img_at_para[non_chapter_paras[para_pos]] = img_idx

        page_num = 1

        def new_page():
            nonlocal page_num
            page_num += 1
            pdf.add_page()
            _fill_bg(pdf)
            _draw_corner_ornaments(pdf, margin=10, size=6)
            _draw_running_header(pdf, title)
            _draw_page_number(pdf, page_num)
            pdf.set_y(MARGIN_TOP + 8)

        def content_bottom() -> float:
            return PAGE_H - MARGIN_BOTTOM - 12

        def space_left() -> float:
            return content_bottom() - pdf.get_y()

        new_page()

        for para_idx, para in enumerate(paragraphs):
            is_chapter = para.startswith('Глава')

            # ── Insert image before this paragraph if scheduled ──────────
            if para_idx in img_at_para:
                img_path = story_images[img_at_para[para_idx]]
                img_h_needed = 82 + 20 + 20  # image + frame + caption + spacing
                if space_left() < img_h_needed:
                    new_page()
                ok = _draw_image_in_frame(pdf, img_path, f'Иллюстрация {img_at_para[para_idx] + 2}')
                if not ok:
                    new_page()
                    _draw_image_in_frame(pdf, img_path, f'Иллюстрация {img_at_para[para_idx] + 2}')

            # ── Chapter header with decorative band ─────────────────────
            if is_chapter:
                if space_left() < 40:
                    new_page()

                # Measure text height
                pdf.set_font('DejaVu', style='B', size=13)
                lines = pdf.multi_cell(CONTENT_W, 8, para, align='C',
                                       new_x='LMARGIN', new_y='NEXT', dry_run=True, output='LINES')
                band_h = len(lines) * 8 + 10

                bx = MARGIN_OUTER - 2
                by = pdf.get_y() - 1
                bw = CONTENT_W + 4

                # Colored band background
                pdf.set_fill_color(HDR_R, HDR_G, HDR_B)
                pdf.rect(bx, by, bw, band_h, style='F')

                # Chapter title text
                pdf.set_y(by + 4)
                pdf.set_font('DejaVu', style='B', size=13)
                pdf.set_text_color(HDR_TXT_R, HDR_TXT_G, HDR_TXT_B)
                pdf.set_x(MARGIN_OUTER)
                pdf.multi_cell(CONTENT_W, 8, para, align='C', new_x='LMARGIN', new_y='NEXT')
                pdf.set_y(by + band_h + 4)

            else:
                # ── Body paragraph ───────────────────────────────────────
                pdf.set_font('DejaVu', style='', size=11)
                pdf.set_text_color(BODY_R, BODY_G, BODY_B)

                lines = pdf.multi_cell(CONTENT_W, 6.8, para, align='J',
                                       new_x='LMARGIN', new_y='NEXT', dry_run=True, output='LINES')
                text_h = len(lines) * 6.8 + 4

                if space_left() < text_h:
                    new_page()

                pdf.set_x(MARGIN_OUTER)
                pdf.multi_cell(CONTENT_W, 6.8, para, align='J', new_x='LMARGIN', new_y='NEXT')
                pdf.ln(4)

        # ── Remaining images (if any not placed inline) ──────────────────
        placed = set(img_at_para.values())
        for i, img_path in enumerate(story_images):
            if i not in placed:
                if space_left() < 110:
                    new_page()
                _draw_image_in_frame(pdf, img_path, f'Иллюстрация {i + 2}')

        # ── Final ornament / "The End" ────────────────────────────────────
        if space_left() < 30:
            new_page()
        _draw_ornament_divider(pdf)
        pdf.set_font('DejaVu', style='B', size=12)
        pdf.set_text_color(TTL_R, TTL_G, TTL_B)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 8, '✦  Конец  ✦', align='C', new_x='LMARGIN', new_y='NEXT')

        pdf.output(str(full_path))
        logger.info('PDF generated: %s (%d bytes, %d pages)', filename, full_path.stat().st_size, page_num)

    except Exception as exc:
        logger.exception('PDF generation failed: %s', exc)
        raise

    return f'{settings.public_base_url}/files/stories/{filename}'
