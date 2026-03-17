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
        'animated film scene in the style of Studio Ghibli "My Neighbor Totoro" (1988) by Hayao Miyazaki. '
        'TECHNIQUE: hand-painted cel animation, gouache on paper, visible soft brushwork texture. '
        'LINES: clean medium-weight ink outlines, slightly organic and hand-drawn, never mechanical. '
        'COLOURS: warm golden yellow, soft meadow green, sky blue, cream white, peach skin — '
        'ALL colours minimum 70% brightness, fully saturated and warm, absolutely NO dark or muddy tones. '
        'LIGHTING: warm golden sunlight from upper-right, soft atmospheric haze in distance, '
        'bright and airy throughout the whole image. '
        'CHARACTERS: large round head 1/4 of body, very large circular eyes with white highlight dot, '
        'simple tiny nose, small rounded mouth, soft rounded limbs, no sharp angles anywhere. '
        'BACKGROUND: lush detailed hand-painted nature — bright green grass, leafy trees, fluffy clouds, '
        'wooden houses, flowers. '
        'MOOD: peaceful wonder, summer warmth, every corner of the image bright and welcoming'
    ),
    'disney': (
        'animated fairy-tale scene in the style of classic Disney "Sleeping Beauty" (1959) by Eyvind Earle. '
        'TECHNIQUE: hand-inked flat cel animation with opaque gouache fills, vintage 1950s production. '
        'LINES: bold elegant ink outlines, slightly angular and decorative, uniform even weight. '
        'COLOURS: rich jewel tones — royal cobalt blue, ruby crimson, emerald green, vivid violet, '
        'pure gold — maximum saturation, brilliant and luminous, NO muted, dusty or dark tones. '
        'LIGHTING: warm sparkling magical light, dramatic contrast with glowing bright highlights, '
        'golden sparkle effects and warm magical glow throughout. '
        'CHARACTERS: elegant proportions, long graceful limbs, large expressive eyes with thick lashes, '
        'refined features, fluid movement. '
        'BACKGROUND: ornate stylized architecture, decorative flat patterns, rich tapestry-like detail. '
        'MOOD: fairy-tale grandeur, magical elegance, vivid and spectacular'
    ),
    'pixar': (
        'premium cinematic 3D CGI animated feature film, top-tier modern animation studio quality. '
        'TECHNIQUE: photorealistic subsurface scattering on skin surfaces, ray-traced global illumination, '
        'smooth polished 3D geometry with fine surface micro-detail. '
        'LINES: NO ink outlines — purely smooth curved 3D forms and surfaces. '
        'COLOURS: rich warm vibrant saturation — golden amber, vivid orange-red, sky blue, leaf green — '
        'warm colour grading, bright luminous highlights, minimum 65% brightness throughout. '
        'LIGHTING: soft volumetric global illumination, warm key light from upper-left, '
        'gentle fill light, soft rim light — NO harsh black shadows. '
        'CHARACTERS: large rounded head 1/3 of body height, oversized expressive eyes with deep shine, '
        'smooth polished skin with warm subsurface glow, exaggerated friendly proportions. '
        'BACKGROUND: richly detailed 3D environment — realistic wood, fabric, stone, vegetation textures. '
        'MOOD: cinematic warmth, emotional depth, wonder and joyful adventure'
    ),
    'watercolor': (
        'bright cheerful children\'s book watercolour illustration '
        'in the style of Quentin Blake\'s illustrations for Roald Dahl books. '
        'TECHNIQUE: traditional watercolour washes over loose pen-and-ink drawing on white paper. '
        'LINES: energetic scratchy ink outlines — irregular, expressive, slightly wobbly — '
        'hand-drawn and imperfect, NOT digital or clean. '
        'COLOURS: bright translucent washes — warm lemon yellow, grass green, cornflower blue, '
        'coral red, peach — white paper showing through as bright highlights everywhere, '
        'light and airy, maximum 50% opacity washes. '
        'LIGHTING: natural bright daylight, open and airy, soft warm grey shadows as watercolour wash. '
        'CHARACTERS: loose energetic shapes, exaggerated movement, large round eyes, '
        'simple curved lines, expressive wobbly outlines, spontaneous feel. '
        'BACKGROUND: sketchy atmospheric watercolour washes, few lines suggesting environment, '
        'lots of white space, not overly detailed. '
        'MOOD: playful, energetic, spontaneous, joyful and light'
    ),
    'cartoon': (
        'bright bold children\'s cartoon illustration '
        'in the style of classic Cartoon Network shows and Hanna-Barbera cartoons. '
        'TECHNIQUE: flat digital vector illustration, zero texture, zero grain, perfectly clean. '
        'LINES: thick uniform bold black outlines, consistent 4-5px weight, perfectly smooth and clean. '
        'COLOURS: flat saturated PRIMARY colours — pure red, royal blue, grass green, sunshine yellow, '
        'orange — COMPLETELY FLAT fills with NO gradients, NO shadows, NO halftones, NO shading. '
        'LIGHTING: NONE — completely flat uniform colour fills throughout the entire image. '
        'CHARACTERS: simple bold geometric shapes — circle heads, oval bodies, '
        'very large round eyes taking up 1/3 of face area, simple curved mouths, stubby rounded limbs. '
        'BACKGROUND: simple flat solid colour background, minimal geometric shapes, '
        'bright solid sky, simple flat ground, 2-3 simple background elements only. '
        'MOOD: bold, graphic, maximally energetic and fun, visually simple'
    ),
    'storybook': (
        'classic illustrated children\'s storybook scene '
        'in the style of E.H. Shepard\'s Winnie-the-Pooh illustrations with pen-and-ink and watercolour. '
        'TECHNIQUE: detailed fine pen-and-ink cross-hatching with warm watercolour washes on cream paper. '
        'LINES: fine warm brown ink lines with hatching and cross-hatching for shading, '
        'delicate, precise, traditional book illustration style. '
        'COLOURS: warm amber, golden ochre, sage green, dusty rose, soft sky blue, cream white — '
        'ALL warm-toned, aged-paper feel, soft and gentle, maximum 55% saturation. '
        'LIGHTING: cosy warm golden afternoon light, soft diffused, no harsh shadows, '
        'gentle and comforting throughout. '
        'CHARACTERS: friendly rounded forms with traditional proportions, '
        'expressive gentle faces, soft fabric textures on clothing, lovable and safe. '
        'BACKGROUND: detailed pen-hatched environment — trees, fields, cosy interiors — '
        'with warm watercolour wash colour fills. '
        'MOOD: cosy, nostalgic, safe, warm, timeless and loved'
    ),
    'soviet': (
        'Soviet children\'s animated cartoon scene '
        'in the exact style of Soyuzmultfilm "Cheburashka" (1966) by Leonid Shvartsman. '
        'TECHNIQUE: flat hand-painted cel animation, 1960s USSR Soyuzmultfilm production quality. '
        'LINES: thick clean black ink outlines, perfectly uniform weight, completely flat and graphic. '
        'COLOURS: strict limited flat palette — sunshine yellow, brick red, sky blue, grass green, '
        'warm orange, cream white — ONLY these colours, NO gradients whatsoever, '
        'NO shadows, completely flat solid fills. '
        'LIGHTING: completely flat and even throughout — NO shadows, NO highlights, NO shading, '
        'NO lighting effects of any kind. '
        'CHARACTERS: very round compact bodies, extremely large round eyes with simple black pupils, '
        'small simple nose, wide simple mouth, large rounded ears, simple tubular limbs. '
        'BACKGROUND: simple flat geometric shapes — flat coloured sky, simple flat ground, '
        'basic stylized flat trees and buildings, 3-4 elements only. '
        'MOOD: warm Soviet nostalgia, simple and friendly, bright cheerful and innocent'
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
    'Do NOT include: colour swatches, palette grids, comic panels, split-screen layout, '
    'collage, storyboard grid, dark or gloomy scenes, night scene, extra unnamed background people, '
    'extreme close-up face portraits, floating text labels, captions, UI windows, '
    'duplicate panels, watermarks, random props not in the scene, '
    'adult men or adult women as the main foreground character, bearded men, muscular adults, '
    'aged or wrinkled faces in the foreground'
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
