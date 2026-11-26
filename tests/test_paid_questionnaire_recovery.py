"""Real process interruption on an isolated SQLite receipt, no API/payment.

PostgreSQL concurrency remains covered by the separate PostgreSQL test fixture.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles, deregister
from sqlalchemy.orm import Session

from backend.app.db import Base
from backend.app.models import Child, Order, Story
from backend.app.services import story_service


def test_killed_generation_retains_paid_questionnaire_and_recovery_uses_it(tmp_path, monkeypatch):
    @compiles(JSONB, 'sqlite')
    def jsonb(type_, compiler, **kw):
        return 'JSON'

    dsn = 'sqlite:///' + (tmp_path/'receipt.db').as_posix()
    engine = create_engine(dsn)
    try:
        Base.metadata.create_all(engine)
        payload = {'external_user_id':'synthetic-buyer-snapshot','child_name':'Тест',
                   'age':7,'gender':'neutral','style':'auto','purpose':'friendship',
                   'favorite_animal':'лиса','favorite_color':'зелёный','hobby':'плавание',
                   'favorite_place':'озеро','telegram_payment_charge_id':'synthetic-snapshot-charge',
                   'photo_base64':'SYNTHETIC_DATA_MUST_NOT_PERSIST'}
        script = '''
import json, os, sys
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from backend.app.services import story_service
@compiles(JSONB,'sqlite')
def jsonb(t,c,**kw): return 'JSON'
def crash(_): os._exit(17)
story_service.generate_story_payload=crash
with Session(create_engine(sys.argv[1])) as db:
    story_service.generate_story(db,json.loads(sys.argv[2]))
'''
        env = dict(os.environ, OPENROUTER_API_KEY='', OPENAI_API_KEY='', TOGETHER_API_KEY='')
        result = subprocess.run([sys.executable,'-c',script,dsn,json.dumps(payload)],
                                cwd=Path(__file__).resolve().parents[1],env=env,
                                capture_output=True,text=True,timeout=20)
        assert result.returncode == 17, result.stderr
        with Session(engine) as db:
            receipt = db.scalar(select(Order))
            snapshot = dict(receipt.meta['questionnaire_v1'])
            assert receipt.status == 'paid'
            assert snapshot['favorite_animal'] == 'лиса'
            assert snapshot['purpose'] == 'friendship'
            assert 'photo_base64' not in snapshot
            assert 'SYNTHETIC_DATA_MUST_NOT_PERSIST' not in json.dumps(receipt.meta)
            assert db.scalar(select(func.count()).select_from(Story)) == 0
            child = db.get(Child,receipt.child_id)
            child.favorite_animal = 'тигр'
            db.commit()
            child_id, order_id = child.id, receipt.id

        calls=[]
        def text(inputs):
            calls.append(inputs)
            return {'title':'Синтетический результат','story_text':'Синтетический текст.'}
        monkeypatch.setattr(story_service,'generate_story_payload',text)
        monkeypatch.setattr(story_service,'generate_images',lambda **kw: (['fixture']*5,None))
        monkeypatch.setattr(story_service,'require_complete_images',lambda _:None)
        monkeypatch.setattr(story_service,'generate_pdf',lambda **kw:'fixture-pdf')
        monkeypatch.setattr(story_service,'require_complete_pdf',lambda _:None)
        retry={**payload,'order_id':order_id,'child_id':child_id,
               'purpose':'changed-after-payment','favorite_animal':'медведь','image_style':'changed'}
        with Session(engine) as db:
            first=story_service.generate_story(db,retry)
            first_id=first.id
        with Session(engine) as restarted:
            second=story_service.generate_story(restarted,retry)
            assert second.id == first_id
            assert restarted.scalar(select(func.count()).select_from(Order)) == 1
            assert restarted.scalar(select(func.count()).select_from(Story)) == 1
            assert restarted.get(Order,order_id).meta['questionnaire_v1'] == snapshot
        assert len(calls) == 1
        assert calls[0]['favorite_animal'] == 'лиса'
        assert calls[0]['purpose'] == 'friendship'
        assert calls[0]['image_style'] == 'watercolor'
    finally:
        engine.dispose()
        deregister(JSONB)
