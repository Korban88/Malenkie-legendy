import base64
import hashlib
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from ..config import get_settings

settings = get_settings()

_IMG_STYLE_SUFFIX = {
    'watercolor': (
        'soft delicate hand-painted watercolor illustration, gentle gradients, natural pigment flow, '
        'subtle color transitions, slightly textured paper feel, light and airy atmosphere, '
        'minimal linework, soft edges, warm emotional tone, storybook aesthetic, '
        "children's book illustration quality, no harsh outlines, no digital gloss, "
        'fully finished illustration, no sketch elements, no palette strips, no paint swatches, '
        'no concept sheet, no unfinished areas, no random artifacts'
    ),
    'ghibli': (
        'hand-drawn anime style inspired by classic Japanese animated films, soft natural lighting, '
        'warm nostalgic atmosphere, expressive but simple faces, detailed but painterly backgrounds, '
        'cozy magical realism, gentle color palette, cinematic framing, emotional storytelling composition, '
        'clean linework, soft shading, fully rendered scene, no concept art look, no palettes, '
        'no sketch artifacts, no text, no collage, no storyboard layout'
    ),
    'soviet': (
        'classic Soviet animation style, hand-drawn 2D illustration, inspired by traditional Eastern European '
        'animated films, soft painterly backgrounds, expressive slightly stylized characters, '
        'warm nostalgic tone, muted but rich color palette, gentle shading, subtle texture of brush or pencil, '
        'emotionally sincere and calm atmosphere, simple but strong storytelling composition, '
        "children's classic animation aesthetic, no modern glossy rendering, no 3D look, "
        'fully finished illustration, no sketch page, no palette strips, no paint swatches, '
        'no concept sheet, no digital artifacts, no text'
    ),
    'pixar': (
        'premium cinematic 3D animated feature film look, highly polished character design, '
        'soft global illumination, volumetric light, expressive realistic eyes, smooth materials, '
        'high detail faces, believable lighting, family-friendly fantasy mood, rich environment detail, '
        'strong composition focus, fully rendered high-quality image, no concept art, no palette strips, '
        'no paint swatches, no sketch look, no unfinished render, no artifacts'
    ),
    'cartoon': (
        'bright flat cartoon style, bold clean shapes, solid color fills, minimal shading, strong outlines, '
        'simple expressive characters, playful composition, high contrast colors, vector-like clarity, '
        'children-friendly design, clean and polished, no gradients overload, no painterly textures, '
        'no sketch lines, no palette strips, no concept sheet, no artifacts, no text'
    ),
    'storybook': (
        "classic children's book illustration style, rich storytelling composition, "
        'balanced detailed scene, soft painterly rendering, controlled brushwork, warm natural colors, '
        'slightly textured traditional feel, high-quality publishing illustration, carefully composed scene, '
        'emotionally clear, fully finished artwork, no sketch, no palettes, no paint swatches, '
        'no concept art, no unfinished look, no artifacts'
    ),
    'disney': (
        "classic Disney fairy-tale animation style, vibrant jewel-tone colors, elegant ink-outlined characters, "
        'sparkling warm magical light, graceful expressive characters, rich detailed backgrounds, '
        'fully rendered scene, no concept art, no palette strips, no sketch, no artifacts'
    ),
}

_BASE_QUALITY = (
    "children's book illustration, bright vibrant cheerful colours, warm sunlit happy atmosphere, "
    "wide establishing shot showing full scene, full body characters visible, "
    "high quality detailed professional illustration, safe for children, "
    "CHILD as protagonist — NO adult men, NO adult women as the main foreground character, "
    "correct child anatomy, no extra background crowd"
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
    'Avoid: no palette strips, no color swatches, no concept art, no sketch, '
    'no unfinished illustration, no collage, no comic panels, no extra characters, '
    'no inconsistent faces, no distorted anatomy, no text in image, no style mixing, '
    'no visual artifacts, no adult men or women as main foreground character'
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
