"""Place the reusable vector paper beneath the interior of an illustrated PDF."""
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject

PAPER_STOCK = Path(__file__).resolve().parents[1] / "assets" / "matte_stock.pdf"
_PAPER_NAME = NameObject("/LegendKidsPaper")


def _add_interior_paper(writer: PdfWriter) -> None:
    with PAPER_STOCK.open("rb") as source:
        stock = PdfReader(source).pages[0]
        # The stock has one compressed vector content stream and a shading mesh.
        # Clone both once; interior pages refer to the same PDF Form XObject.
        paper = stock.raw_get("/Contents").clone(writer)
        form = paper.get_object()
        form[NameObject("/Type")] = NameObject("/XObject")
        form[NameObject("/Subtype")] = NameObject("/Form")
        form[NameObject("/BBox")] = stock.mediabox
        form[NameObject("/Resources")] = stock.raw_get("/Resources").clone(writer)

        sw, sh = float(stock.mediabox.width), float(stock.mediabox.height)
        for page in list(writer.pages)[1:]:
            # FPDF can share page resource dictionaries. Isolate this page's
            # dictionary before adding the form, so the cover stays untouched.
            resources = DictionaryObject(page["/Resources"])
            objects = DictionaryObject(resources.get("/XObject", DictionaryObject()).get_object())
            objects[_PAPER_NAME] = paper
            resources[NameObject("/XObject")] = objects
            page[NameObject("/Resources")] = resources

            box = page.mediabox
            width, height = float(box.width), float(box.height)
            scale = max(width / sw, height / sh)
            x = float(box.left) + (width - scale * sw) / 2 - scale * float(stock.mediabox.left)
            y = float(box.bottom) + (height - scale * sh) / 2 - scale * float(stock.mediabox.bottom)
            prefix = DecodedStreamObject()
            transform = f"{scale:.9f} 0 0 {scale:.9f} {x:.6f} {y:.6f}"
            prefix.set_data(f"q {transform} cm {_PAPER_NAME} Do Q\n".encode("ascii"))
            contents = page.raw_get("/Contents")
            streams = contents.get_object()
            original = list(streams) if isinstance(streams, ArrayObject) else [contents]
            page[NameObject("/Contents")] = ArrayObject([writer._add_object(prefix), *original])


def write_with_paper(rendered: bytes | bytearray, destination: Path) -> None:
    writer = PdfWriter(clone_from=BytesIO(rendered))
    # A failed write must never expose a partial file through the media URL.
    with TemporaryDirectory(dir=destination.parent) as temporary:
        staged = Path(temporary) / destination.name
        if len(writer.pages) > 1:
            _add_interior_paper(writer)
            with staged.open("wb") as output:
                writer.write(output)
        else:
            staged.write_bytes(rendered)
        staged.replace(destination)
