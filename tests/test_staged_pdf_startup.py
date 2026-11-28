"""Crash during paid PDF assembly, restart the ASGI app, fetch the private PDF."""
import importlib
import io
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker


ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'synthetic-key-for-a-local-asgi-test-only'
HEADERS = {'X-Legend-Internal-Key': TOKEN}


def stage_book_then_exit(dsn):
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles
    from backend.app.config import Settings, get_settings

    @compiles(JSONB, 'sqlite')
    def compile_jsonb(type_, compiler, **kw):
        return 'JSON'

    Settings.database_url = property(lambda self: dsn)
    from backend.app import main
    from backend.app.services import story_service

    images = Path(get_settings().images_dir)
    images.mkdir()
    locators = []
    for i in range(5):
        name = f'{i:032x}.png'
        Image.new('RGB', (120, 70), (30 * i, 110, 170)).save(images / name)
        locators.append(f'/files/images/{name}')
    chapters = '\n\n'.join(f'Глава {n}. Test\n\nSaved chapter {n}.' for n in range(1, 5))
    story_service.generate_story_payload = lambda _: {'title': 'Saved book', 'story_text': chapters}
    story_service.generate_images = lambda **kw: (locators, None)
    story_service.generate_pdf = lambda **kw: os._exit(41)

    # The request dies after the normal HTTP handler commits text and images.
    with TestClient(main.app) as client:
        client.post('/api/story/generate', headers=HEADERS, json={
            'external_user_id': 'synthetic-restart', 'child_name': 'Demo', 'age': 7,
            'telegram_payment_charge_id': 'synthetic-restart-receipt',
        }).raise_for_status()
    raise AssertionError('PDF stage was not reached')


def test_staged_paid_book_recovers_on_startup_without_new_order_event(tmp_path, monkeypatch):
    from backend.app import db as db_module
    from backend.app.config import get_settings
    from backend.app.models import Order, Story
    from backend.app.services import pdf_service, story_service

    dsn = 'sqlite:///' + (tmp_path / 'receipt.db').as_posix()
    for key, value in {
        'IMAGES_DIR': str(tmp_path / 'images'), 'STORIES_DIR': str(tmp_path / 'stories'),
        'PUBLIC_BASE_URL': 'https://example.invalid', 'BACKEND_INTERNAL_TOKEN': TOKEN,
        'OPENROUTER_API_KEY': '', 'TOGETHER_API_KEY': '', 'OPENAI_API_KEY': '',
    }.items():
        monkeypatch.setenv(key, value)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(ROOT), os.getenv('PYTHONPATH', '')]))
    killed = subprocess.run([sys.executable, __file__, dsn], cwd=ROOT, env=env, capture_output=True,
                            timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert killed.returncode == 41, killed.stderr.decode(errors='replace')

    engine = create_engine(dsn)
    sessions = sessionmaker(bind=engine)
    try:
        with sessions() as db:
            receipt = db.scalars(select(Order)).one()
            story = db.scalars(select(Story)).one()
            assert receipt.status == 'paid' and story.order_id == receipt.id
            assert story.status == 'pdf_pending' and story.pdf_url is None
            story_id = story.id

        get_settings.cache_clear()
        settings = get_settings()
        with patch.object(db_module.Base.metadata, 'create_all'):
            main = importlib.import_module('backend.app.main')
        monkeypatch.setattr(main, 'settings', settings)
        monkeypatch.setattr(pdf_service, 'settings', settings)
        monkeypatch.setattr(db_module, 'SessionLocal', sessions)
        monkeypatch.setattr(main, 'SessionLocal', sessions)

        def forbidden(*args, **kwargs):
            raise AssertionError('Paid provider work must never repeat during PDF recovery')

        monkeypatch.setattr(story_service, 'generate_story_payload', forbidden)
        monkeypatch.setattr(story_service, 'generate_images', forbidden)
        monkeypatch.setattr(main, 'PDF_RECOVERY_INTERVAL', 0.02)
        scans = []

        def scan(factory):
            scans.append(True)
            if len(scans) == 1:
                raise ConnectionError('Synthetic temporary outage before the first scan')
            return story_service.recover_next_paid_pdf(factory)

        monkeypatch.setattr(main, 'recover_next_paid_pdf', scan)
        with TestClient(main.app) as client:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                with sessions() as db:
                    if db.get(Story, story_id).status == 'ready':
                        break
                time.sleep(0.02)
            result = client.get(f'/api/story/{story_id}', headers=HEADERS).json()
            assert result['status'] == 'ready' and len(scans) >= 2
            path = urlsplit(result['pdf_url']).path
            file_route = '/api/internal' + path
            assert client.get(file_route).status_code == 401
            download = client.get(file_route, headers=HEADERS)
            assert download.status_code == 200 and download.content.startswith(b'%PDF-')
            pages = PdfReader(io.BytesIO(download.content)).pages
            assert sum(len(page.images) for page in pages) >= 5
            assert 'Saved chapter 4.' in '\n'.join(page.extract_text() for page in pages)

        assert story_service.recover_next_paid_pdf(sessions) is False
        assert len(list((tmp_path / 'stories').glob('*.pdf'))) == 1
        with Session(engine) as db:
            assert db.scalar(select(func.count()).select_from(Order)) == 1
            assert db.scalar(select(func.count()).select_from(Story)) == 1
    finally:
        engine.dispose()
        get_settings.cache_clear()


if __name__ == '__main__':
    stage_book_then_exit(sys.argv[1])
