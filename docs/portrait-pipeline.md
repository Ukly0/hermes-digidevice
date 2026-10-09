# Portrait Animation Pipeline Plan

## Status and decision

This is the implementation plan, not a working animation editor or new firmware
feature. Stop creating per-character scripts and regenerating ten GIFs for each
small change. Current scratch scripts under `/tmp/opencode` are experiments, not
the production toolchain.

Biyomon returns to the earlier `build/biyomon-caption-bounce` preview and
`build/biyomon-portraits-v3` layers. The rejected `biyomon-caption-fixed` variant
is preserved. `build/portrait-selection.json` records the selected snapshots and
hashes; `build/portrait-review.html` links to them without regenerating artwork.
Known eye/beak problems remain. Selection is not final visual approval. These
ignored files are temporary; migrate them into the private asset project before
cleaning `build/`.

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
| 1 | Move source/selected assets into the private project; schema, validator, cache and one asset compiler in the repository | Reproduce selected input assets without heuristic redrawing; synthetic tests |
| 2 | Minimal C++ portrait timeline/renderer and a native browser review page | Same core as firmware; local frame stepping, JSON controls, A/B comparison |
| 3 | Authored eye/mouth fixes via the editor, one region/state at a time | Automated regression checks plus explicit visual approval |
| 4 | Static export and board build; measured size/performance report | OTA margin and physical tests, reported separately |

**Next implementation scope: phase 1 only.** No new character redesigns,
Hermes profile aggregation or ESP32 flashing in that phase. The commands and UI
for the new tool will be defined during implementation; they do not exist yet.

## Research references

- [Aseprite CLI](https://www.aseprite.org/docs/cli/): batch sheet/JSON export, tags, layers, slices and duplicate-frame merging.
- [Sprite sheets](https://www.aseprite.org/docs/sprite-sheet/): frame grids, selected layers and animation tags.
- [Slices](https://www.aseprite.org/docs/slices/): bounds and pivots for explicit placement.
- [Existing face tool](faces.md) and [simulator](simulator.md): reuse native interfaces and existing verification rather than another scene implementation.
- [Development checks](development.md) and [licensing notices](../THIRD_PARTY_NOTICES.md): maintain contributor credit, external-asset permissions and hardware limitations.
