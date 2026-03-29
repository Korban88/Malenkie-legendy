import base64
import hashlib
import logging
import uuid
from pathlib import Path
from urllib.parse import quote

import httpx

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_IMG_STYLE_SUFFIX = {
    'watercolor': (
        'TRADITIONAL WATERCOLOR ON PAPER — physical medium, not digital imitation: '
        'visible cold-press watercolor paper grain and texture throughout the image, '
        'transparent pigment washes with natural wet-on-wet color bleeds and blooms at edges, '
        'white paper showing through in highlight and light areas — no solid white fill, '
        'natural pigment granulation and slight irregularity at brushstroke edges, '
        'colors built in luminous transparent overlapping layers like real watercolor, '
        'warm off-white paper tone visible beneath paint, '
        'soft organic edges, no sharp digital outlines, '
        'illustration quality of Beatrix Potter, Quentin Blake, or Jill Barklem, '
        'fully finished painting on textured watercolor paper, no sketch, no digital artifacts'
    ),
    'ghibli': (
        'STUDIO GHIBLI — exact visual style of Hayao Miyazaki films '
        '"My Neighbor Totoro" (1988) and "Spirited Away" (2001): '
        'hand-drawn 2D anime with soft rounded characters, large gentle expressive eyes, '
        'extraordinarily detailed lush painterly backgrounds — '
        'dense forest with dappled light, rich grass textures, warm golden sky, '
        'soft watercolor-quality sky with detailed cumulus clouds, '
        'warm earthy palette: rich forest greens, warm ochre, dusty rose, soft blue-grey, cream, '
        'gentle magical atmosphere with visible hand-painted quality, '
        'warm diffused natural lighting, no CGI, no 3D rendering, '
        'same production art quality as original Ghibli cel animation cells'
    ),
    'soviet': (
        'SOVIET SOYUZMULTFILM ANIMATION — exact visual style of USSR cartoons '
        '"Cheburashka" (1966), "Nu Pogodi!" (1969), "Kot Leopold" (1975), "Vinni-Pukh" (1969): '
        'hand-drawn 2D cel animation look, bold expressive black outlines of varying weight, '
        'flat color fills with minimal cel shading, '
        'warm muted USSR palette: ochre yellow, terracotta orange, sage green, dusty cornflower blue, '
        'cream white, brick red, warm brown — desaturated earthy tones, '
        'simple rounded geometric character shapes with large round eyes and simple noses, '
        'painted backgrounds in flat washes with soft horizon haze, '
        'retro 1960s-1980s Soviet aesthetic, no gradients, no glow effects, no modern glossy look, '
        'exactly the visual quality of original Soyuzmultfilm production cels'
    ),
    'pixar': (
        'PIXAR ANIMATION STUDIOS — exact quality of films "Toy Story 3", "Up", "Brave", "Coco": '
        'premium cinematic 3D CGI animation, highly polished subsurface skin rendering, '
        'soft volumetric global illumination, expressive large eyes with detailed iris and catch-lights, '
        'smooth rounded character designs with exaggerated proportions, '
        'richly detailed textured environments, warm cinematic color grading, '
        'professional studio lighting with soft fill and rim light, '
        'family-friendly magical mood, fully rendered no artifacts, '
        'same production quality as Pixar theatrical releases'
    ),
    'cartoon': (
        'CLASSIC AMERICAN CARTOON — exact style of Cartoon Network and early Disney Channel 2000s: '
        'bold clean black outlines of uniform weight, solid flat color fills, '
        'minimal cel shading — only simple cast shadows, '
        'high-contrast saturated color palette, simple expressive character shapes, '
        'clean vector-like linework, playful dynamic composition, '
        'no painterly textures, no gradients, no realistic rendering, '
        'fully finished flat illustration, no sketch, no artifacts'
    ),
    'storybook': (
        "CLASSIC CHILDREN'S BOOK ILLUSTRATION — quality of published picture books "
        'by Eric Carle, Maurice Sendak, or Chris Van Allsburg: '
        'rich detailed storytelling scene, traditional mixed-media feel, '
        'controlled ink linework with watercolor or gouache fill, '
        'warm natural earthy color palette with rich deep tones, '
        'slightly textured surface suggesting physical medium, '
        'high-quality publishing illustration with strong compositional balance, '
        'emotionally clear and narratively rich, fully finished artwork, '
        'no sketch, no concept art, no unfinished areas'
    ),
    'disney': (
        'CLASSIC DISNEY ANIMATION — exact style of "The Little Mermaid" (1989), '
        '"Beauty and the Beast" (1991), "Aladdin" (1992): '
        'hand-drawn 2D animation with elegant fluid character outlines, '
        'vibrant jewel-tone color palette — deep sapphire, emerald, warm gold, rose, '
        'sparkling warm magical light with visible glint effects, '
        'graceful expressive characters with large almond-shaped eyes, '
        'richly detailed painted backgrounds with romantic atmospheric depth, '
        'fully rendered scene, same quality as Disney theatrical animation production cels, '
        'no CGI, no 3D, no modern look'
    ),
}

_BASE_QUALITY = (
    "FINISHED SINGLE-SCENE children's book illustration — one complete cohesive scene, nothing else. "
    "Bright vibrant cheerful colours, warm sunlit happy atmosphere, "
    "wide establishing shot showing full scene, full body characters visible, "
    "high quality detailed professional illustration, safe for children, "
    "CHILD as the main protagonist hero — correct child anatomy. "
    "STRICT CHARACTER RULE: include ONLY the characters explicitly named in this prompt. "
    "Do NOT add random old men, old women, gnomes, elves, dwarves, strangers, background crowd, "
    "or any animals/creatures not mentioned in the prompt. "
    "If the prompt names only the child and one animal — draw ONLY those two."
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


def _extract_style_fingerprint(cover_image_b64: str) -> str:
    """Use GPT-4o Vision to extract a precise visual STYLE fingerprint from the cover.

    This is separate from character appearance — it captures HOW the illustration
    is rendered: technique, palette, line work, lighting, texture, proportions.

    The fingerprint is injected as a "STYLE CONSTITUTION" at the very start of every
    follow-up prompt, giving DALL-E 3 the most precise possible style specification
    reverse-engineered from the actual cover pixels — not from generic labels.
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
                            'You are a technical art director. Analyze this illustration and produce a precise '
                            'STYLE FINGERPRINT — a technical specification another AI must follow exactly to '
                            'draw in the SAME visual language. Be extremely specific:\n'
                            '1. RENDERING TECHNIQUE: exact medium and method '
                            '(e.g. "soft digital watercolor, semi-transparent pigment washes over clean pencil sketch base")\n'
                            '2. LINE WORK: weight, color, sharpness, consistency '
                            '(e.g. "thin clean dark-brown outlines approx 1-2px, slightly hand-drawn unevenness, expressive not mechanical")\n'
                            '3. COLOUR PALETTE: exactly 4-5 dominant colors with descriptive names '
                            '(e.g. "warm golden amber, deep forest teal, cream parchment white, muted dusty rose, rich chocolate brown")\n'
                            '4. LIGHTING: direction, quality, color temperature, shadow style '
                            '(e.g. "soft overhead warm golden light from upper-left, long gentle shadows, no harsh contrast, dreamy ambient glow")\n'
                            '5. TEXTURE: surface character '
                            '(e.g. "slight paper grain visible throughout, loose expressive brushstroke texture on large areas, not photorealistic")\n'
                            '6. CHARACTER PROPORTIONS: anatomy style '
                            '(e.g. "slightly stylized chibi-adjacent, large expressive eyes taking 1/4 of face, simplified rounded hands, approx 5-head-tall")\n'
                            '7. BACKGROUND TREATMENT: detail level and style '
                            '(e.g. "painterly atmospheric backgrounds, impressionistic soft-focus details, warm environmental haze")\n'
                            'Under 200 words total. Be technical and specific — not poetic.'
                        ),
                    },
                ],
            }],
            max_tokens=320,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return ''


def _build_prompt(scene_prompt: str, char_desc: str = '', image_style: str = 'watercolor',
                  visual_ref_desc: str = '', visual_style_fingerprint: str = '',
                  is_followup: bool = False) -> str:
    """Build image generation prompt with style constitution for visual consistency.

    Prompt block order for FOLLOW-UP images (is_followup=True):
      [0] STYLE CONSTITUTION — extracted from actual cover pixels via GPT-4o Vision.
          Front-loaded so DALL-E 3 treats it as the primary rendering constraint.
      [A] Scene description — what to draw
      [B] Character reference — exact appearance extracted from cover
      [C] Style modifier — generic style label (reinforcement)
      [D] Unity + quality + anti-artifact

    For COVER (is_followup=False):
      [A] Scene → [B] Characters → [C] Style → [D] Quality
    """
    style = _IMG_STYLE_SUFFIX.get(image_style, _IMG_STYLE_SUFFIX['watercolor'])
    parts = []

    # ── Block 0: STYLE CONSTITUTION (follow-up only, always FIRST) ──────────
    # Reverse-engineered from the actual cover pixels — far more reliable than
    # generic style labels. Placed first so DALL-E weights it highest.
    if is_followup and visual_style_fingerprint:
        parts.append(
            f"STYLE CONSTITUTION — MANDATORY visual specification, non-negotiable: "
            f"{visual_style_fingerprint} "
            f"Every aspect of rendering in this image MUST match this specification exactly. "
            f"This is illustration N in a single storybook series — identical visual language required."
        )

    # ── Block A: Scene ───────────────────────────────────────────────────────
    parts.append(scene_prompt)

    # ── Block B: Character reference ────────────────────────────────────────
    if is_followup and visual_ref_desc:
        parts.append(
            f"CHARACTER REFERENCE — copied exactly from the cover illustration: {visual_ref_desc}. "
            f"Do NOT change any detail. Same hair, same clothing, same colors, same animal appearance in every scene."
        )
    elif char_desc:
        parts.append(f"Characters: {char_desc}")

    # ── Block C: Style modifier (reinforcement) ──────────────────────────────
    if is_followup:
        parts.append(
            f"Art style reinforcement (same as cover): {style}"
        )
    else:
        parts.append(f"Art style: {style}")

    # ── Block D: Unity + quality + anti-artifact ─────────────────────────────
    if is_followup:
        parts.append(
            "SINGLE UNIFIED STORYBOOK: this image must be visually indistinguishable "
            "from the same artist who drew the cover — same hand, same session, same tools. "
            "A viewer placing this next to the cover must see one coherent visual universe."
        )
    else:
        parts.append(
            "Same art style, colour tones, and character proportions as all other "
            "illustrations in this storybook — one coherent visual universe"
        )
    parts.append(_BASE_QUALITY)
    parts.append(_DALLE_AVOID)

    return ". ".join(parts)[:3900]


def generate_images(child_name, age, style, photo_base64, char_desc='',
                    scene_prompts=None, count=4, image_style='watercolor'):
    urls: list[str | None] = [None] * count   # fixed-size: indices preserved even on failure
    photo_hash = None
    out_dir = Path(settings.images_dir)
    if photo_base64:
        raw_photo = base64.b64decode(photo_base64)
        photo_hash = hashlib.sha256(raw_photo).hexdigest()
        if settings.keep_uploaded_photo:
            _save_image_bytes(raw_photo, out_dir)

    # Together AI provider: use public cover URL as reference image for follow-ups.
    # All other providers: use base64 pixel reference + GPT-4o Vision extraction.
    cover_public_url: str | None = None    # public URL of cover — for Together reference images
    cover_ref_b64: str | None = None       # cover bytes (base64) — for Stability/OpenAI img2img
    visual_char_desc: str = ''
    visual_style_fingerprint: str = ''

    for i in range(count):
        scene = (scene_prompts[i] if scene_prompts and i < len(scene_prompts)
                 else f"{age}-year-old child named {child_name} in {style} fairy tale scene {i + 1}")

        prompt = _build_prompt(
            scene, char_desc, image_style,
            visual_ref_desc=visual_char_desc if i > 0 else '',
            visual_style_fingerprint=visual_style_fingerprint if i > 0 else '',
            is_followup=(i > 0),
        )
        try:
            ref = photo_base64 if i == 0 else (cover_ref_b64 or photo_base64)
            filename = _generate_single(
                prompt, ref,
                cover_fidelity=(i > 0 and cover_ref_b64 is not None),
                cover_url=cover_public_url if i > 0 else None,
            )
            urls[i] = f'{settings.public_base_url}/files/images/{filename}'

            if i == 0:
                cover_public_url = urls[0]
                # For non-Together providers: extract style+character via GPT-4o Vision
                if settings.image_provider != 'together':
                    try:
                        cover_path = out_dir / filename
                        if cover_path.exists():
                            cover_ref_b64 = base64.b64encode(cover_path.read_bytes()).decode()
                            visual_char_desc = _extract_character_appearance(cover_ref_b64)
                            visual_style_fingerprint = _extract_style_fingerprint(cover_ref_b64)
                    except Exception:
                        pass
        except Exception as exc:
            logger.warning('Image generation failed for slot %d: %s', i, exc)
    return urls, photo_hash


def _together_generate(prompt: str, reference_url: str | None = None) -> str:
    """Generate image via Together AI FLUX.2-pro.

    Cover (reference_url=None): FLUX.1.1-pro, no reference — best quality for first image.
    Follow-ups (reference_url set): FLUX.2-pro with image_urls=[cover_url] — model literally
    looks at the cover when drawing the next scene, guaranteeing identical character and style.
    No GPT-4o Vision extraction needed: pixel-level reference replaces text description.
    """
    if not settings.together_api_key:
        raise RuntimeError('TOGETHER_API_KEY is not configured')

    if reference_url:
        model = 'black-forest-labs/FLUX.2-pro'
        payload: dict = {
            'model': model,
            'prompt': prompt[:3000],
            'width': 1024,
            'height': 1024,
            'n': 1,
            'image_urls': [reference_url],
        }
    else:
        model = 'black-forest-labs/FLUX.1.1-pro'
        payload = {
            'model': model,
            'prompt': prompt[:3000],
            'width': 1024,
            'height': 1024,
            'n': 1,
        }

    logger.debug('Together AI: model=%s reference=%s', model, bool(reference_url))
    response = httpx.post(
        'https://api.together.xyz/v1/images/generations',
        headers={'Authorization': f'Bearer {settings.together_api_key}'},
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    img_url = response.json()['data'][0]['url']

    img_response = httpx.get(img_url, timeout=60)
    img_response.raise_for_status()
    return _save_image_bytes(img_response.content, Path(settings.images_dir))


def _generate_single(prompt: str, photo_base64: str | None, cover_fidelity: bool = False,
                     cover_url: str | None = None) -> str:
    """Generate a single image.

    Hybrid strategy for visual consistency:

    When cover_fidelity=True (generating follow-up images with cover as reference):
      → PREFER Stability AI /control/style endpoint if stability_api_key is configured.
        This is true image-to-image style transfer — the cover image is used as a pixel-level
        style reference, guaranteeing the same rendering regardless of the text prompt.
        Works even when the main image_provider is 'openai'.
      → If Stability is not available, fall back to main provider with style constitution
        text already baked into the prompt.

    When cover_fidelity=False (generating the cover itself):
      → Use the configured image_provider normally.
    """
    provider = settings.image_provider

    # ── Together AI: URL-based reference images — strictest character consistency ──
    # Cover URL is passed from generate_images after first image is saved.
    # FLUX.2-pro receives the actual cover pixels and reuses character + style.
    if provider == 'together':
        try:
            return _together_generate(prompt, reference_url=cover_url)
        except Exception as exc:
            logger.warning('Together image generation failed: %s', exc)
            if settings.backup_image_provider == 'openai':
                return _openai_generate(prompt)
            if settings.backup_image_provider == 'pollinations':
                return _pollinations_generate(prompt)
            raise

    # Higher fidelity for cover follow-ups: tighter style adherence
    fidelity = 0.82 if cover_fidelity else 0.60

    # ── Hybrid: img2img for follow-ups — guarantees visual style consistency ──
    # Priority order for cover follow-ups:
    #   1. gpt-image-1 images.edit  — true img2img, always inherits cover style
    #   2. Stability /control/style — pixel-level style transfer
    #   3. Configured provider       — text-only (lowest consistency)
    if cover_fidelity and photo_base64:
        if settings.openai_api_key:
            try:
                return _openai_edit_generate(prompt, photo_base64)
            except Exception:
                pass  # fall through to Stability or text-based provider
        if settings.stability_api_key:
            try:
                return _stability_generate(prompt, photo_base64, fidelity=fidelity)
            except Exception:
                pass  # fall through to configured provider below

    # ── Primary provider ─────────────────────────────────────────────────────
    if provider == 'openai':
        try:
            return _openai_generate(prompt)
        except Exception as exc:
            logger.warning('OpenAI image generation failed: %s', exc)
            if settings.backup_image_provider == 'pollinations':
                return _pollinations_generate(prompt)
            if settings.backup_image_provider == 'stability':
                return _stability_generate(prompt, photo_base64, fidelity=fidelity)
            raise
    if provider == 'stability':
        try:
            return _stability_generate(prompt, photo_base64, fidelity=fidelity)
        except Exception as exc:
            logger.warning('Stability image generation failed: %s', exc)
            if settings.backup_image_provider == 'pollinations':
                return _pollinations_generate(prompt)
            if settings.backup_image_provider == 'openai':
                return _openai_generate(prompt)
            raise
    if provider == 'pollinations':
        return _pollinations_generate(prompt)
    raise ValueError(f'Unsupported image provider: {provider}')


def _openai_generate(prompt: str) -> str:
    if not settings.openai_api_key:
        raise RuntimeError('OPENAI_API_KEY is not configured')
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)
    response = client.images.generate(
        model='dall-e-3', prompt=prompt[:4000], size='1024x1024',
        quality='standard', style='natural', n=1
    )
    image_url = response.data[0].url
    img_response = httpx.get(image_url, timeout=60)
    img_response.raise_for_status()
    return _save_image_bytes(img_response.content, Path(settings.images_dir))


def _openai_edit_generate(prompt: str, reference_image_b64: str) -> str:
    """True img2img via gpt-image-1 images.edit.

    Passes the cover illustration as a pixel-level visual reference so the model
    generates a completely new scene while inheriting the same art style, colour
    palette, character proportions, linework, and lighting from the cover.
    This is the only reliable way to guarantee visual consistency between images
    when Stability AI style-transfer is not available.
    """
    if not settings.openai_api_key:
        raise RuntimeError('OPENAI_API_KEY is not configured')
    import io
    from openai import OpenAI
    client = OpenAI(api_key=settings.openai_api_key)

    image_bytes = base64.b64decode(reference_image_b64)
    image_file = io.BytesIO(image_bytes)
    image_file.name = 'cover.png'

    response = client.images.edit(
        model='gpt-image-1',
        image=image_file,
        prompt=prompt[:4000],
        size='1024x1024',
    )
    # gpt-image-1 always returns base64
    img_b64 = response.data[0].b64_json
    img_bytes = base64.b64decode(img_b64)
    return _save_image_bytes(img_bytes, Path(settings.images_dir))


def _stability_generate(prompt: str, photo_base64: str | None, fidelity: float = 0.6) -> str:
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
                'aspect_ratio': '1:1',
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
            'aspect_ratio': '1:1',
        },
        timeout=120,
    )
    response.raise_for_status()
    return _save_image_bytes(response.content, out_dir)


def _pollinations_generate(prompt: str) -> str:
    # Pollinations uses GET requests — keep URL short to avoid HTTP 414 / server rejections.
    # The full prompt can be 3900+ chars; URL-encoding it plus negative_prompt creates
    # a 10,000+ char URL that most servers/proxies reject. Use first 400 chars of prompt
    # (core scene description) and omit the negative prompt from the URL.
    short_prompt = prompt[:400]
    encoded = quote(short_prompt)
    url = f'https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true&model=flux'
    logger.debug('Pollinations URL length: %d', len(url))
    response = httpx.get(url, timeout=120)
    response.raise_for_status()
    return _save_image_bytes(response.content, Path(settings.images_dir))
