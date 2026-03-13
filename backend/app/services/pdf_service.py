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

# ── Gender-based color palettes ──────────────────────────────────────────────
_PALETTE = {
    'female': {
        'BG':       (255, 248, 252),
        'HDR':      (180, 70, 120),
        'HDR_TXT':  (255, 235, 248),
        'BODY':     (50,  20,  40),
        'ACC':      (210, 110, 165),
        'RHD':      (175, 85, 135),
        'TTL':      (145, 40,  95),
        'IMG_BRD':  (200, 130, 175),
        'HOOK_BG':  (252, 235, 248),
    },
    'male': {
        'BG':       (245, 248, 255),
        'HDR':      (45,  75,  155),
        'HDR_TXT':  (215, 230, 255),
        'BODY':     (15,  25,  60),
        'ACC':      (75,  115, 200),
        'RHD':      (65,  105, 185),
        'TTL':      (28,  52,  135),
        'IMG_BRD':  (95,  135, 210),
        'HOOK_BG':  (232, 240, 255),
    },
    'neutral': {
        'BG':       (255, 252, 242),
        'HDR':      (120, 60,  20),
        'HDR_TXT':  (255, 245, 225),
        'BODY':     (35,  18,  8),
        'ACC':      (180, 110, 40),
        'RHD':      (160, 100, 50),
        'TTL':      (80,  35,  10),
        'IMG_BRD':  (160, 110, 50),
        'HOOK_BG':  (245, 230, 205),
    },
}


def _to_genitive(name: str) -> str:
    """Convert Russian first name to genitive case (approximation)."""
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


def _url_to_local_path(url: str) -> Path | None:
    try:
        filename = url.rstrip('/').split('/')[-1]
        path = Path(settings.images_dir) / filename
        return path if path.exists() else None
    except Exception:
        return None


# ── Drawing helpers ──────────────────────────────────────────────────────────

def _fill_bg(pdf: FPDF, C: dict) -> None:
    r, g, b = C['BG']
    pdf.set_fill_color(r, g, b)
    pdf.rect(0, 0, PAGE_W, PAGE_H, style='F')


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
    pdf.line(cx + 6, cy, cx + 30, cy)
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


def _draw_square_image(pdf: FPDF, C: dict, img_path: Path,
                       size: float = 110, centered: bool = True) -> None:
    img_x = (PAGE_W - size) / 2 if centered else MARGIN_OUTER
    iy = pdf.get_y() + 3
    _draw_framed_image(pdf, C, img_path, img_x, iy, size, size)
    pdf.set_y(iy + size + 2 + 8)


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

    # Pick color palette
    C = _PALETTE.get(gender, _PALETTE['neutral'])

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
        local_images: list[Path | None] = [_url_to_local_path(u) for u in image_urls]

        # Image slot assignments:
        # [0] cover  [1-5] chapters 0-4  [6] overflow/continuation  [7] final
        def _img(idx: int) -> Path | None:
            return local_images[idx] if idx < len(local_images) else None

        cover_img    = _img(0)
        chapter_imgs = [_img(i) for i in range(1, 6)]   # chapters 0-4
        overflow_img = _img(6)                            # continuation pages
        final_img    = _img(7) or (local_images[-1] if local_images else None)

        # ── PAGE 1: Cover ─────────────────────────────────────────────────
        pdf.add_page()
        _fill_bg(pdf, C)
        _draw_corner_ornaments(pdf, C, margin=12, size=12)

        rr, rg, rb = C['RHD']
        ar, ag, ab = C['ACC']
        tr, tg, tb = C['TTL']

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
        pdf.line(cx - 50, y0, cx + 50, y0)
        pdf.set_y(y0 + 6)

        if episode_number > 1:
            pdf.set_font('DejaVu', style='', size=9)
            pdf.set_text_color(ar, ag, ab)
            pdf.set_x(MARGIN_OUTER)
            pdf.multi_cell(CONTENT_W, 6, f'✦  Эпизод {episode_number}  ✦', align='C',
                           new_x='LMARGIN', new_y='NEXT')
            pdf.ln(4)

        # Cover illustration — large centered square
        if cover_img:
            cov_size = 138
            cov_x = (PAGE_W - cov_size) / 2
            cov_y = pdf.get_y() + 2
            _draw_framed_image(pdf, C, cover_img, cov_x, cov_y, cov_size, cov_size, frame_pad=3)
            pdf.set_y(cov_y + cov_size + 3 + 10)
        else:
            pdf.ln(30)

        # Title
        pdf.set_font('DejaVu', style='B', size=24)
        pdf.set_text_color(tr, tg, tb)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 13, title, align='C', new_x='LMARGIN', new_y='NEXT')
        pdf.ln(8)

        _draw_ornament_divider(pdf, C)

        # Dedication with correct genitive case
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

        # ── Story pages ───────────────────────────────────────────────────
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
        page_has_image = False

        br, bg, bb = C['BODY']
        hr2, hg2, hb2 = C['HDR']
        ht_r, ht_g, ht_b = C['HDR_TXT']

        def new_story_page():
            nonlocal page_num, page_has_image
            page_num += 1
            page_has_image = False
            pdf.add_page()
            _fill_bg(pdf, C)
            _draw_corner_ornaments(pdf, C, margin=10, size=6)
            _draw_running_header(pdf, C, title)
            _draw_page_number(pdf, C, page_num)
            pdf.set_y(MARGIN_TOP + 8)

        def content_bottom() -> float:
            return PAGE_H - MARGIN_BOTTOM - 12

        def space_left() -> float:
            return content_bottom() - pdf.get_y()

        for ch_idx, (chapter_title, paras) in enumerate(chapters):
            new_story_page()

            # Chapter header band with rounded corners
            if chapter_title:
                pdf.set_font('DejaVu', style='B', size=13)
                lines = pdf.multi_cell(CONTENT_W, 8, chapter_title, align='C',
                                       new_x='LMARGIN', new_y='NEXT', dry_run=True, output='LINES')
                band_h = len(lines) * 8 + 12
                bx = MARGIN_OUTER - 2
                by = pdf.get_y() - 1
                bw = CONTENT_W + 4
                pdf.set_fill_color(hr2, hg2, hb2)
                try:
                    pdf.rect(bx, by, bw, band_h, style='F', round_corners=True, corner_radius=4)
                except TypeError:
                    pdf.rect(bx, by, bw, band_h, style='F')
                pdf.set_y(by + 5)
                pdf.set_font('DejaVu', style='B', size=13)
                pdf.set_text_color(ht_r, ht_g, ht_b)
                pdf.set_x(MARGIN_OUTER)
                pdf.multi_cell(CONTENT_W, 8, chapter_title, align='C', new_x='LMARGIN', new_y='NEXT')
                pdf.set_y(by + band_h + 4)

            # Chapter illustration: chapter[0]→img[1], chapter[1]→img[2], etc.
            ch_img = chapter_imgs[ch_idx] if ch_idx < len(chapter_imgs) else None
            if ch_img:
                _draw_square_image(pdf, C, ch_img, size=110, centered=True)
                page_has_image = True

            # Body paragraphs
            for para in paras:
                lines = pdf.multi_cell(CONTENT_W, 6.8, para, align='J',
                                       new_x='LMARGIN', new_y='NEXT', dry_run=True, output='LINES')
                text_h = len(lines) * 6.8 + 4

                if space_left() < text_h:
                    new_story_page()
                    # Draw overflow image on continuation page if available
                    if not page_has_image and overflow_img:
                        _draw_square_image(pdf, C, overflow_img, size=80, centered=True)
                        page_has_image = True

                # Always reset font + color right before rendering
                pdf.set_font('DejaVu', style='', size=11)
                pdf.set_text_color(br, bg, bb)
                pdf.set_x(MARGIN_OUTER)
                pdf.multi_cell(CONTENT_W, 6.8, para, align='J', new_x='LMARGIN', new_y='NEXT')
                pdf.ln(4)

        # ── Next-hook teaser ─────────────────────────────────────────────
        if next_hook:
            if space_left() < 60:
                new_story_page()
            _draw_hook_box(pdf, C, next_hook)

        # ── Final illustration ────────────────────────────────────────────
        if final_img:
            if space_left() < 125:
                new_story_page()
            pdf.ln(4)
            _draw_square_image(pdf, C, final_img, size=100, centered=True)
            pdf.set_text_color(br, bg, bb)

        # ── "The End" ─────────────────────────────────────────────────────
        if space_left() < 25:
            new_story_page()
        _draw_ornament_divider(pdf, C)
        pdf.set_font('DejaVu', style='B', size=12)
        pdf.set_text_color(tr, tg, tb)
        pdf.set_x(MARGIN_OUTER)
        pdf.multi_cell(CONTENT_W, 8, '✦  Конец  ✦', align='C', new_x='LMARGIN', new_y='NEXT')

        pdf.output(str(full_path))
        logger.info('PDF generated: %s (%d bytes, %d pages)', filename, full_path.stat().st_size, page_num)

    except Exception as exc:
        logger.exception('PDF generation failed: %s', exc)
        raise

    return f'{settings.public_base_url}/files/stories/{filename}'
