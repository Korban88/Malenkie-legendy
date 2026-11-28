"""Technical (not artistic) release gate for illustrated books.

Never label an incomplete illustrated book ready. This gate does not replace
editorial review, visual approval, durable payment recovery or authorization.
"""
import hashlib
from io import BytesIO
from urllib.parse import urlsplit
from PIL import Image
from pypdf import PdfReader
from .config import get_settings
from .private_media import locate_media

EXPECTED_IMAGES = 5


def require_illustration_prompts(prompts: object) -> None:
    if not isinstance(prompts, list) or len(prompts) != EXPECTED_IMAGES:
        raise ValueError("Five illustration prompts are required: one cover and four chapter scenes")
    if any(not isinstance(scene, str) or not scene.strip() for scene in prompts):
        raise ValueError("All illustration prompts must be nonempty text")


def _filename(locator: str, kind: str) -> str:
    if not isinstance(locator, str):
        raise ValueError("Missing media locator")
    prefix = f"/files/{kind}/"
    path = urlsplit(locator).path
    if not path.startswith(prefix) or "/" in path[len(prefix):]:
        raise ValueError("Invalid media locator")
    return path[len(prefix):]


def require_complete_images(locators: list[str | None]) -> None:
    if not isinstance(locators, list) or len(locators) != EXPECTED_IMAGES:
        raise ValueError("Five illustration slots are required")
    filenames = [_filename(url, "images") for url in locators]
    if len(set(filenames)) != EXPECTED_IMAGES:
        raise ValueError("Illustration slots must refer to distinct files")
    fingerprints = set()
    for filename in filenames:
        path = locate_media(get_settings().images_dir, filename, kind="images")
        with Image.open(path) as image:
            if image.width < 1 or image.height < 1:
                raise ValueError("Empty illustration")
            image.verify()
        # verify() alone does not decode JPEG pixels. Reopen after verify and
        # check the actual decoded content, not just distinct filenames.
        with Image.open(path) as image:
            image.load()
            with image.convert("RGBA") as pixels:
                fingerprint = (pixels.size, hashlib.sha256(pixels.tobytes()).digest())
        if fingerprint in fingerprints:
            raise ValueError("Illustration slots must contain distinct decoded images")
        fingerprints.add(fingerprint)


def require_complete_pdf(locator: str) -> str:
    path = locate_media(get_settings().stories_dir, _filename(locator, "stories"), kind="stories")
    # The bot delivers at most 30 MiB. Validate and fingerprint the same bytes,
    # including when a stored file is replaced during a later download.
    with path.open("rb") as source:
        content = source.read(30 * 1024 * 1024 + 1)
    if len(content) > 30 * 1024 * 1024:
        raise ValueError("PDF exceeds delivery limit")
    reader = PdfReader(BytesIO(content))
    if not reader.pages:
        raise ValueError("Empty PDF")
    if sum(len(page.images) for page in reader.pages) < EXPECTED_IMAGES:
        raise ValueError("Five embedded illustrations are required")
    if not any((page.extract_text() or "").strip() for page in reader.pages):
        raise ValueError("Missing readable PDF text")
    return hashlib.sha256(content).hexdigest()
