"""Persist selected cached artwork using explicit sources and replacement masks."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from PIL import Image
from hermes_gadget.portraits import compose_feature


def archive(recipe_path, assets):
    recipe_path, assets = Path(recipe_path), Path(assets).resolve()
    repository = Path(__file__).resolve().parents[1]
    recipe = json.loads(recipe_path.read_text())
    if not re.fullmatch(r"[a-z][a-z0-9_]*",recipe.get("profile","")) or not re.fullmatch(r"[A-Za-z0-9_-]+",recipe.get("revision","")):
        raise ValueError("invalid snapshot identifier")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+",name) for name in recipe["frames"]):
        raise ValueError("invalid frame name")
    source_root = (assets/recipe["source_root"]).resolve() if "source_root" in recipe else repository
    if "source_root" in recipe and not source_root.is_relative_to(assets):
        raise ValueError("source root escapes assets")
    output = assets / recipe["profile"] / "portraits" / recipe["revision"]
    if not output.resolve().is_relative_to(assets):raise ValueError("output escapes assets")
    if output.exists():raise ValueError("snapshot already exists")
    originals, frames, hashes, inputs = {}, {}, {}, {}

    def source(relative):
        path = (source_root/relative).resolve()
        if not path.is_relative_to(source_root):raise ValueError("source path escapes source root")
        data = path.read_bytes()
        hashes[relative] = hashlib.sha256(data).hexdigest()
        inputs[relative] = (hashes[relative]+"-"+path.name, data)
        return path, data

    def image(relative):
        path,_ = source(relative)
        with Image.open(path) as im:result = im.convert("RGBA")
        if result.size!=(128,128):raise ValueError("snapshot expects registered 128px canvases")
        for old,new in recipe.get("replace_rgb",[]):
            for y in range(result.height):
                for x in range(result.width):
                    r,g,b,a=result.getpixel((x,y))
                    if [r,g,b]==old:result.putpixel((x,y),(*new,a))
        return result

    for name,relative in recipe["frames"].items():frames[name]=image(relative)
    for operation in recipe.get("composites",[]):
        candidate=image(operation["candidate"])
        path,_=source(operation["mask"])
        with Image.open(path) as im:mask=im.convert("L")
        frames[operation["target"]]=compose_feature(frames[operation["target"]],candidate,mask)
    for relative in recipe["originals"]:
        path,data=source(relative)
        originals[path.name]=data
    output.mkdir(parents=True)
    (output/"layers").mkdir()
    (output/"sources").mkdir()
    (output/"inputs").mkdir()
    for name,data in originals.items():(output/"sources"/name).write_bytes(data)
    for name,frame in frames.items():frame.save(output/"layers"/(name+".png"))
    for filename,data in inputs.values():(output/"inputs"/filename).write_bytes(data)
    rebuild=dict(recipe)
    rebuild["source_root"]=output.relative_to(assets).as_posix()
    rebuild["revision"]=recipe["revision"]+"-rebuilt"
    rebuild["frames"]={name:"inputs/"+inputs[relative][0] for name,relative in recipe["frames"].items()}
    rebuild["composites"]=[{**operation,"candidate":"inputs/"+inputs[operation["candidate"]][0],
                            "mask":"inputs/"+inputs[operation["mask"]][0]} for operation in recipe.get("composites",[])]
    rebuild["originals"]=["sources/"+Path(relative).name for relative in recipe["originals"]]
    (output/"rebuild.json").write_text(json.dumps(rebuild,indent=2)+"\n")
    clips={}
    for side in ("left","right"):
        for family in ("rest","thinking","opened"):
            clips[f"{side}-{family}"]={"loop":True,"steps":[
                {"frame":f"{side}-{family}-{i}","duration_ms":duration} for i,duration in ((0,1600),(1,60),(2,120),(1,60))]}
    profile={"schema_version":1,"profile":recipe["profile"],"canvas":[128,128],
             "frames":{name:(output/"layers"/(name+".png")).relative_to(assets).as_posix() for name in frames},
             "clips":clips,"review":recipe["review"],"source_provenance":hashes,"archive_recipe":recipe,
             "visual_approval":recipe["review_status"]}
    (output/"profile.json").write_text(json.dumps(profile,indent=2)+"\n")
    print(output/"profile.json")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe",type=Path,required=True)
    parser.add_argument("--assets",type=Path,required=True)
    args=parser.parse_args()
    archive(args.recipe,args.assets)
