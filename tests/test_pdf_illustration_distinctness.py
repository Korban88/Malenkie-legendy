"""Synthetic PDF tests: repeated image objects are not five illustrations."""
import hashlib
from types import SimpleNamespace

import pytest
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from backend.app import book_release as gate


@pytest.mark.parametrize('distinct', [1, 4, 5])
def test_pdf_requires_five_distinct_decoded_images(tmp_path, monkeypatch, distinct):
    monkeypatch.setattr(gate, 'get_settings', lambda: SimpleNamespace(stories_dir=str(tmp_path)))
    path = tmp_path / ('a' * 32 + '.pdf')
    pdf = Canvas(str(path))
    for i in range(5):
        pdf.drawString(40, 700, 'Synthetic story page')
        with Image.new('RGB', (32, 24), ((i % distinct) * 40, 100, 150)) as picture:
            pdf.drawImage(ImageReader(picture), 40, 500, width=120, height=90)
        pdf.showPage()
    pdf.save()
    locator = 'https://test.invalid/files/stories/' + path.name
    if distinct < 5:
        with pytest.raises(ValueError, match='distinct embedded illustrations'):
            gate.require_complete_pdf(locator)
    else:
        assert gate.require_complete_pdf(locator) == hashlib.sha256(path.read_bytes()).hexdigest()
