"""Synthetic reference-sequence regression, no external calls."""
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image
from backend.app.services import image_service as service

SCENES = ['cover', 'one', 'two', 'three', 'four']

def png_bytes():
    out = BytesIO()
    Image.new('RGB', (32, 24), 'navy').save(out, format='PNG')
    return out.getvalue()

@pytest.mark.parametrize('route', ['stability', 'together'])
@pytest.mark.parametrize('fault_slot', [0, 2])
@pytest.mark.parametrize('fault', ['bad_bytes', 'empty', 'truncated', 'missing', 'wrong_format'])
def test_invalid_reference_slot_stops_before_next_request(tmp_path, monkeypatch, route, fault_slot, fault):
    cfg = SimpleNamespace(image_provider=route, stability_api_key='synthetic-only',
        keep_uploaded_photo=False, images_dir=str(tmp_path), public_base_url='https://test.invalid')
    monkeypatch.setattr(service, 'settings', cfg)
    monkeypatch.setattr(service, '_build_prompt', lambda scene,*a,**k:scene)
    sign = Mock(return_value='https://test.invalid/signed')
    monkeypatch.setattr(service, 'sign_cover_reference', sign)
    calls=[]
    def fake(*args, **kwargs):
        i=len(calls); calls.append((args,kwargs)); name=f'{i+1:032x}.png'
        data=png_bytes()
        if i==fault_slot:
            if fault=='bad_bytes': data=b'provider returned HTML'
            elif fault=='empty': data=b''
            elif fault=='truncated': data=data[:len(data)//2]
            elif fault=='wrong_format':
                out=BytesIO(); Image.new('RGB',(32,24)).save(out,format='GIF'); data=out.getvalue()
            elif fault=='missing': return name
        (Path(tmp_path)/name).write_bytes(data)
        return name
    monkeypatch.setattr(service, '_stability_generate' if route=='stability' else '_generate_single',fake)
    import base64
    photo=base64.b64encode(png_bytes()).decode() if route=='stability' else None
    urls,_=service.generate_images('synthetic',7,'nature',photo,scene_prompts=SCENES)
    assert len(calls)==fault_slot+1
    assert all(urls[:fault_slot]) and urls[fault_slot:]==[None]*(5-fault_slot)
    if route=='together' and fault_slot==0:
        assert sign.call_count==1  # configuration preflight only; no signing of bad cover

@pytest.mark.parametrize('route',['stability','together'])
def test_valid_reference_sequence(tmp_path,monkeypatch,route):
    cfg=SimpleNamespace(image_provider=route,stability_api_key='synthetic-only',keep_uploaded_photo=False,
        images_dir=str(tmp_path),public_base_url='https://test.invalid')
    monkeypatch.setattr(service,'settings',cfg)
    monkeypatch.setattr(service,'_build_prompt',lambda scene,*a,**kw:scene)
    monkeypatch.setattr(service,'sign_cover_reference',Mock(return_value='https://test.invalid/signed'))
    import base64
    data=png_bytes(); photo=base64.b64encode(data).decode() if route=='stability' else None
    refs=[]
    def fake(prompt,ref,*args,**kwargs):
        refs.append((ref,kwargs.get('cover_url'))); name=f'{len(refs):032x}.png'; (tmp_path/name).write_bytes(data); return name
    monkeypatch.setattr(service,'_stability_generate' if route=='stability' else '_generate_single',fake)
    urls,_=service.generate_images('synthetic',7,'nature',photo,scene_prompts=SCENES)
    assert len(refs)==5 and all(urls)
    if route=='stability': assert all(ref==photo for ref,_ in refs)
    else: assert refs[0][1] is None and all(url=='https://test.invalid/signed' for _,url in refs[1:])
