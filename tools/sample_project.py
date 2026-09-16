"""Small, disposable fixtures; no checked-in illustrations or user images required."""
from pathlib import Path


def create_sample_project(root: Path):
    from PIL import Image, ImageDraw
    root.mkdir(parents=True, exist_ok=True)
    for name, color in [('alice',(80,100,160)),('grace',(130,95,150)),('iris',(70,130,120))]:
        image=Image.new('RGB',(640,360),color)
        ImageDraw.Draw(image).text((24,24),'LIRATING TEST / '+name,fill='white')
        image.save(root/(name+'.png'))
