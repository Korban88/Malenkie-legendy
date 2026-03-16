import base64
import hashlib
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from ..config import get_settings

settings = get_settings()

_IMG_STYLE_SUFFIX = {
    'ghibli': (
        'Studio Ghibli hand-painted animation cel, Hayao Miyazaki style. '
        'LINEART: clean ink outlines with slight line-weight variation. '
        'PALETTE LOCKED: warm ochre sunlight, deep forest green, sky cerulean, cream white, rust red — same palette in every scene. '
        'SHADING: soft 2-tone cel shading, no gradients. '
        'TEXTURE: subtle film grain on backgrounds. '
        'LIGHTING: warm golden-hour glow from upper-right in every image. '
        'Detailed organic backgrounds, expressive chubby character proportions'
    ),
    'disney': (
        'classic Disney fairy-tale animation cel, 1950s–1990s style. '
        'LINEART: smooth fluid ink outlines, consistent line weight throughout. '
        'PALETTE LOCKED: royal blue, antique gold, crimson, forest green, ivory — same palette in every scene. '
        'SHADING: clean 2-tone cel fills, no gradients. '
        'LIGHTING: warm magical glow, rim-light on characters. '
        'Elegant character proportions, lush decorative backgrounds'
    ),
    'pixar': (
        'Pixar 3D CG animation film still, consistent render style. '
        'MATERIAL: subsurface skin scattering, soft cloth texture. '
        'PALETTE LOCKED: warm amber highlights, cool blue-grey shadows, saturated mid-tones — same palette in every scene. '
        'LIGHTING: cinematic soft three-point light, warm key from upper-left. '
        'RENDERING: photorealistic textures, stylized character shapes. '
        'Strong depth of field, bokeh background'
    ),
    'watercolor': (
        'traditional watercolor children\'s-book illustration, identical style across all scenes. '
        'TECHNIQUE: wet-on-wet washes, ink outlines bleeding slightly into paint. '
        'PALETTE LOCKED: warm amber, soft sage green, dusty sky-blue, ivory, warm sienna — same palette every image. '
        'TEXTURE: visible paper grain, white highlights left unpainted. '
        'LINEART: loose confident ink lines. '
        'LIGHTING: soft diffused natural light from upper-left, no harsh shadows'
    ),
    'cartoon': (
        'bold cartoon illustration, identical graphic style across all scenes. '
        'LINEART: thick uniform black outlines, same weight everywhere. '
        'PALETTE LOCKED: bright red, sunshine yellow, cobalt blue, black, white — same palette every image. '
        'SHADING: flat colour fills only, zero gradients. '
        'STYLE: geometric simplified shapes, large round eyes. '
        'COMPOSITION: strong graphic silhouettes, flat background shapes'
    ),
    'storybook': (
        'classic illustrated children\'s storybook, consistent across all scenes. '
        'TECHNIQUE: fine pen crosshatching with warm watercolour washes. '
        'PALETTE LOCKED: golden amber, forest brown, moss green, cream, deep navy — same palette every image. '
        'TEXTURE: aged paper, visible ink hatching, decorative borders. '
        'LINEART: fine detailed pen lines. '
        'LIGHTING: warm candle-golden glow, cosy atmosphere'
    ),
    'soviet': (
        'Soviet Soyuzmultfilm cel animation 1969, Roman Kachanov Cheburashka style, identical in every scene. '
        'LINEART: thick uniform black ink outlines, slightly wobbly hand-drawn quality. '
        'PALETTE LOCKED: warm ochre, burnt sienna, sage green, cream, dusty rose, sky blue — ONLY these colours, every image. '
        'SHADING: flat 2D solid cel fills, zero gradients, no blending. '
        'TEXTURE: visible cel-paint grain, slight colour registration offset. '
        'CHARACTERS: chubby rounded shapes, large soulful eyes, gentle expressions. '
        'BACKGROUNDS: simple geometric flat shapes, minimal detail'
    ),
}

_BASE_QUALITY = (
    "children's book illustration, safe for children, no text, no watermark, "
    "wide establishing shot, full body characters visible in scene, "
    "high quality, detailed, professional illustration, "
    "correct human anatomy, exactly five fingers on each hand, no extra limbs, only named characters in scene"
)

# Artifacts to avoid in human characters
_NEGATIVE_PROMPT = (
    'close-up portrait, headshot, face only, head only, bust portrait, extreme close-up, '
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


_CONSISTENCY_ANCHOR = (
    'VISUAL CONSISTENCY: this illustration is part of a single storybook — '
    'it must match the EXACT same art style, locked colour palette, line-art technique, '
    'character proportions, and lighting direction as all other images in this story'
)


def _build_prompt(scene_prompt: str, char_desc: str = '', image_style: str = 'watercolor') -> str:
    """Build final prompt: locked style + scene action + character + consistency anchor."""
    style = _IMG_STYLE_SUFFIX.get(image_style, _IMG_STYLE_SUFFIX['watercolor'])
    if char_desc:
        base = (f"{style}. "
                f"{scene_prompt}. "
                f"The main character is {char_desc}. "
                f"{_CONSISTENCY_ANCHOR}. "
                f"{_BASE_QUALITY}")
    else:
        base = (f"{style}. "
                f"{scene_prompt}. "
                f"{_CONSISTENCY_ANCHOR}. "
                f"{_BASE_QUALITY}")
    return base[:3000]


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
        else:
            scene = f"{age}-year-old child named {child_name} in {style} fairy tale scene {i + 1}"
        # char_desc passed separately so scene action comes first in the prompt
        prompt = _build_prompt(scene, char_desc, image_style)
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
        model='dall-e-3', prompt=prompt[:4000], size='1024x1024',
        quality='standard', style='natural', n=1
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
    url = f'https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&negative={encoded_neg}&model=flux'
    response = httpx.get(url, timeout=120)
    response.raise_for_status()
    return _save_image_bytes(response.content, Path(settings.images_dir))
