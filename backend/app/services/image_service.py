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
    "FINISHED SINGLE-SCENE children's book illustration — one complete cohesive scene, nothing else. "
    "Bright vibrant cheerful colours, warm sunlit happy atmosphere, "
    "wide establishing shot showing full scene, full body characters visible, "
    "high quality detailed professional illustration, safe for children, "
    "CHILD as protagonist — NO adult men, NO adult women as the main foreground character, "
    "correct child anatomy, no extra background crowd"
)

# Used for Stability AI and Pollinations (DALL-E 3 ignores negative_prompt parameter)
_NEGATIVE_PROMPT = (
    'color swatch, color chart, color palette diagram, palette grid, color picker, '
    'split image, multiple panels, collage layout, reference board, design sheet, '
    'character sheet, style sheet, storyboard, concept art, concept sheet, '
    'multiple scenes in one frame, split layout, comic panels, '
    'dark gloomy scene, dark atmosphere, horror, night scene, shadows, '
    'close-up portrait, headshot, face only, extreme close-up, '
    'dark skin on fair-skinned character, unexpected skin tone change, '
    'extra background people, crowd, strangers, unnamed characters, '
    'beard, mustache, stubble, facial hair on child, '
    'extra limbs, deformed hands, extra fingers, six fingers, bad anatomy, disfigured, '
    'watermark, signature, text label, username, blurry, low quality, ugly, '
    'unfinished render, test render, draft, sketch lines, rough drawing, '
    'UI elements, website screenshot, digital interface mockup, computer window'
)

# Inline "avoid" — embedded in every DALL-E 3 prompt (DALL-E 3 ignores negative_prompt param)
_DALLE_AVOID = (
    'RENDER AS ONE FINISHED ILLUSTRATION ONLY. '
    'Strictly forbidden: palette strips, color swatches, color chart, '
    'split image, multiple panels, collage, reference board, design sheet, '
    'character sheet, style sheet, storyboard, concept art, multiple scenes in one frame, '
    'sketch, unfinished illustration, draft, rough lines, '
    'comic panels, style mixing, visual artifacts, text in image, '
    'extra characters, inconsistent faces, distorted anatomy, '
    'adult men or women as main foreground character'
)


def _save_image_bytes(data: bytes, out_dir: Path) -> str:
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.png'
    path = out_dir / filename
    path.write_bytes(data)
    return filename


def _extract_character_appearance(cover_image_b64: str) -> str:
    """Use GPT-4o Vision to extract exact character appearance from the cover image.

    Returns a precise art-direction note used as hard visual reference for all
    subsequent illustrations — ensuring the child and animal look identical in every scene.
    """
    if not settings.openai_api_key:
        return ''
    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model='gpt-4o',
            messages=[{
                'role': 'user',
                'content': [
                    {
                        'type': 'image_url',
                        'image_url': {
                            'url': f'data:image/png;base64,{cover_image_b64}',
                            'detail': 'high',
                        },
                    },
                    {
                        'type': 'text',
                        'text': (
                            'You are a senior art director preparing character consistency sheets. '
                            'Study this illustration carefully and describe EXACTLY how the main child character '
                            'and animal companion look. Cover: hair color and style, skin tone, eye color, '
                            'exact clothing (every color, garment type, accessories, shoes), '
                            'animal species, fur/feather color, size, any distinctive markings or features. '
                            'Write as a strict reference note for an illustrator who must draw these SAME characters '
                            'in different scenes — every detail must match perfectly. '
                            'Be concrete and specific. Under 130 words. Child first, then animal.'
                        ),
                    },
                ],
            }],
            max_tokens=220,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return ''


def _build_prompt(scene_prompt: str, char_desc: str = '', image_style: str = 'watercolor',
                  visual_ref_desc: str = '', is_followup: bool = False) -> str:
    """4-block: A(Scene) + B(Character) + C(Style modifier) + D(Quality/Negative).

    Scene comes FIRST so DALL-E 3 treats the prompt as an illustration brief,
    not a design-reference document — prevents palette-strip artifacts.

    For images 1-5 (is_followup=True), visual_ref_desc (extracted from the cover via
    GPT-4o Vision) is injected as a hard character reference, overriding the generic
    text char_desc to enforce strict visual consistency across all illustrations.
    """
    style = _IMG_STYLE_SUFFIX.get(image_style, _IMG_STYLE_SUFFIX['watercolor'])
    parts = []

    # A — Scene (front-loaded to anchor DALL-E on the illustration, not style specs)
    parts.append(scene_prompt)

    # B — Character block
    # For follow-up images, visual_ref_desc (from cover Vision scan) takes priority —
    # it describes exactly how the characters ACTUALLY look in the generated cover,
    # which is far more reliable than the pre-generation text description.
    if is_followup and visual_ref_desc:
        parts.append(
            f"STRICT CHARACTER REFERENCE — the child and animal in this scene must look "
            f"IDENTICAL to the cover illustration, same in every detail: {visual_ref_desc}. "
            f"Do NOT change hair, clothing, colors, or animal appearance in any way."
        )
    elif char_desc:
        parts.append(f"Characters: {char_desc}")

    # C — Style modifier
    parts.append(f"Art style: {style}")

    # D — Consistency + quality + anti-artifact
    if is_followup:
        parts.append(
            "CRITICAL VISUAL CONSISTENCY — this illustration is part of a single storybook and MUST look "
            "as if drawn by THE SAME HAND in THE SAME SITTING as the cover illustration. "
            "IDENTICAL rendering technique: same line weight, same edge softness, same brushstroke texture, same level of detail. "
            "IDENTICAL colour palette: same specific hues, same saturation level, same warmth/coolness balance as the cover. "
            "IDENTICAL lighting: same direction, same intensity, same ambient mood as the cover. "
            "IDENTICAL character proportions and design — same child, same animal, absolutely zero design drift. "
            "A viewer placing this image next to the cover must NOT be able to tell they came from different prompts. "
            "Any style drift, technique mismatch, or character inconsistency = mission failure."
        )
    else:
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

    cover_ref_b64: str | None = None   # cover image bytes used as Stability style reference
    visual_char_desc: str = ''          # character description extracted from cover via Vision

    for i in range(count):
        scene = (scene_prompts[i] if scene_prompts and i < len(scene_prompts)
                 else f"{age}-year-old child named {child_name} in {style} fairy tale scene {i + 1}")

        # Cover (i=0): plain prompt; follow-ups: inject visual reference from cover scan
        prompt = _build_prompt(scene, char_desc, image_style,
                               visual_ref_desc=visual_char_desc if i > 0 else '',
                               is_followup=(i > 0))
        try:
            # Cover (0): use user photo as reference if provided
            # Images 1+: use cover image as hard style/character reference
            ref = photo_base64 if i == 0 else (cover_ref_b64 or photo_base64)
            filename = _generate_single(prompt, ref, cover_fidelity=(i > 0 and cover_ref_b64 is not None))
            urls[i] = f'{settings.public_base_url}/files/images/{filename}'

            # After cover is generated: save bytes + extract exact character appearance via Vision
            if i == 0 and cover_ref_b64 is None:
                try:
                    cover_path = out_dir / filename
                    if cover_path.exists():
                        cover_ref_b64 = base64.b64encode(cover_path.read_bytes()).decode()
                        visual_char_desc = _extract_character_appearance(cover_ref_b64)
                except Exception:
                    pass
        except Exception:
            pass  # slot stays None; index positions are preserved
    return urls, photo_hash


def _generate_single(prompt, photo_base64, cover_fidelity: bool = False):
    """Generate a single image.

    cover_fidelity=True means photo_base64 is the cover image (not a user photo),
    so we use a higher fidelity value to preserve character appearance more strictly.
    """
    provider = settings.image_provider
    fidelity = 0.72 if cover_fidelity else 0.6
    if provider == 'openai':
        try:
            return _openai_generate(prompt)
        except Exception:
            if settings.backup_image_provider == 'pollinations':
                return _pollinations_generate(prompt)
            raise
    if provider == 'stability':
        try:
            return _stability_generate(prompt, photo_base64, fidelity=fidelity)
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


def _stability_generate(prompt, photo_base64, fidelity: float = 0.6):
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
                'fidelity': fidelity,
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
