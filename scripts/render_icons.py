"""Render iPhone Home Screen and QTS App Center icons from assets/qcc-icon.svg."""
import argparse
from io import BytesIO
from pathlib import Path
import cairosvg
from PIL import Image, ImageOps

SOURCE = Path(__file__).resolve().parent.parent / "assets" / "qcc-icon.svg"

def render(output):
    output.mkdir(parents=True, exist_ok=True)
    source = SOURCE.read_bytes()
    for name, size, disabled in (
        ("apple-touch-icon.png", 180, False),
        ("QnapControlCenter.png", 64, False),
        ("QnapControlCenter_80.png", 80, False),
        ("QnapControlCenter_gray.png", 64, True),
    ):
        data = cairosvg.svg2png(bytestring=source, output_width=size, output_height=size)
        with Image.open(BytesIO(data)) as im:
            icon = im.convert("RGB")
            if disabled:
                icon = ImageOps.grayscale(icon).convert("RGB")
            icon.save(output / name, format="PNG", optimize=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    render(parser.parse_args().output)
