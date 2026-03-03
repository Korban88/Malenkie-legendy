import base64
import hashlib
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from ..config import get_settings

settings = get_settings()


def _save_image_bytes(data: bytes, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.png'
    path = out_dir / filename
    path.write_bytes(data)
    return filename


def image_prompt(child_name: str, age: int, style: str, scene_idx: int) -> str:
    return (
        f"children's book illustration, {style} style, kid hero named {child_name}, age {age}, "
        f'scene #{scene_idx + 1}, warm colors, detailed, safe content, no text'
    )


def generate_images(child_name: str, age: int, style: str, photo_base64: str | None, count: int = 3) -> tuple[list[str], str | None]:
    urls: list[str] = []
    photo_hash = None
    out_dir = Path(settings.images_dir)

    if photo_base64:
        raw_photo = base64.b64decode(photo_base64)
        photo_hash = hashlib.sha256(raw_photo).hexdigest()
        if settings.keep_uploaded_photo:
            _save_image_bytes(raw_photo, out_dir)

    for i in range(count):
        prompt = image_prompt(child_name, age, style, i)
        filename = _generate_single(prompt, photo_base64)
        urls.append(f'{settings.public_base_url}/files/images/{filename}')

    return urls, photo_hash


def _generate_single(prompt: str, photo_base64: str | None) -> str:
    if settings.image_provider == 'stability':
        try:
            return _stability_generate(prompt, photo_base64)
        except Exception:
            if settings.backup_image_provider == 'pollinations':
                return _pollinations_generate(prompt)
            raise

    if settings.image_provider == 'pollinations':
        return _pollinations_generate(prompt)

    raise ValueError(f'Unsupported image provider: {settings.image_provider}')


def _stability_generate(prompt: str, photo_base64: str | None) -> str:
    if not settings.stability_api_key:
        raise RuntimeError('STABILITY_API_KEY is not configured')

    form_data = {'prompt': prompt, 'output_format': 'png'}
    files = None
    if photo_base64:
        files = {'image': ('reference.png', base64.b64decode(photo_base64), 'image/png')}

    response = httpx.post(
        'https://api.stability.ai/v2beta/stable-image/generate/core',
        headers={'Authorization': f'Bearer {settings.stability_api_key}', 'Accept': 'image/*'},
        data=form_data,
        files=files,
        timeout=120,
    )
    response.raise_for_status()
    return _save_image_bytes(response.content, Path(settings.images_dir))


def _pollinations_generate(prompt: str) -> str:
    response = httpx.get(
        'https://image.pollinations.ai/prompt/' + quote(prompt),
        timeout=120,
    )
    response.raise_for_status()
    return _save_image_bytes(response.content, Path(settings.images_dir))
