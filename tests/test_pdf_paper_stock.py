"""The reusable vector stock must not substitute for or obscure a scene."""
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fpdf import FPDF
from PIL import Image
from pypdf import PdfReader

from backend.app import book_release
from backend.app.services import paper_stock, pdf_service


@pytest.mark.parametrize("scenes", [4, 5])
def test_generated_book_shares_one_interior_stock_and_counts_only_art(tmp_path, monkeypatch, scenes):
    settings = SimpleNamespace(stories_dir=str(tmp_path), images_dir=str(tmp_path),
                               public_base_url="https://test.invalid")
    monkeypatch.setattr(pdf_service, "settings", settings)
    monkeypatch.setattr(book_release, "get_settings", lambda: settings)
    urls = []
    for number in range(scenes):
        name = f"{number:032x}.png"
        with Image.new("RGB", (300, 165), (20 * number, 80, 120)) as scene:
            scene.save(tmp_path / name)
        urls.append(f"{settings.public_base_url}/files/images/{name}")
    story = "\n\n".join(f"Глава {n}. Бумажный дом\n\nКрот постучал в дверь." for n in range(1, 5))
    locator = pdf_service.generate_pdf("Бумажный дом", story, urls, child_name="Лена")
    path = tmp_path / Path(locator).name
    reader = PdfReader(path, strict=True)
    assert "/LegendKidsPaper" not in reader.pages[0]["/Resources"]["/XObject"]
    interiors = list(reader.pages)[1:]
    assert len(interiors) >= 4
    papers = [p["/Resources"]["/XObject"].raw_get("/LegendKidsPaper") for p in interiors]
    assert len({paper.idnum for paper in papers}) == 1
    form = papers[0].get_object()
    assert form["/Subtype"] == "/Form" and "/Shading" in form["/Resources"]
    for page in interiors:
        assert tuple(map(float, page.mediabox)) == pytest.approx((0, 0, 595.28, 841.89), abs=.02)
        assert b"/LegendKidsPaper Do" in page["/Contents"][0].get_object().get_data()
    assert sum(len(page.images) for page in reader.pages) == scenes
    assert "Бумажный дом" in "".join(page.extract_text() or "" for page in interiors)
    if scenes == 5:
        assert book_release.require_complete_pdf(locator) == hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        with pytest.raises(ValueError, match="distinct embedded illustrations"):
            book_release.require_complete_pdf(locator)


def test_write_failure_leaves_no_partial_book(tmp_path, monkeypatch):
    pdf = FPDF()
    pdf.add_page()
    pdf.add_page()
    path = tmp_path / "test.pdf"

    def interrupted_write(_writer, stream):
        stream.write(b"%PDF-unfinished")
        raise OSError("write interrupted")

    monkeypatch.setattr(paper_stock.PdfWriter, "write", interrupted_write)
    with pytest.raises(OSError, match="interrupted"):
        paper_stock.write_with_paper(pdf.output(), path)
    assert list(tmp_path.iterdir()) == []
    path.write_bytes(b"previous complete copy")
    with pytest.raises(OSError, match="interrupted"):
        paper_stock.write_with_paper(pdf.output(), path)
    assert path.read_bytes() == b"previous complete copy"


def test_stock_cost_is_paid_once_per_book(tmp_path):
    sizes = {}
    for count in (1, 2, 12):
        pdf = FPDF()
        for _ in range(count):
            pdf.add_page()
        source = pdf.output()
        path = tmp_path / f"{count}.pdf"
        paper_stock.write_with_paper(source, path)
        if count == 1:
            assert path.read_bytes() == source
        sizes[count] = path.stat().st_size
    assert 0 < sizes[12] - sizes[2] < 20_000
