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
MARGIN_OUTER = 18
MARGIN_TOP = 22
MARGIN_BOTTOM = 22
CONTENT_W = PAGE_W - 2 * MARGIN_OUTER

# ── Color palette ────────────────────────────────────────────────────────────
BG_R, BG_G, BG_B             = 255, 252, 242   # warm cream background
HDR_R, HDR_G, HDR_B          = 120,  60,  20   # chapter band (dark brown)
HDR_TXT_R, HDR_TXT_G, HDR_TXT_B = 255, 245, 225  # chapter text (near white)
BODY_R, BODY_G, BODY_B       = 35,   18,   8   # body text
ACC_R, ACC_G, ACC_B          = 180, 110,  40   # ornaments / lines
RHD_R, RHD_G, RHD_B         = 160, 100,  50   # running header / page num
TTL_R, TTL_G, TTL_B          = 80,   35,  10   # title text
IMG_BRD_R, IMG_BRD_G, IMG_BRD_B = 160, 110, 50  # image frame
HOOK_BG_R, HOOK_BG_G, HOOK_BG_B = 245, 230, 205  # next-hook box background


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
    pdf.set_fill_color(BG_R, BG_G, BG_B)
    pdf.rect(0, 0, PAGE_W, PAGE_H, style='F')


def _draw_corner_ornaments(pdf: FPDF, margin: float = 10.0, size: float = 8.0) -> None:
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


def _draw_ornament_divider(pdf: FPDF) -> None:
    cy = pdf.get_y() + 3
    cx = PAGE_W / 2
    pdf.set_draw_color(ACC_R, ACC_G, ACC_B)
    pdf.set_line_width(0.3)
    pdf.line(cx - 30, cy, cx - 6, cy)
    pdf.line(cx + 6, cy, cx + 30, cy)
    pdf.set_fill_color(ACC_R, ACC_G, ACC_B)
    pdf.ellipse(cx - 2, cy - 2, 4, 4, style='F')
    pdf.set_y(pdf.get_y() + 8)


def _draw_page_number(pdf: FPDF, page_num: int) -> None:
    pdf.set_y(PAGE_H - MARGIN_BOTTOM + 4)
    pdf.set_font('DejaVu', style='', size=8)
    pdf.set_text_color(RHD_R, RHD_G, RHD_B)
    pdf.set_x(MARGIN_OUTER)
    pdf.cell(CONTENT_W, 5, f'— {page_num} —', align='C')


def _draw_running_header(pdf: FPDF, title: str) -> None:
    pdf.set_y(10)
    pdf.set_font('DejaVu', style='', size=7.5)
    pdf.set_text_color(RHD_R, RHD_G, RHD_B)
    pdf.set_x(MARGIN_OUTER)
    display = title if len(title) <= 50 else title[:47] + '...'
    pdf.cell(CONTENT_W, 5, display, align='C')
    pdf.set_draw_color(ACC_R, ACC_G, ACC_B)
    pdf.set_line_width(0.2)
    y = pdf.get_y() + 5
    pdf.line(MARGIN_OUTER, y, PAGE_W - MARGIN_OUTER, y)


def _draw_chapter_image(pdf: FPDF, img_path: Path) -> None:
    """Draw a full-width illustration right after chapter header."""
    img_w = CONTENT_W
    img_h = 90
    img_x = MARGIN_OUTER
    iy = pdf.get_y() + 3
    frame_pad = 2

    # Double frame
    pdf.set_draw_color(IMG_BRD_R, IMG_BRD_G, IMG_BRD_B)
    pdf.set_line_width(0.8)
    pdf.rect(img_x - frame_pad, iy - frame_pad, img_w + frame_pad * 2, img_h + frame_pad * 2)
    pdf.set_line_width(0.2)
    pdf.rect(img_x - frame_pad - 2, iy - frame_pad - 2,
             img_w + (frame_pad + 2) * 2, img_h + (frame_pad + 2) * 2)

    try:
        pdf.image(str(img_path), x=img_x, y=iy, w=img_w, h=img_h)
    except Exception as e:
        logger.warning('Chapter image render failed: %s', e)

    pdf.set_y(iy + img_h + frame_pad + 8)


def _draw_hook_box(pdf: FPDF, hook_text: str) -> None:
    """Draw the cliffhanger/next-episode teaser in a decorative box."""
    pdf.set_font('DejaVu', style='', size=10)
    # Measure height
    lines = pdf.multi_cell(CONTENT_W - 12, 7, hook_text, align='C',
                           dry_run=True, output='LINES',
                           new_x='LMARGIN', new_y='NEXT')
    text_h = len(lines) * 7
    box_h = text_h + 20

    bx = MARGIN_OUTER
    by = pdf.get_y() + 4
    # Background
    pdf.set_fill_color(HOOK_BG_R, HOOK_BG_G, HOOK_BG_B)
    pdf.rect(bx, by, CONTENT_W, box_h, style='F')
    # Border
    pdf.set_draw_color(ACC_R, ACC_G, ACC_B)
    pdf.set_line_width(0.6)
    pdf.rect(bx, by, CONTENT_W, box_h)
    pdf.set_line_width(0.2)
    pdf.rect(bx + 2, by + 2, CONTENT_W - 4, box_h - 4)

    # Label
    pdf.set_y(by + 5)
    pdf.set_font('DejaVu', style='B', size=8)
    pdf.set_text_color(ACC_R, ACC_G, ACC_B)
    pdf.set_x(MARGIN_OUTER)
    pdf.cell(CONTENT_W, 5, '✦  Что будет в следующий раз...  ✦', align='C')
    pdf.ln(5)

    # Hook text
    pdf.set_font('DejaVu', style='I', size=10)
    pdf.set_text_color(TTL_R, TTL_G, TTL_B)
    pdf.set_x(MARGIN_OUTER + 6)
    pdf.multi_cell(CONTENT_W - 12, 7, hook_text, align='C',
                   new_x='LMARGIN', new_y='NEXT')
    pdf.set_y(by + box_h + 6)


# ── Main generator ───────────────────────────────────────────────────────────

def generate_pdf(title: str, story_text: str, image_urls: list[str],
                 episode_number: int = 1, child_name: str = '',
                 next_hook: str = '') -> str:
    out_dir = Path(settings.stories_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.pdf'
    full_path = out_dir / filename

    try:
        regular = _find_font(_REGULAR_CANDIDATES, 'regular')
        bold = _find_font(_BOLD_CANDIDATES, 'bold')
        italic_path = next((c for c in _ITALIC_CANDIDATES if Path(c).exists()), regular)

        pdf = FPDF()
        pdf.set_auto_page_break(auto=False)
        pdf.add_font('DejaVu', style='', fname=regular)
        pdf.add_font('DejaVu', style='B', fname=bold)
        pdf.add_font('DejaVu', style='I', fname=italic_path)

        # Collect local image paths
        local_images: list[Path | None] = []
        for url in image_urls:
            local_images.append(_url_to_local_path(url))

        # ── PAGE 1: Cover ─────────────────────────────────────────────────
        pdf.add_page()
        _fill_bg(pdf)
        _draw_corner_ornaments(pdf, margin=12, size=12)

        pdf.set_y(35)
        pdf.set_font('DejaVu', style='I', size=10)
        pdf.set_text_color(RHD_R, RHD_G, RHD_B)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 7, 'Маленькие легенды', align='C', new_x='LMARGIN', new_y='NEXT')

        pdf.set_draw_color(ACC_R, ACC_G, ACC_B)
        pdf.set_line_width(0.6)
        cx = PAGE_W / 2
        y0 = pdf.get_y() + 2
        pdf.line(cx - 50, y0, cx + 50, y0)
        pdf.ln(10)

        if episode_number > 1:
            pdf.set_font('DejaVu', style='', size=9)
            pdf.set_text_color(ACC_R, ACC_G, ACC_B)
            pdf.set_x(MARGIN_OUTER)
            pdf.multi_cell(CONTENT_W, 6, f'✦  Эпизод {episode_number}  ✦', align='C', new_x='LMARGIN', new_y='NEXT')
            pdf.ln(4)

        pdf.set_font('DejaVu', style='B', size=28)
        pdf.set_text_color(TTL_R, TTL_G, TTL_B)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 15, title, align='C', new_x='LMARGIN', new_y='NEXT')
        pdf.ln(12)

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

        # Split into chapter blocks: list of (chapter_title, [paragraphs], image_or_None)
        chapters: list[tuple[str, list[str], Path | None]] = []
        current_chapter_title = ''
        current_paras: list[str] = []

        for para in paragraphs:
            if para.startswith('Глава'):
                if current_chapter_title or current_paras:
                    # Assign image: chapter index matches local_images index
                    img = local_images[len(chapters)] if len(chapters) < len(local_images) else None
                    chapters.append((current_chapter_title, current_paras, img))
                current_chapter_title = para
                current_paras = []
            else:
                current_paras.append(para)

        # Last chapter
        if current_chapter_title or current_paras:
            img = local_images[len(chapters)] if len(chapters) < len(local_images) else None
            chapters.append((current_chapter_title, current_paras, img))

        page_num = 1

        def new_story_page():
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

        for chapter_title, paras, chapter_img in chapters:
            # Each chapter starts on a new page
            new_story_page()

            # Chapter header band
            if chapter_title:
                pdf.set_font('DejaVu', style='B', size=13)
                lines = pdf.multi_cell(CONTENT_W, 8, chapter_title, align='C',
                                       new_x='LMARGIN', new_y='NEXT', dry_run=True, output='LINES')
                band_h = len(lines) * 8 + 12
                bx = MARGIN_OUTER - 2
                by = pdf.get_y() - 1
                bw = CONTENT_W + 4
                pdf.set_fill_color(HDR_R, HDR_G, HDR_B)
                pdf.rect(bx, by, bw, band_h, style='F')
                pdf.set_y(by + 5)
                pdf.set_font('DejaVu', style='B', size=13)
                pdf.set_text_color(HDR_TXT_R, HDR_TXT_G, HDR_TXT_B)
                pdf.set_x(MARGIN_OUTER)
                pdf.multi_cell(CONTENT_W, 8, chapter_title, align='C', new_x='LMARGIN', new_y='NEXT')
                pdf.set_y(by + band_h + 4)

            # Chapter illustration right after header
            if chapter_img:
                _draw_chapter_image(pdf, chapter_img)

            # Body paragraphs
            for para in paras:
                pdf.set_font('DejaVu', style='', size=11)
                pdf.set_text_color(BODY_R, BODY_G, BODY_B)

                lines = pdf.multi_cell(CONTENT_W, 6.8, para, align='J',
                                       new_x='LMARGIN', new_y='NEXT', dry_run=True, output='LINES')
                text_h = len(lines) * 6.8 + 4

                if space_left() < text_h:
                    new_story_page()

                pdf.set_x(MARGIN_OUTER)
                pdf.multi_cell(CONTENT_W, 6.8, para, align='J', new_x='LMARGIN', new_y='NEXT')
                pdf.ln(4)

        # ── Next-hook teaser ─────────────────────────────────────────────
        if next_hook:
            if space_left() < 60:
                new_story_page()
            _draw_hook_box(pdf, next_hook)

        # ── "The End" ─────────────────────────────────────────────────────
        if space_left() < 25:
            new_story_page()
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
