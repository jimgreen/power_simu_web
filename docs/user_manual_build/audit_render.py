from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent
RENDER_DIR = ROOT / "rendered_formula_final6_word"
CONTACT_DIR = ROOT / "contact_sheets_formula_final6_word"
PDF_PATH = ROOT / "word_export_final6_2" / "manual_formula_final6.pdf"


def page_number(path: Path) -> int:
    return int(path.stem.split("-")[-1])


def nonwhite_bbox(image: Image.Image, threshold: int = 247):
    rgb = image.convert("RGB")
    bg = Image.new("RGB", rgb.size, (255, 255, 255))
    diff = ImageChops.difference(rgb, bg).convert("L")
    mask = diff.point(lambda value: 255 if value > 255 - threshold else 0)
    return mask.getbbox()


def main() -> None:
    pages = sorted(RENDER_DIR.glob("page-*.png"), key=page_number)
    CONTACT_DIR.mkdir(parents=True, exist_ok=True)

    print("PAGE_COUNT", len(pages))
    for path in pages:
        with Image.open(path) as image:
            bbox = nonwhite_bbox(image)
            if bbox is None:
                print(path.name, "BLANK")
                continue
            left, top, right, bottom = bbox
            content_ratio = (right - left) * (bottom - top) / (image.width * image.height)
            bottom_gap = (image.height - bottom) / image.height
            print(
                path.name,
                "size",
                image.size,
                "bbox",
                bbox,
                "content_box_ratio",
                f"{content_ratio:.3f}",
                "bottom_gap",
                f"{bottom_gap:.3f}",
            )

    reader = PdfReader(PDF_PATH)
    print("PDF_PAGES", len(reader.pages))
    for index, page in enumerate(reader.pages, start=1):
        text = " ".join((page.extract_text() or "").split())
        print(f"TEXT {index:02d}", text[:180])

    sheet_width = 2600
    tile_width = 1240
    tile_height = 1605
    gap = 32
    margin = 44
    label_height = 44
    for start in range(0, len(pages), 4):
        batch = pages[start : start + 4]
        sheet = Image.new("RGB", (sheet_width, 2 * (tile_height + label_height) + 3 * gap), "#D9E2EA")
        draw = ImageDraw.Draw(sheet)
        for offset, path in enumerate(batch):
            with Image.open(path) as source:
                source = source.convert("RGB")
                source.thumbnail((tile_width, tile_height), Image.Resampling.LANCZOS)
                col = offset % 2
                row = offset // 2
                x = margin + col * (tile_width + gap)
                y = gap + row * (tile_height + label_height + gap)
                canvas = Image.new("RGB", (tile_width, tile_height), "white")
                px = (tile_width - source.width) // 2
                py = (tile_height - source.height) // 2
                canvas.paste(source, (px, py))
                sheet.paste(canvas, (x, y))
                draw.text((x + 8, y + tile_height + 8), f"Page {page_number(path)}", fill="#15324A")
        end = page_number(batch[-1])
        output = CONTACT_DIR / f"pages_{page_number(batch[0]):02d}_{end:02d}.png"
        sheet.save(output, optimize=True)
        print("CONTACT", output.name, output.stat().st_size)


if __name__ == "__main__":
    main()
