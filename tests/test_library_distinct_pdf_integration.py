"""Exercise the shared PDF gate through the paid-family library on isolated SQLite."""
import hashlib
from types import SimpleNamespace

import pytest
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles, deregister
from sqlalchemy.orm import Session

from backend.app import book_release
from backend.app.db import Base
from backend.app.models import Child, Order, Story, User
from backend.app.services.telegram_library import find_book, list_books, PAGE_SIZE


def _pdf(path, distinct):
    pdf = Canvas(str(path))
    for i in range(5):
        pdf.drawString(40, 700, 'Synthetic story page')
        with Image.new('RGB', (32, 24), ((i % distinct) * 40, 100, 150)) as picture:
            pdf.drawImage(ImageReader(picture), 40, 500, width=120, height=90)
        pdf.showPage()
    pdf.save()


@pytest.mark.parametrize('bad_distinct', [1, 4])
def test_library_omits_repeated_images_but_preserves_owned_complete_pdf(tmp_path, monkeypatch, bad_distinct):
    @compiles(JSONB, 'sqlite')
    def jsonb(type_, compiler, **kw):
        return 'JSON'

    monkeypatch.setattr(book_release, 'get_settings', lambda: SimpleNamespace(stories_dir=str(tmp_path)))
    engine = create_engine('sqlite:///' + (tmp_path / 'synthetic.db').as_posix())
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            buyer = User(channel='telegram', external_id='101')
            db.add(buyer)
            db.flush()
            child = Child(user_id=buyer.id, name='Synthetic', age=7)
            db.add(child)
            db.flush()
            ids = []
            # A full physical page of bad books must not hide an older valid book.
            for i in range(PAGE_SIZE + 3):
                order = Order(user_id=buyer.id, child_id=child.id, provider='telegram_stars',
                              provider_payment_id=f'synthetic-{i}', tariff='story', amount_rub=150, status='paid')
                db.add(order)
                db.flush()
                filename = f'{order.id:032x}.pdf'
                story = Story(order_id=order.id, child_id=child.id, episode_number=i + 1,
                              status='ready', title='Synthetic', pdf_url='/files/stories/' + filename)
                db.add(story)
                db.flush()
                path = tmp_path / filename
                _pdf(path, 5 if i == 0 else bad_distinct)
                if i == 0:
                    good_digest = hashlib.sha256(path.read_bytes()).hexdigest()
                ids.append(story.id)
            db.commit()
            assert [b['story_id'] for b in list_books(db, '101', None)['books']] == ids[:1]
            assert all(find_book(db, '101', i) is None for i in ids[1:])
            assert find_book(db, '101', ids[0])['pdf_sha256'] == good_digest
            assert find_book(db, '202', ids[0]) is None
            assert db.scalar(select(func.count(Order.id))) == len(ids)
            assert db.scalar(select(func.count(Story.id))) == len(ids)
    finally:
        engine.dispose()
        deregister(JSONB)
