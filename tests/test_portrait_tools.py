"""Synthetic authoring/archive fixtures; no private character pixels or fonts."""
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

pytest.importorskip("PIL")
from PIL import Image, ImageDraw


def tool(name):
    path = Path(__file__).resolve().parents[1] / "tools" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def authored(tmp_path):
    assets, imports = tmp_path / "assets", tmp_path / "imports"
    assets.mkdir(); imports.mkdir()
    palette = [[0,0,0],[227,245,234],[66,165,198],[232,138,85]]
    base = Image.new("RGBA", (128,128), (*palette[1],255))
    draw = ImageDraw.Draw(base)
    draw.rectangle((14,22,24,32),fill=(*palette[2],255))
    draw.rectangle((76,22,86,32),fill=(*palette[2],255))
    draw.rectangle((54,52,58,55),fill=(0,0,0,255))
    draw.line((50,68,62,68),fill=(0,0,0,255))
    base.save(imports / "base.png")
    donor = base.copy()
    draw = ImageDraw.Draw(donor)
    draw.rectangle((51,67,64,82),fill=(0,0,0,255))
    draw.rectangle((54,75,62,83),fill=(*palette[3],255))
    donor.save(imports / "mouth.png")
    recipe = {
        "profile":"sample", "revision":"candidate-01", "canvas":[128,128],
        "sources":["base.png","mouth.png"], "palette":palette,
        "outline_index":0, "outline_luma":45,
        "eyes":{"regions":[[10,15,35,45],[70,15,100,45]],"iris_index":2,"fill_index":1,"padding":4,"closed_drop":4},
        "mouth":{"base_nose_roi":[50,48,62,60],"donor_nose_roi":[50,48,62,60],
                 "donor_roi":[45,65,70,87],"donor_color_indices":[0,3],
                 "clear_roi":[45,64,70,85],"clear_color_indices":[0],"fill_index":1},
        "poses":{side:{"neutral":"base.png","thinking":"base.png","mouth":"mouth.png","mirror_canonical":False}
                 for side in ("left","right")},
        "review":{}
    }
    path = tmp_path / "recipe.json"
    path.write_text(json.dumps(recipe))
    return assets, imports, path, recipe


def test_authoring_persists_originals_masks_and_valid_export(authored, tmp_path):
    from hermes_gadget.portrait_assets import generate
    assets, imports, recipe, _ = authored
    tool("prepare_portrait_profile").prepare(recipe, assets, imports)
    project = assets / "sample/portraits/candidate-01"
    assert (project / "sources/base.png").read_bytes() == (imports / "base.png").read_bytes()
    assert len(list((project / "layers").glob("*.png"))) == 18
    with Image.open(project / "layers/left-rest-2.png") as image:
        assert (66,165,198) not in {rgb[:3] for count,rgb in image.getcolors(256)}
    result = generate(project / "profile.json", assets, tmp_path / "cpp")
    assert result["budget"]["payload_bytes"] < result["budget"]["naive_fullframe_bytes"]
    with pytest.raises(ValueError, match="already exists"):
        tool("prepare_portrait_profile").prepare(recipe, assets, imports)


def test_compact_lids_share_height_without_changing_open_pose(authored):
    assets, imports, path, recipe = authored
    # Offset one authored eye vertically to expose independently centred lids.
    with Image.open(imports / "base.png") as image:
        image = image.convert("RGBA")
        draw = ImageDraw.Draw(image)
        draw.rectangle((76,22,86,32),fill=(227,245,234,255))
        draw.rectangle((76,24,86,34),fill=(66,165,198,255))
        # An unrelated blue ear/shadow pixel must not enlarge or raise the iris.
        draw.point((92,16),fill=(66,165,198,255))
        image.save(imports / "base.png")
    recipe["eyes"].update(lid_width_ratio=.8,align_lid_height=True,closed_drop=1,iris_components="largest")
    path.write_text(json.dumps(recipe))
    tool("prepare_portrait_profile").prepare(path,assets,imports)
    folder=assets/"sample/portraits/candidate-01/layers"
    with Image.open(folder/"left-rest-0.png") as opened,Image.open(folder/"left-rest-2.png") as closed:
        boxes=[]
        for x0,y0,x1,y1 in recipe["eyes"]["regions"]:
            points=[(x,y) for y in range(y0,y1) for x in range(x0,x1) if closed.getpixel((x,y))[:3]==(0,0,0)]
            boxes.append((min(x for x,y in points),min(y for x,y in points),max(x for x,y in points),max(y for x,y in points)))
        assert boxes[0][1::2]==boxes[1][1::2]
        assert all(box[2]-box[0]<=10 for box in boxes)
        assert opened.getpixel((76,24))[:3]==(66,165,198)
        assert closed.getpixel((92,16))[:3]==(66,165,198)


@pytest.mark.parametrize("ratio", [float("nan"),0,2,True])
def test_invalid_lid_ratio_rejected_before_output(authored,ratio):
    assets, imports, path, recipe=authored
    recipe["eyes"]["lid_width_ratio"]=ratio
    path.write_text(json.dumps(recipe))
    with pytest.raises(ValueError,match="lid_width_ratio"):
        tool("prepare_portrait_profile").prepare(path,assets,imports)
    assert not (assets/"sample").exists()


@pytest.mark.parametrize("change", ["revision", "palette", "source", "eye"])
def test_invalid_authoring_does_not_create_revision(authored, change):
    assets, imports, path, recipe = authored
    if change == "revision": recipe["revision"] = "../../escape"
    if change == "palette": recipe["palette"][0][0] = True
    if change == "source": recipe["sources"][0] = "../base.png"
    if change == "eye": recipe["eyes"]["regions"][0][0] = -1
    path.write_text(json.dumps(recipe))
    with pytest.raises(ValueError): tool("prepare_portrait_profile").prepare(path, assets, imports)
    assert not (assets / "sample").exists()


def test_archive_rebuild_survives_original_input_cleanup(tmp_path):
    assets = tmp_path / "assets"
    inputs = assets / "inputs"
    inputs.mkdir(parents=True)
    Image.new("RGBA", (128,128), (120,130,140,255)).save(inputs / "base.png")
    Image.new("RGBA", (128,128), (210,100,80,255)).save(inputs / "open.png")
    mask = Image.new("L", (128,128)); ImageDraw.Draw(mask).rectangle((20,20,30,30),fill=255)
    mask.save(inputs / "mask.png")
    frames = {f"{side}-{family}-{i}":"base.png" for side in ("left","right")
              for family in ("rest","thinking","opened") for i in range(3)}
    recipe = {"profile":"snapshot", "revision":"selected-01", "source_root":"inputs",
              "frames":frames,"composites":[{"target":"left-opened-0","candidate":"open.png","mask":"mask.png"}],
              "originals":["base.png","open.png"],"review":{},"review_status":"synthetic"}
    path = tmp_path / "archive.json"; path.write_text(json.dumps(recipe))
    module = tool("archive_portrait_snapshot")
    module.archive(path,assets)
    first = assets / "snapshot/portraits/selected-01"
    shutil.rmtree(inputs)
    module.archive(first / "rebuild.json",assets)
    rebuilt = assets / "snapshot/portraits/selected-01-rebuilt"
    for image in (first / "layers").glob("*.png"):
        assert image.read_bytes() == (rebuilt / "layers" / image.name).read_bytes()


def test_insect_idle_moves_appendages_not_eyes(authored):
    assets,imports,path,recipe=authored
    with Image.open(imports/"base.png") as image:
        image=image.convert("RGBA")
        draw=ImageDraw.Draw(image)
        draw.line((5,2,8,4),fill=(232,138,85,255))
        draw.line((105,2,108,4),fill=(232,138,85,255))
        image.save(imports/"base.png")
    recipe.pop("eyes")
    recipe["mouth"]={"enabled":False}
    recipe["idle"]={"parts":[
        {"region":[3,0,20,10],"color_index":3,"offset":[1,0],"moving_until_row":8,"backdrop_rgba":[227,245,234,255]},
        {"region":[100,0,120,10],"color_index":3,"offset":[-1,0],"moving_until_row":8,"backdrop_rgba":[227,245,234,255]}],
        "timeline":[[0,1200],[1,80],[0,120],[2,80],[0,920]]}
    path.write_text(json.dumps(recipe))
    tool("prepare_portrait_profile").prepare(path,assets,imports)
    root=assets/"sample/portraits/candidate-01"
    with Image.open(root/"layers/left-rest-0.png") as base:
        for i in (1,2):
            with Image.open(root/f"layers/left-rest-{i}.png") as frame:
                assert frame.tobytes()!=base.tobytes()
                assert frame.crop((0,15,128,128)).tobytes()==base.crop((0,15,128,128)).tobytes()
    profile=json.loads((root/"profile.json").read_text())
    assert sum(step["duration_ms"] for step in profile["clips"]["left-rest"]["steps"])==2400


def test_review_rejects_unauthored_state_before_output(tmp_path):
    assets=tmp_path/"assets";assets.mkdir()
    (assets/"scene.json").write_text(json.dumps({"canvas":[466,466],"labels":{"talking":"Speaking"}}))
    profile=tmp_path/"profile.json"
    profile.write_text(json.dumps({"review":{"scene":"scene.json","unsupported_states":["talking"]}}))
    out=tmp_path/"out"
    with pytest.raises(ValueError,match="no authored animation"):
        tool("portrait_review").export(profile,assets,out,["talking"],["left"])
    assert not out.exists()


def test_motion_effect_preserves_reference_and_exports_cyclic_ripples(tmp_path):
    from hermes_gadget.portrait_assets import generate
    assets=tmp_path/"assets";assets.mkdir()
    source=Image.new("RGBA",(16,16))
    ImageDraw.Draw(source).line((2,2,2,12),fill=(255,255,255,255))
    source.save(assets/"reference.png")
    recipe={"profile":"wave","source":"reference.png","output":"wave/v1",
            "source_rect":[0,0,16,16],"white_threshold":200,"stroke_growth":1,"canvas":[32,32],
            "frames":[{"name":"quiet","strokes":[]},
                      {"name":"near","strokes":[],"arcs":[{"center":[22,16],"radius":6,"start":120,"end":240,"width":2,"color":[227,245,234]}]},
                      {"name":"far","strokes":[],"arcs":[{"center":[22,16],"radius":10,"start":120,"end":240,"width":1,"color":[101,121,134]}]}],
            "timeline":[{"frame":"quiet","duration_ms":120},{"frame":"near","duration_ms":120},
                        {"frame":"far","duration_ms":120},{"frame":"quiet","duration_ms":120}]}
    path=tmp_path/"effect.json";path.write_text(json.dumps(recipe))
    tool("prepare_motion_effect").prepare(path,assets)
    root=assets/"wave/v1"
    assert (root/"source.png").read_bytes()==(assets/"reference.png").read_bytes()
    with Image.open(root/"quiet.png") as image:assert image.getchannel("A").getbbox() is None
    report=generate(root/"profile.json",assets,tmp_path/"cpp")
    assert not report["frames"]["quiet"]["tiles"]
    assert report["frames"]["near"]["tiles"]
    assert sum(item["duration_ms"] for item in report["clips"]["flow"]["steps"])==480


def test_static_insect_does_not_generate_eyelids_or_twitches(authored):
    assets,imports,path,recipe=authored
    recipe.pop("eyes")
    recipe["idle"]={"kind":"static","timeline":[[0,1000]]}
    recipe["mouth"]={"enabled":False}
    path.write_text(json.dumps(recipe))
    tool("prepare_portrait_profile").prepare(path,assets,imports)
    root=assets/"sample/portraits/candidate-01/layers"
    with Image.open(root/"left-rest-0.png") as base:
        for i in (1,2):
            with Image.open(root/f"left-rest-{i}.png") as frame:assert frame.tobytes()==base.tobytes()
