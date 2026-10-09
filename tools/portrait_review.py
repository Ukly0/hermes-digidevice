"""Offline portrait design exporter, NOT the native firmware renderer.

Load a persistent profile and shared scene; export only explicitly selected
states. Native rendering/voice integration remains a separate implementation.
"""
import argparse
import json
import hashlib
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps


def export(profile_path, assets, out, states, sides):
    profile_path, assets, out = map(Path, (profile_path, assets, out))
    assets = assets.resolve()
    profile = json.loads(profile_path.read_text())

    def path(relative):
        result = (assets / relative).resolve()
        if not result.is_relative_to(assets):
            raise ValueError("asset path escapes its root")
        return result

    scene = json.loads(path(profile["review"]["scene"]).read_text())
    n = scene["canvas"][0]
    if scene["canvas"] != [466,466]:
        raise ValueError("review target must be 466x466")
    if any(state not in scene["labels"] for state in states):
        raise ValueError("unknown review state")
    if any(state in profile["review"].get("unsupported_states",[]) for state in states):
        raise ValueError("requested state has no authored animation")
    if any(side not in ("left","right") for side in sides):
        raise ValueError("unknown orientation")
    black, ink = (0,0,0), (227,245,234)
    palette = [tuple(c) for c in profile["review"]["palette"]]
    accents = {state:tuple(c) for state,c in profile["review"]["accents"].items()}
    frame = Image.open(path(scene["frame"])).convert("L")
    circle = Image.open(path(scene["panel_mask"])).convert("L")
    outside = circle.point(lambda v:255-v)
    ring = Image.frombytes("L",(n,n),bytes(255 if frame.getpixel((x,y)) and
        228<=math.hypot(x-232.5,y-232.5)<229 else 0 for y in range(n) for x in range(n)))
    size = scene["avatar_size"]
    ax,ay = scene["avatar_origin"]
    baseline = scene["caption_baseline"]
    font = ImageFont.truetype(str(path(scene["font"])),scene["font_size"])
    pulse,reaction = scene["pulse"],scene["reaction"]
    step = scene["frame_step_ms"]
    animated = set(scene["animated_labels"])
    banks,occupied = {},{}
    for side in sides:
        occupied[side] = Image.new("L",(n,n))
        for family in ("rest","thinking","opened"):
            bank = []
            for i in range(3):
                with Image.open(path(profile["frames"][f"{side}-{family}-{i}"])) as image:
                    bank.append(image.convert("RGBA").resize((size,size),Image.Resampling.NEAREST))
            banks[side,family] = bank
            for image in bank:
                mask = Image.new("L",(n,n)); mask.paste(image.getchannel("A"),(ax,ay))
                if ImageChops.multiply(mask,frame).getbbox():
                    raise ValueError("portrait intersects frame")
                occupied[side] = ImageChops.lighter(occupied[side],mask)

    glyphs = {}
    for state in states:
        for ch in scene["labels"][state]:
            if ch in glyphs:continue
            left,top,right,bottom = font.getbbox(ch,anchor="ls")
            mask = Image.new("L",(max(1,right-left),max(1,bottom-top)))
            if right>left and bottom>top:
                ImageDraw.Draw(mask).text((-left,-top),ch,font=font,fill=255,anchor="ls")
            glyphs[ch] = (mask.point(lambda v:255 if v>=128 else 0),left,top)

    ambient=[]
    for definition in profile["review"].get("ambient_layers",[]):
        effect_profile=json.loads(path(definition["profile"]).read_text())
        clip=effect_profile["clips"][definition["clip"]]
        frames={name:Image.open(path(relative)).convert("RGBA") for name,relative in effect_profile["frames"].items()}
        for side in sides:
            positions=[definition["anchors"][side]]+[values[side] for values in definition.get("state_anchors",{}).values()]
            for x,y in positions:
                for sprite in frames.values():
                    if side=="right" and definition.get("mirror_right",False):sprite=ImageOps.mirror(sprite)
                    mask=Image.new("L",(n,n));mask.paste(sprite.getchannel("A"),(x,y))
                    if x<0 or y<0 or x+sprite.width>n or y+sprite.height>n or ImageChops.multiply(mask,outside).getbbox():
                        raise ValueError("ambient effect would be clipped")
        ambient.append((definition,clip,frames))

    effects,anchors,halos = {},{},{}
    for state in states:
        kind = "thinking" if state=="processing" else state
        if kind not in scene["effects"]:continue
        originals = [Image.open(path(name)).convert("RGBA") for name in scene["effects"][kind]]
        boxes = [image.getchannel("A").getbbox() for image in originals]
        box = (min(b[0] for b in boxes),min(b[1] for b in boxes),max(b[2] for b in boxes),max(b[3] for b in boxes))
        dimensions = (round((box[2]-box[0])*64/(box[3]-box[1])),64)
        effects[state] = []
        for image in originals:
            image = image.crop(box)
            for y in range(image.height):
                for x in range(image.width):
                    r,g,b,a = image.getpixel((x,y))
                    color = (ink if max(r,g,b)>200 else accents[state]) if kind=="thinking" else (accents[state] if g>=(80 if kind=="talking" else 120) else black)
                    image.putpixel((x,y),(*color,255 if a>=128 else 0))
            effects[state].append(image.resize(dimensions,Image.Resampling.NEAREST))
        for side in sides:
            union = Image.new("L",dimensions)
            for image in effects[state]:
                if side=="right":image=ImageOps.mirror(image)
                union=ImageChops.lighter(union,image.getchannel("A"))
            padded=Image.new("L",(union.width+4,union.height+4));padded.paste(union,(2,2))
            halo=padded.filter(ImageFilter.MaxFilter(5))
            candidates=[]
            search=profile["review"].get("effect_search",{}).get(state,
                   profile["review"].get("effect_search",{}).get(kind,{}))
            xr=search.get("x",[20,110] if kind=="talking" else [280,352])
            yr=search.get("y",[224,310] if kind=="talking" else [28,114])
            for y in range(yr[0],yr[1],2):
                for canonical_x in range(xr[0],xr[1],2):
                    x=n-canonical_x-union.width if side=="right" else canonical_x
                    mask=Image.new("L",(n,n));mask.paste(halo,(x-2,y-2))
                    if ImageChops.multiply(mask,outside).getbbox() or ImageChops.multiply(mask,occupied[side]).getbbox():continue
                    mask=Image.new("L",(n,n));mask.paste(union,(x,y))
                    if not ImageChops.multiply(mask,frame).getbbox():continue
                    tx,ty=search.get("target",[52,248] if kind=="talking" else [304,62])
                    candidates.append(((canonical_x-tx)**2+(y-ty)**2,x,y))
            if not candidates:raise ValueError("no safe effect anchor")
            _,x,y=min(candidates);anchors[side,state]=(x,y);halos[side,state]=halo

    def render(side,state,tick,ticks):
        image=Image.new("RGB",(n,n),black)
        image.paste(ink,(0,0),frame);image.paste(accents[state],(0,0),ring)
        motion=tick*step//scene["motion_step_ms"]
        eye=0
        if profile["review"].get("motion")=="clip":
            family="thinking" if state in ("thinking","processing") else "rest"
            clip=profile["clips"][f"{side}-{family}"]
            t=tick*step%sum(item["duration_ms"] for item in clip["steps"])
            for item in clip["steps"]:
                if t<item["duration_ms"]:
                    eye=int(item["frame"].rsplit("-",1)[1]);break
                t-=item["duration_ms"]
        else:
            for onset in scene["blink_onsets"]:
                if (onset+4)*scene["motion_step_ms"]>=ticks*step:continue
                delta=motion-onset
                if delta in (0,3):eye=1
                if delta in (1,2):eye=2
        speaking=state=="talking" and motion%scene["mouth_loop_steps"] in scene["mouth_open_steps"]
        family="opened" if speaking else "thinking" if state in ("thinking","processing") else "rest"
        avatar=banks[side,family][eye];image.paste(avatar,(ax,ay),avatar)
        for definition,clip,frames in ambient:
            if state not in definition["states"]:continue
            t=tick*step%sum(item["duration_ms"] for item in clip["steps"])
            for item in clip["steps"]:
                if t<item["duration_ms"]:
                    sprite=frames[item["frame"]]
                    if side=="right" and definition.get("mirror_right",False):sprite=ImageOps.mirror(sprite)
                    at=definition.get("state_anchors",{}).get(state,definition["anchors"])[side]
                    image.paste(sprite,tuple(at),sprite)
                    break
                t-=item["duration_ms"]
        if state in effects and (state!="talking" or speaking):
            sprite=effects[state][motion//scene["effect_stride"][state]%len(effects[state])]
            if side=="right":sprite=ImageOps.mirror(sprite)
            x,y=anchors[side,state];image.paste(black,(x-2,y-2),halos[side,state]);image.paste(sprite,(x,y),sprite)
        text=scene["labels"][state]
        start=(n-round(font.getlength(text)))//2
        active=tick//len(pulse)%len(text) if state in animated else -1
        partners=scene["secondary_letter_offsets"]
        secondary=(active+partners[active%len(partners)])%len(text) if active>=0 else -1
        text_mask=Image.new("L",(n,n))
        moving=0
        for i,ch in enumerate(text):
            offset=pulse[tick%len(pulse)] if i==active else reaction[tick%len(pulse)] if i==secondary else 0
            moving+=bool(offset)
            mask,left,top=glyphs[ch]
            x=start+round(font.getlength(text[:i]))+left;y=baseline+top+offset
            color=ink if i==active or (i==secondary and offset) else accents[state]
            image.paste(color,(x,y),mask);text_mask.paste(255,(x,y),mask)
        assert moving<=2
        assert ImageChops.multiply(text_mask,frame).getbbox() is None
        assert ImageChops.multiply(text_mask,occupied[side]).getbbox() is None
        assert ImageChops.multiply(image.convert("L"),outside).getbbox() is None
        return image

    if out.exists():raise ValueError("review output must be new")
    out.mkdir(parents=True)
    color_table=Image.new("P",(1,1));color_table.putpalette([v for c in palette for v in c]+[0]*(768-3*len(palette)))
    durations={}
    for side in sides:
        for state in states:
            ticks=len(scene["labels"][state])*len(pulse) if state in animated else scene["static_preview_steps"]
            periods=[sum(item["duration_ms"] for item in clip["steps"]) for definition,clip,_ in ambient if state in definition["states"]]
            if periods:
                duration=math.lcm(ticks*step,*periods)
                if duration%step or duration>60000:raise ValueError("ambient review loop is too long or incompatible")
                ticks=duration//step
            images=[render(side,state,tick,ticks) for tick in range(ticks)]
            indexed=[image.quantize(palette=color_table,dither=Image.Dither.NONE) for image in images]
            indexed[0].save(out/f"{side}-{state}.gif",save_all=True,append_images=indexed[1:],duration=step,loop=0,disposal=2,optimize=False)
            images[3 if state=="talking" else 8 if state in animated else 6].save(out/f"{side}-{state}.png")
            durations[state]=ticks*step
    (out/"manifest.json").write_text(json.dumps({"profile":profile["profile"],"implementation":"offline asset design review, not native core",
        "profile_path":profile_path.name,
        "input_hashes":{"profile":hashlib.sha256(profile_path.read_bytes()).hexdigest(),
                        "scene":hashlib.sha256(path(profile["review"]["scene"]).read_bytes()).hexdigest(),
                        "font":hashlib.sha256(path(scene["font"]).read_bytes()).hexdigest()},
        "scene":scene,"palette":palette,"durations_ms":durations,
        "ambient_layers":profile["review"].get("ambient_layers",[]),
        "effect_anchors":{f"{s}-{st}":at for (s,st),at in anchors.items()},"visual_approval":"candidate"},indent=2)+"\n")
    print(f"Prepared {len(states)*len(sides)} review animations: {out}")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile",type=Path,required=True)
    parser.add_argument("--assets",type=Path,required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--state",action="append",choices=("rest","thinking","listening","talking","processing"))
    parser.add_argument("--side",action="append",choices=("left","right"))
    args=parser.parse_args()
    export(args.profile,args.assets,args.out,args.state or ["rest"],args.side or ["left"])
