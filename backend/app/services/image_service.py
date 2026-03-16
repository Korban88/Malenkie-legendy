import base64
import hashlib
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from ..config import get_settings

settings = get_settings()

_IMG_STYLE_SUFFIX = {
    'ghibli':     'Studio Ghibli style, soft hand-painted watercolor, anime-inspired, gentle whimsical atmosphere, Miyazaki',
    'disney':     'Disney fairy tale animation style, vibrant cheerful colors, cute rounded characters, magical sparkles',
    'pixar':      'Pixar 3D animation style, richly detailed, warm cinematic lighting, expressive characters, subsurface scattering',
    'watercolor': 'soft watercolor illustration, dreamy pastel tones, gentle brushstrokes, traditional watercolor art',
    'cartoon':    'cartoon illustration, bold black outlines, bright saturated colors, playful flat style',
    'storybook':  "classic children's storybook illustration, detailed ink and watercolor, warm cozy golden tones",
    'soviet':     'Soviet Soyuzmultfilm animation style exactly as in Cheburashka 1966, classic USSR cartoon, thick clean outlines, warm muted earthy palette, flat 2D, 1970s Soyuzmultfilm aesthetic',
}

_BASE_QUALITY = (
    "children's book illustration, safe for children, no text, no watermark, "
    "high quality, detailed, professional illustration, "
    "correct human anatomy, exactly five fingers on each hand, no extra limbs, only named characters in scene"
)

# Artifacts to avoid in human characters
_NEGATIVE_PROMPT = (
    'beard, mustache, goatee, facial hair, stubble on child, '
    'tails on humans, animal features on human characters, extra limbs, deformed hands, '
    'extra fingers, six fingers, mutated body, bad anatomy, disfigured, '
    'poorly drawn face, extra arms, extra legs, cloned face, '
    'instrument held incorrectly, playing flute through nose, wrong hand position, '
    'watermark, signature, text, username, blurry, low quality, ugly'
)


def _save_image_bytes(data: bytes, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.png'
    path = out_dir / filename
    path.write_bytes(data)
    return filename


def _build_prompt(scene_prompt: str, image_style: str = 'watercolor') -> str:
    """Build final prompt: style FIRST so DALL-E applies it consistently."""
    style = _IMG_STYLE_SUFFIX.get(image_style, _IMG_STYLE_SUFFIX['watercolor'])
    # Style goes first — DALL-E weights the beginning of the prompt most heavily
    base = f"{style}. {scene_prompt}. {_BASE_QUALITY}"
    return base[:1200]


def generate_images(child_name, age, style, photo_base64, char_desc='',
                    scene_prompts=None, count=5, image_style='watercolor'):
    urls: list[str | None] = [None] * count   # fixed-size: indices preserved even on failure
    photo_hash = None
    out_dir = Path(settings.images_dir)
    if photo_base64:
        raw_photo = base64.b64decode(photo_base64)
        photo_hash = hashlib.sha256(raw_photo).hexdigest()
        if settings.keep_uploaded_photo:
            _save_image_bytes(raw_photo, out_dir)
    for i in range(count):
        if scene_prompts and i < len(scene_prompts):
            scene = scene_prompts[i]
            # Prepend locked character description to every scene for visual consistency
            base_prompt = f"{char_desc}. {scene}" if char_desc else scene
        else:
            base_prompt = (f"{char_desc}. " if char_desc else "") + (
                f"{age}-year-old child named {child_name} in {style} fairy tale scene {i + 1}"
            )
        prompt = _build_prompt(base_prompt, image_style)
        try:
            filename = _generate_single(prompt, photo_base64 if i > 0 else None)
            urls[i] = f'{settings.public_base_url}/files/images/{filename}'
        except Exception:
            pass  # slot stays None; index positions are preserved
    return urls, photo_hash


def _generate_single(prompt, photo_base64):
    provider = settings.image_provider
    if provider == 'openai':
        try:
            return _openai_generate(prompt)
        except Exception:
            if settings.backup_image_provider == 'pollinations':
                return _pollinations_generate(prompt)
            raise
    if provider == 'stability':
        try:
            return _stability_generate(prompt, photo_base64)
        except Exception:
            if settings.backup_image_provider == 'pollinations':
                return _pollinations_generate(prompt)
            raise
    if provider == 'pollinations':
        return _pollinations_generate(prompt)
    raise ValueError(f'Unsupported image provider: {provider}')


def _openai_generate(prompt):
    if not settings.openai_api_key:
        raise RuntimeError('OPENAI_API_KEY is not configured')
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    # Use landscape format for wide page layout
    response = client.images.generate(
        model='dall-e-2', prompt=prompt[:1000], size='1024x1024', n=1
    )
    image_url = response.data[0].url
    img_response = httpx.get(image_url, timeout=60)
    img_response.raise_for_status()
    return _save_image_bytes(img_response.content, Path(settings.images_dir))


def _stability_generate(prompt, photo_base64):
    if not settings.stability_api_key:
        raise RuntimeError('STABILITY_API_KEY is not configured')
    out_dir = Path(settings.images_dir)
    if photo_base64:
        photo_bytes = base64.b64decode(photo_base64)
        response = httpx.post(
            'https://api.stability.ai/v2beta/stable-image/control/style',
            headers={'Authorization': f'Bearer {settings.stability_api_key}', 'Accept': 'image/*'},
            data={
                'prompt': prompt,
                'negative_prompt': _NEGATIVE_PROMPT,
                'output_format': 'png',
                'aspect_ratio': '16:9',
                'fidelity': 0.6,
            },
            files={'image': ('reference.png', photo_bytes, 'image/png')},
            timeout=120,
        )
        if response.status_code == 200:
            return _save_image_bytes(response.content, out_dir)
    response = httpx.post(
        'https://api.stability.ai/v2beta/stable-image/generate/core',
        headers={'Authorization': f'Bearer {settings.stability_api_key}', 'Accept': 'image/*'},
        data={
            'prompt': prompt,
            'negative_prompt': _NEGATIVE_PROMPT,
            'output_format': 'png',
            'aspect_ratio': '16:9',
        },
        timeout=120,
    )
    response.raise_for_status()
    return _save_image_bytes(response.content, out_dir)


def _pollinations_generate(prompt):
    # Use landscape 16:9 format and add negative prompt support
    encoded = quote(prompt)
    encoded_neg = quote(_NEGATIVE_PROMPT)
    url = f'https://image.pollinations.ai/prompt/{encoded}?width=1280&height=720&nologo=true&negative={encoded_neg}'
    response = httpx.get(url, timeout=120)
    response.raise_for_status()
    return _save_image_bytes(response.content, Path(settings.images_dir))
