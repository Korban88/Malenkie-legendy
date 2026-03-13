import base64
import hashlib
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from ..config import get_settings

settings = get_settings()

# Shot-type modifiers ensure visual diversity across the 5 illustrations
_SHOT_MODIFIERS = [
    "wide panoramic establishing shot, atmospheric, no characters visible",
    "medium shot, child protagonist as focus, expressive face, dynamic pose",
    "dramatic low angle, intense atmosphere, dark contrasting shadows and light",
    "close-up portrait, magical animal or creature, expressive eyes, detailed fur/feathers",
    "wide joyful shot, warm golden sunlight flooding the scene, triumphant moment",
]

_STYLE_SUFFIX = {
    'magic':     'soft watercolor, enchanted atmosphere, warm golden tones',
    'magical':   'soft watercolor, enchanted atmosphere, warm golden tones',
    'tender':    'pastel watercolor, gentle light, cozy and dreamy',
    'adventure': 'vibrant gouache, dynamic composition, rich saturated colors',
    'nature':    'detailed watercolor, lush greens, natural dappled light',
    'space':     'digital art, cosmic blues and purples, glowing stardust',
    'epic':      'dramatic oil-paint style, rich deep colors, heroic lighting',
}

_BASE_QUALITY = (
    "children's book illustration, safe for children, no text, no watermark, "
    "high quality, detailed, professional illustration"
)


def _save_image_bytes(data: bytes, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.png'
    path = out_dir / filename
    path.write_bytes(data)
    return filename


def _build_prompt(scene_prompt: str, style: str, shot_idx: int) -> str:
    """Combine LLM scene prompt + shot-type modifier + style suffix + quality tags."""
    style_sfx = _STYLE_SUFFIX.get(style, 'watercolor style, warm colors')
    shot_mod = _SHOT_MODIFIERS[shot_idx] if shot_idx < len(_SHOT_MODIFIERS) else ""
    return f"{scene_prompt}, {shot_mod}, {style_sfx}, {_BASE_QUALITY}"


def generate_images(
    child_name: str,
    age: int,
    style: str,
    photo_base64: str | None,
    scene_prompts: list[str] | None = None,
    count: int = 5,
) -> tuple[list[str], str | None]:
    urls: list[str] = []
    photo_hash = None
    out_dir = Path(settings.images_dir)

    if photo_base64:
        raw_photo = base64.b64decode(photo_base64)
        photo_hash = hashlib.sha256(raw_photo).hexdigest()
        if settings.keep_uploaded_photo:
            _save_image_bytes(raw_photo, out_dir)

    for i in range(count):
        # Use LLM-provided scene prompt if available, otherwise fallback
        if scene_prompts and i < len(scene_prompts):
            base_prompt = scene_prompts[i]
        else:
            base_prompt = (
                f"children's book illustration, {age}-year-old child named {child_name}, "
                f"{style} fairy tale scene {i + 1}"
            )

        prompt = _build_prompt(base_prompt, style, i)

        try:
            filename = _generate_single(prompt, photo_base64 if i > 0 else None)
            urls.append(f'{settings.public_base_url}/files/images/{filename}')
        except Exception:
            pass  # skip failed images

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

    out_dir = Path(settings.images_dir)

    if photo_base64:
        # Use style-transfer endpoint for better character consistency with photo
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
        # Fallback to standard generation if style-transfer fails
        photo_base64 = None

    # Standard text-to-image generation
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


def _pollinations_generate(prompt: str) -> str:
    response = httpx.get(
        'https://image.pollinations.ai/prompt/' + quote(prompt),
        timeout=120,
    )
    response.raise_for_status()
    return _save_image_bytes(response.content, Path(settings.images_dir))
