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
        'animated film scene in the style of Studio Ghibli "My Neighbor Totoro" (1988) by Hayao Miyazaki: '
        'clean cel animation, warm golden sunlight, bright lush green nature, '
        'soft expressive round characters with large eyes, smooth ink outlines, '
        'bright warm joyful uplifting atmosphere, vibrant cheerful colours, no dark tones'
    ),
    'disney': (
        'animated fairy-tale scene in the style of classic Disney "Sleeping Beauty" (1959): '
        'fluid elegant ink-outlined characters, bright rich jewel-tone colours, '
        'sparkling warm magical light, graceful rounded shapes, '
        'bright cheerful uplifting atmosphere, vivid saturated colours throughout'
    ),
    'pixar': (
        'premium cinematic 3D animated family fantasy feature film, '
        'top-tier modern animation studio quality: '
        'warm soft global illumination with volumetric depth, '
        'rich warm colour grading with vivid saturation, '
        'expressive stylised characters with polished high-detail faces, '
        'large emotive eyes, emotionally readable expressions and body language, '
        'soft subsurface skin glow, cinematic wide-angle composition, '
        'lush detailed environment, bright cheerful uplifting premium children\'s fantasy'
    ),
    'watercolor': (
        'bright cheerful children\'s book watercolour illustration '
        'in the style of Quentin Blake\'s illustrations for Roald Dahl books: '
        'energetic ink lines with bright colourful watercolour washes, '
        'warm golden natural light, loose expressive brushwork, '
        'vivid warm cheerful uplifting mood, white paper showing as highlights'
    ),
    'cartoon': (
        'bright bold children\'s cartoon illustration '
        'in the style of classic Cartoon Network shows and "The Smurfs": '
        'thick clean black outlines, flat bright saturated primary colours, '
        'simple bold friendly shapes, expressive large eyes, '
        'clean graphic look, bright sunny cheerful atmosphere, vivid uplifting colours'
    ),
    'storybook': (
        'classic illustrated children\'s storybook scene '
        'in the style of E.H. Shepard\'s Winnie-the-Pooh illustrations: '
        'warm pen-and-ink lines with golden watercolour washes, '
        'bright cosy warm light, friendly rounded character shapes, '
        'nostalgic cheerful uplifting atmosphere, warm amber and green tones'
    ),
    'soviet': (
        'Soviet children\'s animated cartoon scene '
        'in the exact style of Soyuzmultfilm "Cheburashka" (1966) and "Hedgehog in the Fog" (1975): '
        'thick clean black ink outlines, flat bright colours — sunshine yellow, '
        'bright red, sky blue, grass green, warm orange — no dark tones, '
        'simple rounded friendly character shapes with large soulful eyes, '
        'flat graphic clean look, bright warm sunny cheerful joyful atmosphere'
    ),
}

_BASE_QUALITY = (
    "children's book illustration, bright vibrant cheerful colours, warm sunlit happy atmosphere, "
    "wide establishing shot showing full scene, full body characters visible, "
    "high quality detailed professional illustration, safe for children, "
    "correct anatomy, exactly five fingers, "
    "only the named hero and the named animal companion in the scene — no extra people, no background crowd"
)

# Used for Stability AI and Pollinations (DALL-E 3 ignores negative_prompt parameter)
_NEGATIVE_PROMPT = (
    'color swatch, color chart, color palette diagram, palette grid, color picker, '
    'dark gloomy scene, dark atmosphere, horror, night scene, shadows, '
    'close-up portrait, headshot, face only, extreme close-up, '
    'dark skin on fair-skinned character, unexpected skin tone change, '
    'extra background people, crowd, strangers, unnamed characters, '
    'beard, mustache, stubble, facial hair on child, '
    'extra limbs, deformed hands, extra fingers, six fingers, bad anatomy, disfigured, '
    'watermark, signature, text label, username, blurry, low quality, ugly, '
    'UI elements, website screenshot, digital interface mockup, computer window'
)

# Inline "avoid" — embedded in every DALL-E 3 prompt (DALL-E 3 ignores negative_prompt param)
_DALLE_AVOID = (
    'Do NOT include: colour swatches, palette grids, comic panels, split-screen layout, '
    'collage, storyboard grid, dark or gloomy scenes, extra unnamed background people, '
    'extreme close-up face portraits, floating text labels, captions, UI windows, '
    'duplicate panels, watermarks, random props not in the scene'
)


def _save_image_bytes(data: bytes, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.png'
    path = out_dir / filename
    path.write_bytes(data)
    return filename


def _build_prompt(scene_prompt: str, char_desc: str = '', image_style: str = 'watercolor') -> str:
    """4-block: A(Style) + B(Character — front-loaded) + C(Scene) + D(Quality/Negative).

    Character block comes BEFORE the scene so DALL-E 3 anchors on character appearance
    before reading the action, reducing face/outfit drift across illustrations.
    """
    style = _IMG_STYLE_SUFFIX.get(image_style, _IMG_STYLE_SUFFIX['watercolor'])
    parts = [style]

    # B — Character block (front-loaded for consistency)
    if char_desc:
        parts.append(
            f"FIXED CHARACTER APPEARANCE — same in every illustration of this book: {char_desc}"
        )

    # C — Scene
    parts.append(scene_prompt)

    # D — Consistency + quality + anti-artifact
    parts.append(
        "Same art style, colour tones, and character proportions as all other "
        "illustrations in this storybook — one coherent visual universe"
    )
    parts.append(_BASE_QUALITY)
    parts.append(_DALLE_AVOID)

    return ". ".join(parts)[:3500]


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
