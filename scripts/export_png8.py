"""Produce phone-friendly PNG-8 without cropping speech bubbles."""
import argparse
from pathlib import Path
from PIL import Image, ImageOps

def export(source: Path, target: Path, size=(800,1000)):
    image=Image.open(source).convert("RGB")
    # Pad instead of crop: preserve all text and characters.
    image=ImageOps.pad(image,size,method=Image.Resampling.LANCZOS,color=(12,20,34))
    pal=image.quantize(colors=256,method=Image.Quantize.MEDIANCUT,dither=Image.Dither.NONE)
    target.parent.mkdir(parents=True,exist_ok=True)
    pal.save(target,format="PNG",optimize=True,compress_level=9)
    print(f"{source.name} -> {target} ({target.stat().st_size//1024} KiB; {pal.size}, {pal.mode})")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("input",type=Path)
    p.add_argument("output",type=Path)
    args=p.parse_args()
    export(args.input,args.output)
