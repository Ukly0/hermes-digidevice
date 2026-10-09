# Portrait Animation Pipeline Plan

## Status and decision

The persistent asset/compiler part is now implemented; the native editor and
portrait runtime are still planned. Stop creating per-character scripts and
regenerating ten GIFs for each small change. Scratch scripts under `/tmp/opencode`
are experiments, not the production toolchain.

Biyomon returns to the earlier `build/biyomon-caption-bounce` preview and
`build/biyomon-portraits-v3` layers. The rejected `biyomon-caption-fixed` variant
is preserved. `build/portrait-selection.json` records the selected snapshots and
hashes; `build/portrait-review.html` links to them without regenerating artwork.
Known eye/beak problems remain in that earlier reference. Selection is not final
visual approval. Subsequent accepted speech/blink work has also been archived;
the selected source projects now live in the private asset repository, not only
in ignored build files.

The first small reusable primitive is `compose_feature` in
`python/hermes_gadget/portraits.py`: explicit binary replacement masks, matching
canvases and exact preservation of all other RGBA pixels. Synthetic tests cover
erasing a feature and rejecting soft/misaligned masks. A cached Biyomon speech
candidate constrains the previous mask using `build/biyomon-speaking-constraint.json`,
restores excess neck/chest edits and updates only the two speech GIFs. The selected
baseline remains unchanged. This is not the full compiler or native review UI.
An additional constraint can exclude protected feature rectangles, such as the
far-eye/beak junction. Compare cached GIFs at matching timestamps and require
zero differences outside the intended correction region, including scene effects
and typography; do not compare frame indices when duplicate frames are merged.

## Implemented tools

The private asset checkout now has `portraits/index.json`, `portraits/scene.json`,
shared frame/effect inputs and per-character projects. Gatomon `candidate-01`
stores its 12 original PNGs, hashes, authoring recipe, masks and 18 normalised
frame variants. Gabumon/Biyomon `selected-01` snapshots also store their source
and compositing inputs; `rebuild.json` can reproduce frames without the original
workspace build caches. Do not infer visual approval of every state from a
selected snapshot.

The reusable repository tools are:

- `tools/prepare_portrait_profile.py`: external recipe to registered source/frame/mask assets, without per-character code.
- `tools/archive_portrait_snapshot.py`: preserve selected legacy frames and explicit replacement operations.
- `tools/portrait_review.py`: optional offline design review from the saved project/scene; only selected states are exported by default. This temporary host compositor is not the native reference and must not be shipped as device animation logic.
- `python -m hermes_gadget.portrait_assets`: validated, deterministic static C++ frame/clip export with shared 16x16 RGB565/alpha tiles. Empty transparent tiles are omitted; identical tiles are deduplicated.

Example commands from an activated checkout environment (the output directories
must be new; the compiler's parent must already exist):

```bash
ASSETS=/path/to/digimon-assets
python tools/portrait_review.py --assets "$ASSETS" --profile "$ASSETS/gatomon/portraits/candidate-01/profile.json" --state talking --side left --out build/gatomon-review-next
mkdir -p build/portrait-firmware
python -m hermes_gadget.portrait_assets --assets "$ASSETS" --profile "$ASSETS/gatomon/portraits/candidate-01/profile.json" --out build/portrait-firmware/gatomon-next
```

The export includes `assets.hpp`, `assets.cpp`, tile binaries and a manifest with
source hashes, frame placement, clip durations, encoding and payload budget.
Its generic types are in `firmware/core/include/hg/portrait_assets.hpp`.
The static arrays compile as C++17, but no portrait renderer is connected to
`App` yet. Restore the backdrop before drawing every full frame; otherwise
omitted transparent tiles can retain old mouth/eye pixels. The authored clip
tables describe asset gestures, not complete voice/caption/effect state logic.
The 24px font and scene controller still need native integration.

Gatomon's candidate export contains 18 frames in 280 unique tiles: 152,320 bytes
of pixels/masks versus 626,688 bytes without deduplication. This excludes C++
metadata and is not the total linked ESP32 image size. Generation/compile checks
and decoded private-asset comparisons are desktop evidence only.

Gatomon's later blink revision separates the iris from unrelated palette-blue
ear pixels by selecting the largest connected component inside each authored
eye region. Cleanup masks still erase the complete socket, but lid stroke width
is configurable independently of mask padding. `lid_width_ratio` controls the
visible stroke; `align_lid_height` shares a vertical baseline between both eyes.
This avoids oversized or uneven lids without moving the open pose. The selected
`candidate-03` uses ratio 0.82 and keeps previous private revisions intact.

Tentomon uses a different, explicitly declared idle mode: no eyelid generation
or blink timer. Two distal antenna regions produce separate one-source-pixel
twitches while compound eyes, antenna attachments and thorax remain unchanged.
Its private recipe defines a 2400ms hold/twitch/return timeline; the review tool
samples the same exported clip data instead of applying the mammal blink cycle.
Effect search bounds are profile parameters, allowing icons to fit between the
large antennae/elytra without covering them. These are authored pixel-art idle
choices, not measured insect behaviour or recovered game timing. Do not invent
open-wing frames: only folded elytra are present in the supplied artwork.
Speech remains unauthored and the review tool rejects `talking` for this profile.
See the [pixel-art idle reference](https://www.slynyrd.com/blog/2018/8/19/pixelblog-8-intro-to-animation)
for small keyframe cycles, long holds and deliberate timing. Original images,
motion masks, recipe and C++ tile/clip export are retained for later integration.

The user rejected the antenna-tip twitch as fire-like and too static. The latest
Tentomon revision therefore holds antennae and the complete portrait still,
without blinking. It isolates the supplied white wing-speed mark from source
530, removes the baked-in mark from the thinking base, and redraws it as connected
expanding ripple arcs with a dim trailing echo. This is a stylised wing-motion
cue, not invented wing anatomy or a physical wingbeat simulation. The effect
has its own persistent 64px frame/clip project and native tile export.
Pose-specific anchors keep the ripple beside the elytron, not on the eye or
inside its grey spot. Offline review loop lengths are multiples of both the
caption and ambient clip periods to avoid a jump at the GIF loop boundary.
`tools/prepare_motion_effect.py` saves the original reference bytes, selected
source mark, recipe, frames and timeline without a new per-character script.

## Tentomon idle animation

The user rejected the antenna-tip twitch as fire-like and too static. A later
sprite-sheet study (`sprite-128x128px-8f-sheet.png`) showed the desired effect:
antennae and elytra shift sinusoidally while the body stays fixed. The 8-frame
sheet is derived from the original 526 portrait (482-1151 changed pixels per
frame vs base).

The accepted approach (`candidate-09`) takes the original 526, extracts antenna
tip pixels (yellow, top 20 rows: 436 px) and elytra edge pixels (grey, left/right
edges y30-80: 757 px), and applies sinusoidal shifts (antenna dx=2*sin(t),
elytra dx=1*sin(t+1.5)). The body (y>=80) remains bit-identical across all 8
frames. This produces 48-159 changed antenna pixels and 23-137 changed elytra
pixels per frame, with 0 body changes.

Export: 8 frames, 179 unique tiles, 97,376 bytes pixels+masks (vs 278,528
naive). The C++ compiles as C++17. Original 526 bytes are preserved in
`candidate-09/sources/`. No blink: Tentomon is an insect with fixed compound
eyes.

See the [pixel-art idle reference](https://www.slynyrd.com/blog/2018/8/19/pixelblog-8-intro-to-animation)
for small keyframe cycles, long holds and deliberate timing.

## Architecture

**External artwork + profile JSON -> deterministic asset compiler -> shared
C++ animation/render core -> native simulator or ESP32.**

Python prepares assets and hosts the viewer. It must not become a second
implementation of facial animation, typography or composition. Browser controls
send bounded preview inputs and display the native framebuffer. No LLM, gateway
or paid API is involved in editing, playback or tests.

One profile definition contains source paths/hashes, original canvas dimensions,
palette, authored frames/layers, anchors, replacement masks, frame durations and
state mappings. Shared scene settings define the 466x466 circle, frame, avatar
scale, effects, font and primary/secondary letter pulses. Do not duplicate these
settings for every Digimon.

## Artwork workflow

- Accept PNG frames plus a manifest first. Aseprite is an optional editor, not a required purchase or firmware dependency.
- Keep artwork, fonts, generated arrays and screenshots in the private asset repository or ignored build outputs. Keep tools, schemas and synthetic tests public.
- Author `base`, near/far eyes, mouth/beak and effects explicitly. Show the base with facial layers disabled to catch features that would remain underneath an open mouth.
- Use exclusive replacement groups: select one eye/mouth frame, not two overlapping variants. A layer with transparency does not automatically erase the old feature.
- Preserve the original canvas and frame offsets. Avoid independent per-frame trimming; if importing a trimmed atlas, restore its original-canvas placement from metadata.
- Do not automatically invent anatomy, redraw a beak or mirror a frame without a profile instruction. Missing frames require artwork, not a threshold or warp.
- Optionally import Aseprite sheet JSON with frame timing, tags and slices/pivots. Pin and test the supported format; reject missing placement metadata.

## Local review without token-heavy iteration

Build a single local review page with profile/state selection, play/pause,
single-frame stepping, 1x/2x zoom, circle/anchor/mask overlays and an A/B slider.
Select a frozen reference or a candidate. Native resolution is the default.

Edit positions, scale, colours, durations, blink intervals and letter motion
using controls backed by JSON. Save only the changed parameters. Changing a
timeline must not rebuild pixel arrays; changing one sprite invalidates only that
profile's asset cache. Cache by source, compiler-version and configuration hash.

Preview only the selected profile/state. GIF/video/contact-sheet export is
explicit, not automatic after every slider change. A normal edit/test cycle
prints a short pass/fail summary and a viewer URL, not full logs or ten images.
Performance targets must be measured; do not promise instant rebuilds in advance.

The user can inspect and adjust visuals locally without chat. Use the assistant
for tool bugs or concrete requests such as `biyomon: mouth anchor x -2`, not for
repeated whole-image regeneration. No subagent fan-out for routine asset tweaks.

## Tests and approval gates

1. Validate dimensions, paths, required states, palette/mask format, finite values, bounded timings and alpha conventions before replacing output.
2. Use fixed timestamps and a fixed blink seed. Verify replacement exclusivity, stable anchors and immutable pixels outside declared feature regions.
3. Check complete closure of both eye sockets, not merely changed iris pixels. Use profile-specific masks; flag surviving closed-feature pixels during an open-mouth frame.
4. Check pairwise frame-piece overlap, avatar/caption/effect separation, circular clipping, foreground ordering and the maximum number of animated letters.
5. Render checkpoints with the C++ core and compare candidate/reference images. Show diffs locally; do not automatically accept a new golden image because it passes geometry tests.
6. Require human visual approval for anatomy and motion. Technical tests cannot judge whether an eyelid or bill looks natural.

Keep selection separate from approval. Never overwrite a selected reference;
switch it using a small manifest update, preserving the old revision.

## Firmware handoff

Start with the existing `Bitmap` RGB565 plus row-padded MSB-first alpha masks,
and `Glyph` one-bit masks. Emit static C++ arrays plus bounded timeline/anchor
metadata. The existing habitat pose enum describes walking sprites; portrait
states need their own contract rather than silently reusing its indices.

Share frame/effect/font arrays across profiles; deduplicate identical bitmaps.
Prefer authored small facial layers over many duplicated full portraits. Report
payload, metadata, RAM, stack and actual linked image size. Consider indexed
packing only if measurements justify a new decoder. No PNG/GIF/OTF parsing on
the device, GPU dependency, or per-frame allocation.

Native preview and device must use the same C++ sampler and renderer. Test time
wrap, pause/reduced motion and state transitions. Treat `Processing` as a visual
alias until a real protocol requirement exists. `tap to speak` needs a separately
implemented input action; a caption alone does not provide voice interaction.

The AMOLED target has a 2,031,616-byte OTA app slot and the project's size check
requires 10% headroom. Passing desktop tests does not demonstrate ESP32 image
fit, timing, audio coexistence or physical display correctness.

## Delivery order

| Phase | Deliverable | Gate |
|---|---|---|
| 0, done | Restore the previous Biyomon reference; record selection; preserve rejected variant | Old snapshots still load and hashes match |
| 1, partial | Persistent private projects, validator and static asset compiler implemented; incremental/watch cache pending | Synthetic tests, deterministic exports and source reconstruction |
| 2 | Minimal C++ portrait timeline/renderer and a native browser review page | Same core as firmware; local frame stepping, JSON controls, A/B comparison |
| 3 | Authored eye/mouth fixes via the editor, one region/state at a time | Automated regression checks plus explicit visual approval |
| 4 | Static export and board build; measured size/performance report | OTA margin and physical tests, reported separately |

**Next integration scope: the native sampler/review page and incremental cache.**
The commands above exist; the interactive editor and firmware portrait UI do not.
No Hermes profile aggregation, gateway changes or ESP32 flashing is implied.

## Research references

- [Aseprite CLI](https://www.aseprite.org/docs/cli/): batch sheet/JSON export, tags, layers, slices and duplicate-frame merging.
- [Sprite sheets](https://www.aseprite.org/docs/sprite-sheet/): frame grids, selected layers and animation tags.
- [Slices](https://www.aseprite.org/docs/slices/): bounds and pivots for explicit placement.
- [Existing face tool](faces.md) and [simulator](simulator.md): reuse native interfaces and existing verification rather than another scene implementation.
- [Development checks](development.md) and [licensing notices](../THIRD_PARTY_NOTICES.md): maintain contributor credit, external-asset permissions and hardware limitations.
