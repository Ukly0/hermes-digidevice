"""Prepare an external portrait recipe; no character artwork is bundled.

This is offline asset authoring, not the firmware renderer. Recipes explicitly
choose source poses, palette, eye apertures, and mouth ownership/registration.
"""
import argparse
import hashlib
import json
import re
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps
from hermes_gadget.portraits import compose_feature


def prepare(recipe_path, assets, imports):
    recipe_path, assets, imports = map(Path, (recipe_path, assets, imports))
    assets, imports = assets.resolve(), imports.resolve()
    recipe = json.loads(recipe_path.read_text())
    if not isinstance(recipe, dict) or not re.fullmatch(r"[a-z][a-z0-9_]*", recipe.get("profile", "")):
        raise ValueError("invalid profile identifier")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", recipe.get("revision", "")):
        raise ValueError("invalid revision")
    if not assets.is_dir() or not imports.is_dir():
        raise ValueError("assets/imports directories must exist")
    if (not isinstance(recipe.get("palette"), list) or not 1 <= len(recipe["palette"]) <= 256 or
        any(not isinstance(c,list) or len(c)!=3 or any(type(v) is not int or not 0<=v<=255 for v in c)
            for c in recipe["palette"])):
        raise ValueError("invalid palette")
    if recipe.get("canvas") != [128,128]:
        raise ValueError("authoring tool expects a 128x128 source canvas")
    palette = [tuple(c) for c in recipe["palette"]]
    width, height = recipe["canvas"]
    sources, provenance = {}, {}
    root = assets / recipe["profile"] / "portraits" / recipe["revision"]
    if not root.resolve().is_relative_to(assets):
        raise ValueError("output escapes assets root")
    if root.exists():
        raise ValueError("revision already exists; use a new revision, never overwrite a reference")
    original_bytes = {}
    shared_bytes = {}
    repository = Path(__file__).resolve().parents[1]
    for destination, relative_source in recipe.get("shared_imports", {}).items():
        target, source = (assets/destination).resolve(), (repository/relative_source).resolve()
        if not target.is_relative_to(assets.resolve()) or not source.is_relative_to(repository):
            raise ValueError("shared asset path escapes its root")
        if not source.exists() and target.is_file():
            # A previously imported private shared asset survives build cleanup.
            continue
        data = source.read_bytes()
        if target.exists() and target.read_bytes() != data:
            raise ValueError("shared asset already exists with different content")
        shared_bytes[target] = data
    for name in recipe["sources"]:
        if Path(name).name != name:
            raise ValueError("source names must be basenames")
        path = (imports / name).resolve()
        if not path.is_relative_to(imports):
            raise ValueError("source escapes imports root")
        data = path.read_bytes()
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (width, height):
                raise ValueError(f"expected registered {width}x{height} PNG: {name}")
            source = image.convert("RGBA")
        original_bytes[name] = data
        provenance[name] = hashlib.sha256(data).hexdigest()
        normalized = Image.new("RGBA", source.size)
        for y in range(height):
            for x in range(width):
                r, g, b, a = source.getpixel((x, y))
                if a < 128:
                    color = palette[0]
                elif (.299*r + .587*g + .114*b) < recipe["outline_luma"]:
                    color = palette[recipe["outline_index"]]
                else:
                    color = min(palette, key=lambda c: (r-c[0])**2+(g-c[1])**2+(b-c[2])**2)
                normalized.putpixel((x, y), (*color, 255 if a >= 128 else 0))
        sources[name] = normalized

    def motion_bank(base):
        if "idle" in recipe:
            if recipe["idle"].get("kind")=="static":
                return [base,base.copy(),base.copy()],Image.new("L",base.size)
            # Insect profiles use explicit appendage frames, never eyelid masks.
            phases = [base]
            permission = Image.new("L",base.size)
            for phase,duration in recipe["idle"]["timeline"]:
                if type(phase) is not int or not 0<=phase<=2 or type(duration) is not int or not 1<=duration<=65535:
                    raise ValueError("invalid appendage timeline")
            for part in recipe["idle"]["parts"]:
                x0,y0,x1,y1 = part["region"]
                if not 0<=x0<x1<=width or not 0<=y0<y1<=height:
                    raise ValueError("invalid appendage region")
                dx,dy = part["offset"]
                if any(type(v) is not int or not -4<=v<=4 for v in (dx,dy)):
                    raise ValueError("appendage offset must be an integer in -4..4")
                feature = base.copy()
                mask = Image.new("L",base.size)
                selected = []
                for y in range(y0,y1):
                    for x in range(x0,x1):
                        p = base.getpixel((x,y))
                        if p[3] and p[:3]==palette[part["color_index"]]:
                            # Only the distal section moves; the attachment stays fixed.
                            shift = dx if y<part["moving_until_row"] else 0
                            if shift or dy:selected.append((x,y,shift,dy,p))
                if not selected:raise ValueError("appendage region contains no movable pixels")
                for x,y,sx,sy,p in selected:
                    feature.putpixel((x,y),tuple(part["backdrop_rgba"]))
                    mask.putpixel((x,y),255)
                for x,y,sx,sy,p in selected:
                    if not 0<=x+sx<width or not 0<=y+sy<height:
                        raise ValueError("appendage motion would clip source pixels")
                    feature.putpixel((x+sx,y+sy),p)
                    mask.putpixel((x+sx,y+sy),255)
                phases.append(compose_feature(base,feature,mask))
                permission=ImageChops.lighter(permission,mask)
            if len(phases)!=3:raise ValueError("review expects neutral plus two appendage phases")
            return phases,permission
        masks = []
        half, closed = base.copy(), base.copy()
        eyes = recipe["eyes"]
        ratio = eyes.get("lid_width_ratio")
        if ratio is not None and (type(ratio) not in (int,float) or not math.isfinite(ratio) or not .25<=ratio<=1.25):
            raise ValueError("lid_width_ratio must be finite and between .25 and 1.25")
        if type(eyes.get("align_lid_height",False)) is not bool:
            raise ValueError("align_lid_height must be boolean")
        component_mode = eyes.get("iris_components","all")
        if component_mode not in ("all","largest"):
            raise ValueError("iris_components must be all or largest")
        apertures = []
        for region in eyes["regions"]:
            x0, y0, x1, y1 = region
            if not 0<=x0<x1<=width or not 0<=y0<y1<=height:
                raise ValueError("invalid eye region")
            points = [(x,y) for y in range(y0,y1) for x in range(x0,x1)
                      if base.getpixel((x,y))[:3] == palette[eyes["iris_index"]]]
            if not points:
                raise ValueError("authored eye region contains no iris pixels")
            if component_mode == "largest":
                pending = set(points)
                components = []
                while pending:
                    stack = [pending.pop()]
                    group = []
                    while stack:
                        x,y = stack.pop()
                        group.append((x,y))
                        for dx in (-1,0,1):
                            for dy in (-1,0,1):
                                neighbor = (x+dx,y+dy)
                                if neighbor in pending:
                                    pending.remove(neighbor)
                                    stack.append(neighbor)
                    components.append(group)
                points = max(components,key=lambda group:(len(group),-min(y for x,y in group),-min(x for x,y in group)))
            pad = eyes["padding"]
            bounds = (min(x for x,y in points)-pad, min(y for x,y in points)-pad,
                      max(x for x,y in points)+pad, max(y for x,y in points)+pad)
            mask = Image.new("L", base.size)
            ImageDraw.Draw(mask).ellipse(bounds, fill=255)
            point_set = {(x,y) for y in range(max(0,bounds[1]),min(height,bounds[3]+1))
                         for x in range(max(0,bounds[0]),min(width,bounds[2]+1))
                         if base.getpixel((x,y))[:3]==palette[eyes["iris_index"]]}
            for y in range(height):
                for x in range(width):
                    if base.getpixel((x,y))[3] == 0:
                        mask.putpixel((x,y),0)
                    elif (x,y) in point_set:
                        mask.putpixel((x,y),255)
            cx, cy = (bounds[0]+bounds[2])//2, (bounds[1]+bounds[3])//2
            iris_width = max(x for x,y in points)-min(x for x,y in points)+1
            apertures.append((mask,bounds,cx,cy,iris_width))
        shared_cy = round(sum(cy for _,_,_,cy,_ in apertures)/len(apertures))
        for mask,bounds,cx,cy,iris_width in apertures:
            if eyes.get("align_lid_height",False):
                cy = shared_cy
            for y in range(height):
                for x in range(width):
                    if mask.getpixel((x,y)):
                        color = (*palette[eyes["fill_index"]], base.getpixel((x,y))[3])
                        closed.putpixel((x,y),color)
                        if y <= cy:
                            half.putpixel((x,y),color)
            for image, drop in ((half,0),(closed,eyes["closed_drop"])):
                line = Image.new("L", base.size)
                if ratio is None:
                    left,right = bounds[0]+2,bounds[2]-2
                else:
                    span = max(3,round(iris_width*ratio))
                    left,right = cx-span//2,cx+span//2
                ImageDraw.Draw(line).line([(left,cy+drop-1),(cx,cy+drop+1),
                                          (right,cy+drop-1)],fill=255,width=1)
                for y in range(height):
                    for x in range(width):
                        if mask.getpixel((x,y)) and line.getpixel((x,y)):
                            image.putpixel((x,y),(*palette[recipe["outline_index"]],base.getpixel((x,y))[3]))
            assert all(closed.getpixel((x,y))[:3] != palette[eyes["iris_index"]]
                       for y in range(height) for x in range(width)
                       if mask.getpixel((x,y)) and base.getpixel((x,y))[:3]==palette[eyes["iris_index"]])
            masks.append(mask)
        permission = Image.new("L", base.size)
        for mask in masks:
            permission = ImageChops.lighter(permission, mask)
        return [base,compose_feature(base,half,permission),compose_feature(base,closed,permission)],permission

    def anchor(image, box):
        x0,y0,x1,y1 = box
        if not 0<=x0<x1<=width or not 0<=y0<y1<=height:
            raise ValueError("invalid anchor region")
        points = [(x,y) for y in range(y0,y1) for x in range(x0,x1)
                  if image.getpixel((x,y))[:3] == palette[recipe["outline_index"]]]
        if not points:
            raise ValueError("nose registration region contains no outline pixels")
        return round(sum(x for x,y in points)/len(points)),round(sum(y for x,y in points)/len(points))

    outputs, masks, registration = {}, {}, {}
    for side, poses in recipe["poses"].items():
        if side not in ("left","right") or type(poses["mirror_canonical"]) is not bool:
            raise ValueError("invalid orientation")
        mirror = poses["mirror_canonical"]
        base, thinking, donor = [sources[poses[k]].copy() for k in ("neutral","thinking","mouth")]
        if mirror:
            base,thinking,donor = map(ImageOps.mirror,(base,thinking,donor))
        for target,region,color_index in poses.get("clear_decorations",[]):
            image={"neutral":base,"thinking":thinking}[target]
            x0,y0,x1,y1=region
            if not 0<=x0<x1<=width or not 0<=y0<y1<=height:raise ValueError("invalid decoration region")
            for y in range(y0,y1):
                for x in range(x0,x1):
                    if image.getpixel((x,y))[:3]==palette[color_index]:image.putpixel((x,y),(0,0,0,0))
        rest,eye_mask = motion_bank(base)
        think,think_mask = motion_bank(thinking)
        if not recipe["mouth"].get("enabled",True):
            opened = rest
            permission = Image.new("L",base.size)
            registration[side] = None
            for family,bank in (("rest",rest),("thinking",think),("opened",opened)):
                for index,image in enumerate(bank):
                    outputs[f"{side}-{family}-{index}"] = ImageOps.mirror(image) if mirror else image
            for family,mask in (("rest",eye_mask),("thinking",think_mask),("mouth",permission)):
                masks[f"{side}-{family}"] = ImageOps.mirror(mask) if mirror else mask
            continue
        mouth = recipe["mouth"]
        a,b = anchor(base,mouth["base_nose_roi"]),anchor(donor,mouth["donor_nose_roi"])
        dx,dy = a[0]-b[0],a[1]-b[1]
        registration[side] = [dx,dy]
        component = Image.new("L", base.size)
        x0,y0,x1,y1 = mouth["donor_roi"]
        if not 0<=x0<x1<=width or not 0<=y0<y1<=height:
            raise ValueError("invalid mouth region")
        allowed_colors = {palette[i] for i in mouth["donor_color_indices"]}
        for y in range(y0,y1):
            for x in range(x0,x1):
                if donor.getpixel((x,y))[3] and donor.getpixel((x,y))[:3] in allowed_colors:
                    component.putpixel((x,y),255)
        shifted = Image.new("L",base.size)
        shifted.paste(component,(dx,dy))
        shifted = shifted.filter(ImageFilter.MaxFilter(3))
        aligned = Image.new("RGBA",base.size)
        aligned.paste(donor,(dx,dy))
        clear = Image.new("L",base.size)
        x0,y0,x1,y1 = mouth["clear_roi"]
        if not 0<=x0<x1<=width or not 0<=y0<y1<=height:
            raise ValueError("invalid mouth clear region")
        clear_colors = {palette[i] for i in mouth["clear_color_indices"]}
        for y in range(y0,y1):
            for x in range(x0,x1):
                if base.getpixel((x,y))[:3] in clear_colors:
                    clear.putpixel((x,y),255)
        permission = ImageChops.subtract(ImageChops.lighter(clear,shifted),eye_mask)
        opened = []
        for frame in rest:
            plane = frame.copy()
            plane.paste((*palette[mouth["fill_index"]],255),(0,0),clear)
            feature = Image.composite(aligned,plane,shifted)
            opened.append(compose_feature(frame,feature,permission))
        for family,bank in (("rest",rest),("thinking",think),("opened",opened)):
            for index,image in enumerate(bank):
                if mirror:
                    image = ImageOps.mirror(image)
                outputs[f"{side}-{family}-{index}"] = image
        for family,mask in (("rest",eye_mask),("thinking",think_mask),("mouth",permission)):
            masks[f"{side}-{family}"] = ImageOps.mirror(mask) if mirror else mask

    # Persist original bytes and authored data, not merely temporary screenshots.
    root.mkdir(parents=True)
    for target,data in shared_bytes.items():
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():target.write_bytes(data)
    (root/"sources").mkdir()
    (root/"layers").mkdir()
    (root/"masks").mkdir()
    for name,data in original_bytes.items():
        (root/"sources"/name).write_bytes(data)
    for name,image in outputs.items():
        image.save(root/"layers"/(name+".png"))
    for name,mask in masks.items():
        mask.save(root/"masks"/(name+".png"))
    frames = {name:(root/"layers"/(name+".png")).relative_to(assets).as_posix() for name in outputs}
    clips = {}
    for side in recipe["poses"]:
        for family in ("rest","thinking","opened"):
            timeline = recipe["idle"]["timeline"] if "idle" in recipe else ((0,1600),(1,60),(2,120),(1,60))
            clips[f"{side}-{family}"] = {"loop":True,"steps":[
                {"frame":f"{side}-{family}-{i}","duration_ms":duration} for i,duration in timeline]}
    profile = {"schema_version":1,"profile":recipe["profile"],"canvas":recipe["canvas"],
               "frames":frames,"clips":clips,"review":recipe["review"],
               "source_provenance":provenance,"authoring_recipe":recipe,
               "registration":registration,"visual_approval":"candidate, not yet approved",
               "feature_masks":{name:(root/"masks"/(name+".png")).relative_to(assets).as_posix() for name in masks}}
    (root/"profile.json").write_text(json.dumps(profile,indent=2)+"\n")
    print(root/"profile.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe",type=Path,required=True)
    parser.add_argument("--assets",type=Path,required=True)
    parser.add_argument("--imports",type=Path,required=True)
    args = parser.parse_args()
    prepare(args.recipe.resolve(),args.assets.resolve(),args.imports.resolve())
