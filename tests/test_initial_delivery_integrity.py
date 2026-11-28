import asyncio
import hashlib
import ast
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from pypdf import PdfWriter
from io import BytesIO

BOT_SOURCE = Path(__file__).resolve().parents[1] / "bot" / "bot.py"
class TelegramAPIError(Exception): pass
class Message:
    def __init__(self, *, user=101, chat_type='private', chat_id=101):
        self.from_user = SimpleNamespace(id=user)
        self.chat = SimpleNamespace(type=chat_type, id=chat_id)
        self.answer = AsyncMock()
        self.answer_document = AsyncMock()
class FSMContext:
    def __init__(self):
        self.get_data = AsyncMock(return_value={'order_id': 3})
        self.clear = AsyncMock()

def pdf(width):
    writer = PdfWriter(); writer.add_blank_page(width=width,height=100)
    buf=BytesIO(); writer.write(buf); return buf.getvalue()

@pytest.mark.parametrize('case', ['valid','changed_file','invalid_digest','unowned','different_locator','different_episode','group','wrong_buyer','preview_failure','newer_questionnaire'])
def test_first_delivery(case):
    verified = pdf(100); changed = pdf(101)
    buyer=Message(user=999 if case=='wrong_buyer' else 101,
                  chat_type='group' if case=='group' else 'private',
                  chat_id=-200 if case=='group' else 999 if case=='wrong_buyer' else 101)
    state=FSMContext()
    if case=='newer_questionnaire': state.get_data.return_value={'order_id':4}
    data={'external_user_id':'101','order_id':3,'child_name':'Synthetic'}
    result={'story_id':4,'status':'ready','episode_number':1,'story_text':'Глава 1\nSynthetic story.',
            'images_urls':['cover','scene1','scene2','scene3','scene4'],'pdf_url':'/files/stories/fixture.pdf'}
    book={'pdf_url':result['pdf_url'],'episode_number':1,'pdf_sha256':hashlib.sha256(verified).hexdigest()}
    if case=='invalid_digest': book['pdf_sha256']='bad'
    if case=='different_locator': book['pdf_url']='/files/stories/other.pdf'
    if case=='different_episode': book['episode_number']=2
    async def lookup(endpoint,payload):
        assert endpoint=='library/4' and payload=={'external_user_id':'101'}
        if case=='unowned': raise httpx.HTTPStatusError('not found',request=httpx.Request('POST','https://synthetic.invalid'),response=httpx.Response(404))
        return book
    check=AsyncMock(side_effect=lookup)
    download=AsyncMock(return_value=('fixture.pdf',changed if case=='changed_file' else verified))
    send_image=AsyncMock(return_value=case!='preview_failure')
    ctx=dict(Message=Message,FSMContext=FSMContext,TelegramAPIError=TelegramAPIError,re=re,hashlib=hashlib,httpx=httpx,
             BufferedInputFile=lambda content,filename:SimpleNamespace(content=content,filename=filename),
             _download_private_media=download,_checkout_request=check,_send_image=send_image,
             _genitive=lambda s:s,kb_after_story=lambda *a:None)
    # Compile only these real handlers; importing the bot would initialize
    # its Telegram client. All I/O is synthetic and no network call is made.
    parsed = ast.parse(BOT_SOURCE.read_text(encoding='utf-8'))
    wanted = {'_send_pdf', '_deliver_generated_book'}
    funcs = [node for node in parsed.body if isinstance(node, ast.AsyncFunctionDef) and node.name in wanted]
    assert {node.name for node in funcs} == wanted
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(BOT_SOURCE), 'exec'), ctx)
    asyncio.run(ctx['_deliver_generated_book'](buyer,state,data,result))
    success=case in ('valid','preview_failure','newer_questionnaire')
    assert buyer.answer_document.await_count==int(success)
    assert state.clear.await_count==int(success and case!='newer_questionnaire')
    if success: assert buyer.answer_document.await_args.kwargs['document'].content==verified
    if case in ('group','wrong_buyer'):
        check.assert_not_awaited();send_image.assert_not_awaited();buyer.answer.assert_not_awaited()
    if case in ('unowned','invalid_digest','different_locator','different_episode'):
        send_image.assert_not_awaited();download.assert_not_awaited()
    if case=='changed_file': download.assert_awaited_once()
