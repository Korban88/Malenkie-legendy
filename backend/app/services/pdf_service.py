import uuid
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from ..config import get_settings

settings = get_settings()


def generate_pdf(title: str, story_text: str, image_urls: list[str]) -> str:
    out_dir = Path(settings.stories_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.pdf'
    full_path = out_dir / filename

    c = canvas.Canvas(str(full_path), pagesize=A4)
    w, h = A4
    y = h - 50
    c.setFont('Helvetica-Bold', 16)
    c.drawString(40, y, title[:90])
    y -= 40

    c.setFont('Helvetica', 11)
    for para in story_text.split('\n\n'):
        for line in _wrap(para.strip(), 95):
            c.drawString(40, y, line)
            y -= 16
            if y < 100:
                c.showPage()
                c.setFont('Helvetica', 11)
                y = h - 50
        y -= 10  # отступ между абзацами

    y -= 20
    c.setFont('Helvetica-Bold', 12)
    c.drawString(40, y, 'Иллюстрации:')
    y -= 18
    c.setFont('Helvetica', 10)
    for url in image_urls:
        c.drawString(40, y, url[:110])
        y -= 14
        if y < 70:
            c.showPage()
            c.setFont('Helvetica', 10)
            y = h - 50

    c.save()
    return f'{settings.public_base_url}/files/stories/{filename}'


def _wrap(text: str, max_len: int) -> list[str]:
    words = text.split()
    lines, current = [], []
    for word in words:
        trial = ' '.join(current + [word])
        if len(trial) <= max_len:
            current.append(word)
        else:
            lines.append(' '.join(current))
            current = [word]
    if current:
        lines.append(' '.join(current))
    return lines
