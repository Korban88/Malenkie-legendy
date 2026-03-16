import base64
import hashlib
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from ..config import get_settings

settings = get_settings()

# Shot-type modifiers ensure visual diversity across the 8 illustrations
_SHOT_MODIFIERS = [
    "wide panoramic establishing shot, atmospheric, no characters visible",
    "medium shot, child protagonist as focus, expressive face, dynamic pose",
    "dramatic low angle, intense atmosphere, contrasting shadows and light",
    "close-up portrait, magical animal companion, expressive eyes, detailed",
    "wide joyful shot, warm golden sunlight, triumphant celebration moment",
    "over-the-shoulder view, exploring magical landscape, sense of wonder",
    "gentle medium shot, two characters side by side, peaceful and warm",
    "wide triumphant shot, golden hour light, heroes victorious, epic moment",
]

# Image style presets — maps image_style key to DALL-E prompt suffix
_IMG_STYLE_SUFFIX = {
    'ghibli':     'Studio Ghibli style exactly as in My Neighbor Totoro, Hayao Miyazaki signature soft hand-painted watercolor, gentle rounded shapes, muted natural palette, warm luminous backgrounds',
    'soviet':     'Soviet Soyuzmultfilm animation style, exactly like Cheburashka and Crocodile Gena 1966, classic USSR cartoon, simple clean outlines with thick borders, warm muted earthy palette, flat 2D nostalgia, 1970s animation aesthetic',
    'pixar':      'Pixar 3D animation style exactly as in Toy Story and Up, richly detailed subsurface scattering skin, warm cinematic rim lighting, expressive rounded characters',
    'watercolor': 'soft traditional watercolor illustration, dreamy pastel tones, visible gentle brushstrokes, wet-on-wet blending, white paper showing through, loose artistic style',
    'cartoon':    'classic cartoon illustration, bold black outlines, bright saturated flat colors, playful fun style, cel-shading',
    'storybook':  "classic children's storybook illustration, detailed ink-and-watercolor, warm cozy texture, golden-age book art",
}

_BASE_QUALITY = (
    "children's book illustration, safe for children, no text, no watermark, "
    "high quality, detailed, professional illustration, "
    "correct human anatomy, exactly five fingers on each hand, no extra limbs, "
    "only named characters in scene, no background strangers"
)


def _save_image_bytes(data: bytes, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.png'
    path = out_dir / filename
    path.write_bytes(data)
    return filename


def _build_prompt(scene_prompt: str, style: str, shot_idx: int,
                  image_style: str = 'watercolor') -> str:
    img_style_sfx = _IMG_STYLE_SUFFIX.get(image_style, _IMG_STYLE_SUFFIX['watercolor'])
    shot_mod = _SHOT_MODIFIERS[shot_idx] if shot_idx < len(_SHOT_MODIFIERS) else ''
    base = f"{scene_prompt}, {shot_mod}, {img_style_sfx}, {_BASE_QUALITY}"
    return base[:950]


def generate_images(
    child_name: str,
    age: int,
    style: str,
    photo_base64: str | None,
    scene_prompts: list[str] | None = None,
    count: int = 8,
    image_style: str = 'watercolor',
) -> tuple[list[str], str | None]:
    urls: list[str] = []
    photo_hash = None
    out_dir = Path(settings.images_dir)

    if photo_base64:
        raw_photo = base64.b64decode(photo_base64)
        photo_hash = hashlib.sha256(raw_photo).hexdigest()
        if settings.keep_uploaded_photo:
            _save_image_bytes(raw_photo, out_dir)

    # Single seed per story for consistent style across all images (Pollinations)
    import random
    story_seed = random.randint(10000, 99999)

    for i in range(count):
        if scene_prompts and i < len(scene_prompts):
            base_prompt = scene_prompts[i]
        else:
            base_prompt = (
                f"children's book illustration, {age}-year-old child named {child_name}, "
                f"{style} fairy tale scene {i + 1}"
            )

        prompt = _build_prompt(base_prompt, style, i, image_style)

        try:
            filename = _generate_single(prompt, photo_base64 if i > 0 else None, seed=story_seed + i)
            urls.append(f'{settings.public_base_url}/files/images/{filename}')
        except Exception:
            pass

    return urls, photo_hash


def _generate_single(prompt: str, photo_base64: str | None, seed: int = 42) -> str:
    provider = settings.image_provider

    if provider == 'openai':
        try:
            return _openai_generate(prompt)
        except Exception:
            if settings.backup_image_provider == 'pollinations':
                return _pollinations_generate(prompt, seed)
            raise

    if provider == 'stability':
        try:
            return _stability_generate(prompt, photo_base64)
        except Exception:
            if settings.backup_image_provider == 'pollinations':
                return _pollinations_generate(prompt, seed)
            raise

    if provider == 'pollinations':
        return _pollinations_generate(prompt, seed)

    raise ValueError(f'Unsupported image provider: {provider}')


def _openai_generate(prompt: str) -> str:
    if not settings.openai_api_key:
        raise RuntimeError('OPENAI_API_KEY is not configured')

    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)

    # dall-e-2: ~$0.020/image vs dall-e-3 $0.040/image — 2x cheaper for mass generation
    response = client.images.generate(
        model='dall-e-2',
        prompt=prompt[:1000],  # dall-e-2 limit is 1000 chars
        size='1024x1024',
        n=1,
    )
    image_url = response.data[0].url

    img_response = httpx.get(image_url, timeout=60)
    img_response.raise_for_status()
    return _save_image_bytes(img_response.content, Path(settings.images_dir))


def _stability_generate(prompt: str, photo_base64: str | None) -> str:
    if not settings.stability_api_key:
        raise RuntimeError('STABILITY_API_KEY is not configured')

    out_dir = Path(settings.images_dir)

    if photo_base64:
        photo_bytes = base64.b64decode(photo_base64)
        response = httpx.post(
            'https://api.stability.ai/v2beta/stable-image/control/style',
            headers={
                'Authorization': f'Bearer {settings.stability_api_key}',
                'Accept': 'image/*',
            },
            data={'prompt': prompt, 'output_format': 'png', 'fidelity': 0.6},
            files={'image': ('reference.png', photo_bytes, 'image/png')},
            timeout=120,
        )
        if response.status_code == 200:
            return _save_image_bytes(response.content, out_dir)

    response = httpx.post(
        'https://api.stability.ai/v2beta/stable-image/generate/core',
        headers={
            'Authorization': f'Bearer {settings.stability_api_key}',
            'Accept': 'image/*',
        },
        data={'prompt': prompt, 'output_format': 'png'},
        timeout=120,
    )
    response.raise_for_status()
    return _save_image_bytes(response.content, out_dir)


def _pollinations_generate(prompt: str, seed: int = 42) -> str:
    response = httpx.get(
        'https://image.pollinations.ai/prompt/' + quote(prompt),
        params={'seed': seed, 'width': 1024, 'height': 1024, 'nologo': 'true'},
        timeout=120,
    )
    response.raise_for_status()
    return _save_image_bytes(response.content, Path(settings.images_dir))
