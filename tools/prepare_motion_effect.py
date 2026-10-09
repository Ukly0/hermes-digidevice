"""Build a persistent motion-effect clip from an explicitly selected source mark."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from PIL import Image,ImageDraw,ImageFilter


def prepare(recipe_path,assets):
    assets=Path(assets).resolve()
    recipe=json.loads(Path(recipe_path).read_text())
    if not re.fullmatch(r"[a-z][a-z0-9_]*",recipe.get("profile","")):raise ValueError("invalid effect profile")
    names=[item["name"] for item in recipe["frames"]]
    if len(set(names))!=len(names) or any(not re.fullmatch(r"[A-Za-z0-9_-]+",name) for name in names):raise ValueError("invalid effect frame names")
    if (not isinstance(recipe.get("canvas"),list) or len(recipe["canvas"])!=2 or
        any(type(v) is not int or not 1<=v<=466 for v in recipe["canvas"])):raise ValueError("invalid effect canvas")
    if not recipe["timeline"]:raise ValueError("empty effect timeline")
    for item in recipe["timeline"]:
        if item["frame"] not in names or type(item["duration_ms"]) is not int or not 1<=item["duration_ms"]<=65535:
            raise ValueError("invalid effect timeline")
    source=(assets/recipe["source"]).resolve()
    output=(assets/recipe["output"]).resolve()
    if not source.is_relative_to(assets) or not output.is_relative_to(assets):raise ValueError("effect path escapes assets")
    if output.exists():raise ValueError("effect revision already exists")
    with Image.open(source) as im:original=im.convert("RGBA")
    x0,y0,x1,y1=recipe["source_rect"]
    if not 0<=x0<x1<=original.width or not 0<=y0<y1<=original.height:raise ValueError("invalid source mark region")
    crop=original.crop(tuple(recipe["source_rect"]))
    mask=Image.new("L",crop.size)
    pixels=crop.tobytes()
    mask.frombytes(bytes(255 if pixels[i+3]>=128 and min(pixels[i:i+3])>=recipe["white_threshold"] else 0
                         for i in range(0,len(pixels),4)))
    if not mask.getbbox():raise ValueError("source region contains no white effect")
    growth=recipe["stroke_growth"]
    if type(growth) is not int or growth not in (1,3,5,7):raise ValueError("stroke_growth must be 1, 3, 5 or 7")
    if growth>1:
        mask=mask.filter(ImageFilter.MaxFilter(growth))
    frames={}
    for item in recipe["frames"]:
        image=Image.new("RGBA",tuple(recipe["canvas"]))
        for stroke in item["strokes"]:
            scaled=mask.resize(tuple(stroke["size"]),Image.Resampling.NEAREST)
            sprite=Image.new("RGBA",scaled.size,(*stroke["color"],255));sprite.putalpha(scaled)
            x,y=stroke["at"]
            if x<0 or y<0 or x+sprite.width>image.width or y+sprite.height>image.height:raise ValueError("effect stroke clipped")
            image.alpha_composite(sprite,(x,y))
        for arc in item.get("arcs",[]):
            cx,cy=arc["center"];radius=arc["radius"]
            ImageDraw.Draw(image).arc((cx-radius,cy-radius,cx+radius,cy+radius),
                arc["start"],arc["end"],fill=(*arc["color"],255),width=arc["width"])
        frames[item["name"]]=image
    output.mkdir(parents=True)
    originals=output/"source.png";originals.write_bytes(source.read_bytes())
    mask.save(output/"source-mark.png")
    for name,image in frames.items():image.save(output/(name+".png"))
    profile={"schema_version":1,"profile":recipe["profile"],"canvas":recipe["canvas"],
             "frames":{name:(output/(name+".png")).relative_to(assets).as_posix() for name in frames},
             "clips":{"flow":{"loop":True,"steps":recipe["timeline"]}},
             "authoring_recipe":recipe,"source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),
             "scope":"stylised motion mark, not physical wing anatomy"}
    (output/"profile.json").write_text(json.dumps(profile,indent=2)+"\n")
    print(output/"profile.json")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe",type=Path,required=True);parser.add_argument("--assets",type=Path,required=True)
    args=parser.parse_args();prepare(args.recipe,args.assets)
