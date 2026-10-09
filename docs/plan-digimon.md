# Digimon Habitat Plan

Working roadmap for Hermes Digidevice. This persists the decisions discussed
with the owner; it is not approval to deploy or restart the live fleet.

## Vision and confirmed scope

One shared habitat with eight independent Hermes profiles. Tap a resident to
open its profile, then navigate to domain features, history and schedules.
The eventual profile screen uses large portraits supplied separately by the
owner; the small sprites are for the habitat. Retain push-to-talk alongside touch.

| Resident | Domain and planned views |
|---|---|
| Gabumon (`default`) | Orchestration, Kanban and task dispatch |
| Agumon | Research, inbox-style reports |
| Biyomon | Mail and agenda, spoken summaries and voice replies |
| Tentomon | Development, code viewer |
| Palmon | Media, covers, library status and charts |
| Gatomon | Finance, expenses, portfolio and charts |
| Gomamon | Automation and workflow status |
| Patamon | Infrastructure, security and audit alerts |

Use mock data first. Inbox UI starts with Agumon; later connect Biyomon when
its real service is ready. Read-only cron views show schedules and results;
task history lives on the host. Notifications belong to their resident and
never steal focus from another profile. Opening a notification and marking it
read are separate actions.

## Asset audit

The external asset collection has twelve 64x64 PNGs per resident, complete
384x128 scenery, and additional transparent overlays. Keep all originals
unchanged. The public repository includes neither these pixels nor generated
previews. A private repository is storage, not permission to redistribute.

Earlier session claims about snow, coins, original animation timing, and
parallax were interpretations, not recovered game configuration. Numbered
images and duplicate files alone do not establish frame order or duration.
No firmware, scene script or authoritative gameplay metadata has been supplied.
Gatomon's open-mouth poses also mean the earlier "no mouth frame" claim should
not be relied on. Classifications in the private manifests remain provisional.

The first native demo uses the complete beach image to avoid uncertain layer order.
The current demo uses visually selected locomotion poses, not just translated
idle pictures. These are not verified original-game walk classifications or
timings. Water shimmer, movement timing,
rest and notification gestures are new prototype behavior. Foreground
parallax and environment transitions can follow a visual review.

## Architecture direction

Implemented first slice: `firmware/core/src/habitat.cpp` owns the resident
state machine, 20 Hz movement/animation, background rendering, hit-testing, pending
counts and profile cards. It uses the same `Display`/`Canvas` contracts on the
native simulator and ESP-IDF component. The mode is currently opt-in and
limited to a 466x466 round display. Scene pixels use the full panel, not the
old UI's inscribed square; text/cards remain inside safe circular bounds.
The beach panorama now covers the entire circular glass using an aspect-ratio
preserving center crop, with no letterbox bands. Sprites render at 150% of their
cropped source size (25% smaller than the first 200% prototype). They now roam
in X and Y across the sand rather than remaining in two lanes; farther residents
are slightly smaller (120% to 150%). Title, pending count and cards are small overlays on the scenery. This
cover framing intentionally trims the panorama's horizontal extremes.

- Keep rich charts and image processing on the host; send bounded display data.
- Keep resident movement and hit targets local for the eventual device home.
- Use external assets through an explicit path; do not ship them with firmware.
- Decide face storage, caching and flash budgets from measured assets, not an
  assumed fixed eight expressions times the existing mascot bitmap size.
- Profile switching and gateway routing still need integration design. Simply
  connecting only to the selected profile cannot receive background notices
  from the other seven. A host-side aggregator or equivalent routing is needed.
- Preserve sessions, permissions and existing cron delivery destinations. Do
  not replace Telegram delivery or restart gateways during UI prototyping.

## Delivery phases

### Monochrome portrait pilot

The large-face branch can prepare externally supplied expression frames using
the same 1-bit mask convention as the Hermes mascot. This is a monochrome trial,
not the final selected portrait format: one foreground color can be selected at
render time, and eyes/mouth remain negative space rather than a solid alpha
silhouette. The subsequent colour study below retains more character detail.

```bash
python -m hermes_gadget.portraits --inputs /path/to/idle.png /path/to/blink.png /path/to/talk.png --out build/portrait-pilot --sequence idle blink idle talk idle talk
```

All input PNGs must share the same source canvas/registration. Conversion fits
the entire canvas at 64, 96, 144 and 192 px without per-expression cropping.
It writes transparent warm-white PNGs, packed row-padded MSB-first `.bin` masks,
a manifest and a contact sheet on `#0D1D24`. `--sequence` optionally produces a
visual GIF; it is not driven by agent states. The output directory must be new.
Use `--threshold` to inspect how luminance separation preserves facial details;
transparent source pixels never contribute ink.

Three frames at those sizes use 26,592 bitmap bytes. Twelve use 106,368 bytes,
excluding metadata. No generated artwork belongs in the public repository.
The converter does not overwrite the shipped mascot. Per-profile mask loading,
effect anchors and native state-driven rendering still need integration.
Candidate roles are idle (rest), blink (periodic eye closure) and talk
(alternating open/closed mouth). Additional drawn expressions can support a
concerned visual state, but artwork alone does not establish an error/approval
semantic or original animation timing. Verify the appearance before assigning
any state; listening/thinking indicators can be native overlays as for Hermes.

### Limited-colour portrait study

The Gabumon visual study selects five flat colours (including the dark background)
and selective one-pixel material seams, rather than the earlier luminance-only
mask. Keep the source's warm skin, pale fur, blue stripes and eye distinct.
All original and adapted character pixels, effect sprites and frame sprites
remain external or in ignored `build/` previews. No new character artwork is
licensed under this repository's MIT license.

The animation study follows authored-keyframe techniques rather than pasting
rectangular eye/mouth pieces from differently posed portraits. Complete supplied
frames for neutral, squinted eyes, closed eyes, open mouth and open mouth with
closed eyes share a padded canvas and horn registration anchor. The small
changes in pose are retained; do not claim a perfectly stationary silhouette.
Source pixels must not be lost when applying registration offsets.

Later visual feedback selects stationary state bases for rest, thinking and
listening instead of those whole-frame pose swaps. Rest and listening share a
neutral base; thinking holds one squinted-eye base. Locally authored near/far
eyelid masks produce open/half-closed/closed phases without changing the muzzle,
horn, body, registration or source alpha. Validate all visible non-eye pixels
over the decoded animation, not only the source portrait bank. Animate the frame
behind the portrait so its corners cannot produce apparent motion by covering
the body. Listening uses the two supplied musical-note sprites, registered with
a common crop and recoloured to the portrait's gold. Speaking is not changed by
this stationary-state revision and still needs a properly authored mouth set.

Thinking uses the squinted-eye expression with a closed mouth, not merely the
neutral portrait plus a status icon. Supplied speech/thinking effects use a
common crop per sequence, a shared palette and the same integer pixel scale as
the portrait. Frame corners are enlarged as glyphs instead of magnifying empty
quadrants. Inspect expressions at native size and enlarged nearest-neighbour
size before approving playback. Technical palette/position checks are not
evidence that the anatomy looks right.

The supplied art lacks a genuinely half-open mouth keyframe. Do not fabricate
one by warping the muzzle or describe a two-mouth-frame loop as a three-frame
animation. A half-open drawing on the same registered template remains pending.
Preview timings and effect placements are design choices, not recovered game
logic, measured speech synchronization, or an ESP32 runtime implementation.
Earlier square mockups were not validated against circular panel clipping.
The subsequent high-resolution-frame study now composes exactly 466x466 pixels
inside a radius-232.5 panel mask. It removes the supplied frame's outer padding,
fits its maximum visible radius, removes small noise components, and preserves
the relief in three grayscale tones after downsampling. The avatar retains its
limited colour palette. Effects are the final foreground layer, above the frame,
with a black rim for contrast; their complete sequences stay inside the circle
and clear of the avatar. Check the decoded GIFs for out-of-circle pixels,
frame/avatar separation and non-eye motion, not only the initial screenshot.
This is host-side visual evidence, not physical screen or firmware validation.
Native state-driven portrait rendering remains a separate integration.

The latest layout returns to the four original 128px frame pieces rather than
the high-resolution relief frame. Their source canvases already overlap at the
diagonals; separate them symmetrically along their cardinal directions before
applying one common scale. Keep every original symbol pixel and validate all six
piece-pair intersections. A thin circular track, split into disjoint quarter
arcs, unifies the four sections around the panel centre without an elliptical
stretch. In the zero-padding study, the centred 314x314 square is completely free
of frame pixels and is occupied by the avatar canvas with zero added padding. Original
transparent corners remain transparent; zero padding does not mean filling
them or distorting the character. Foreground effects may obscure the frame,
but not the avatar, and must remain inside the physical-circle mask.

A separate speaking preview now uses this same square layout and the two
supplied speech-effect sprites. Register the open-mouth donor to the neutral
portrait's nose and limit changes to an explicitly selected lower-face mask;
do not swap the whole head pose. Blink masks remain independent. Verify decoded
frames outside both the mouth and eye masks for unintended motion. This is a
two-mouth-state visual loop (closed/open), not a half-open drawing or real
speech synchronization, and is still not integrated into the native core.

The subsequent caption study intentionally reduces the avatar to 256x256 at
`(105,88)` within the same four-piece frame, reserving a lower text band.
It uses externally supplied Pixel Digivolve at 24px with a shared baseline of
377. Idle shows `tap to speak`; the other visual labels are `Thinking`,
`Listening`, `Speaking` and an optional `Processing` alias of thinking.
Thinking/listening/processing offset each glyph vertically by an integer-rounded
sine wave, with 4px amplitude, an 1800ms period and a per-character phase shift.
Idle and speaking captions stay static. Keep glyph x positions fixed and measure
the complete wave envelope against frame, avatar and panel masks.
These labels are visual mockups: `tap to speak` does not implement a touch action,
and `Processing` is not a new protocol state. Glyph parsing/rasterization remains
host-side; 24px glyphs and caption state logic still need native integration.

The isolated-caption revision replaces the continuous sine wave with isolated,
sequential character pulses: one glyph uses offsets `0,-3,-6,-6,-3,0` over six
60ms steps, then the next glyph takes its turn. At most one character moves;
all others hold the shared baseline. Complete each word cycle before looping.
Thinking/processing text and the thin circular track use the portrait's blue;
idle/listening/speaking use its gold. The active character highlights in warm
white, while the original frame glyphs remain white. This keeps accents coherent
with the supplied effects without rainbow colours or additional artwork copies.
Validate character positions in decoded GIFs as well as animation metadata.

The later dynamic version uses a faster primary bounce with offsets
`0,-8,-12,-6,2,0` at 40ms per step (240ms per character), including a small
settling overshoot. A separated second character reacts with
`0,0,0,-3,-6,-2`, staggered behind the primary jump. At most two characters move;
the rest hold the baseline. Preserve the avatar/effect timing on its original
60ms clock rather than accelerating it with the text. Both active glyphs use
the warm-white highlight; state accents and static idle/speaking captions stay
unchanged. Recheck the larger jump envelope against the avatar and frame.

For further portrait work, follow the [animation pipeline plan](portrait-pipeline.md)
instead of continuing per-character scratch scripts. The user selected the
earlier `biyomon-caption-bounce` reference and rejected `biyomon-caption-fixed`;
both snapshots remain available. Selection does not resolve the known eye/beak
issues or constitute visual approval of the rejected correction.

The Biyomon portrait pilot uses the same 466px composition, 256px avatar,
Pixel Digivolve captions and two-character bounce timing. Its external 128px
source frames are 510..521, paired left/right across six expressions. A separate
pink/coral/blue/turquoise palette preserves plumage, beak and eyes instead of
reusing Gabumon's colour classification. Author Biyomon-specific near/far eye
masks; never reuse Gabumon's horn, iris or jaw geometry. The initial shifted
beak-donor approach left mismatched contours. An attempted correction used traced bill
layers: remove the old bill before drawing either the closed or open shape.
Both bill halves use the same coral fill with black outline/cavity, without a
second shaded bill or pink tongue. The far-eye mask must cover its whole white
socket, not merely the few turquoise iris pixels. Check complete disappearance
of white/blue eye pixels in both eye regions on closure, and verify that the
open composite contains no remaining closed-bill fill beneath it.
Pink accents serve idle/listening/speech;
turquoise accents serve thinking/processing. Refit foreground effects against
the crest and beak, and validate the decoded letter motion and non-expression
pixels in both profiles. This remains asset/interaction preview work, not live
profile switching, gateway integration or hardware evidence.

References for techniques only; no code or artwork is copied from these projects:

- [SLYNYRD: Intro to Animation](https://www.slynyrd.com/blog/2018/8/19/pixelblog-8-intro-to-animation): clear keyframes, coherent pixel clusters and deliberate frame duration.
- [Fire Emblem portrait alignment discussion](https://feuniverse.us/t/smiling-frame-misalignment/4975/7): authored frames need a common grid; adjusting coordinates alone may not fix mismatched artwork.
- [FE8 face implementation study](https://github.com/FireEmblemUniverse/fireemblem8u/blob/master/src/face.c): independently controlled mouth and blink sequences with explicit feature positions.
- [Ren'Py layered images](https://www.renpy.org/doc/html/layeredimage.html): independently selectable expression groups; proper authored layers, not arbitrary donor-image patches.

### Roadmap

1. Native firmware UX skeleton: eight residents walking/resting, animated
   environment, tap selection and simulated pending notifications. The browser
   forwards touch and displays the simulator's 466x466 framebuffer. Reproducible
   PNG/GIF exports use that same core; no live Hermes access.
2. Profile identity: owner-supplied portraits, expressions and navigation.
3. Host integration: aggregate profile state and notifications, read-only cron,
   per-profile task history, authentication and reconnect/resync behavior.
4. Domain views: charts, code, media, finance, mail, Kanban, infra and workflows.
5. Device port: measured rendering, asset memory, touch targets, audio and
   physical board verification. Desktop success does not verify an ESP32 port.

## Run the UX skeleton

Install the existing image extra in your activated environment:

```bash
python -m pip install -e '.[images,dev]'
python -m hermes_gadget.habitat --assets /path/to/digimon-assets
```

From an editable checkout, startup converts external PNGs and builds a dedicated native library under
`build/habitat/`. CMake and a C++17 compiler are required. Pillow is used only
for asset conversion and PNG/GIF encoding, not scene composition. There is no
Tk requirement. The default library under `build/host/` is not overwritten.

For the configured local demo use `--timezone Europe/Madrid`; standalone runs
default to UTC. The viewer synchronizes real Unix time and the zone's current
UTC offset into the native core at startup and every thirty seconds, including
DST offset changes. Time is not drawn by the browser, nor inferred from uptime.

Open `http://127.0.0.1:8770/`. One automatic mock notice arrives after six seconds,
driven by the C++ core even when no browser is polling. Add further examples
with **Send demo notice**; the unattended demo does not flood all eight residents.
Tap a sprite or its bubble to inspect its native card. **READ** acknowledges one
information notice, **REVIEW** marks one incident as seen (not fixed), and
questions require explicit **YES/NO**. **BACK** or a downward swipe returns
home. Opening a card does not clear pending notices. Pausing and reduced-motion
controls help examine poses. The browser controls below the panel are developer
tools that send whitelisted inputs, not device UI or live agent actions.

Headless previews, saved outside tracked assets:

```bash
python -m hermes_gadget.habitat --assets /path/to/digimon-assets --preview /tmp/habitat.png --seconds 12
python -m hermes_gadget.habitat --assets /path/to/digimon-assets --preview /tmp/habitat.gif --seconds 12
```

The server binds only to loopback by default and exposes no arbitrary file
paths or unrestricted console commands. Keep this binding when using Tailscale
Serve. This is a shared demo session, not a multi-user application.

For an already built library, add
`--library /absolute/path/build/habitat/libhgsim.so` to skip generation/build.
On Windows use the built `hgsim.dll`; on macOS use `libhgsim.dylib`.
An installed package without the firmware checkout needs this explicit library.

For a headless host, Tailscale Serve can proxy the loopback service privately
over HTTPS (not Funnel). Supply its exact URL to allow browser actions:

```bash
python -m hermes_gadget.habitat --assets /path/to/digimon-assets --allowed-origin https://host.tailnet.ts.net:8443
tailscale serve --bg --https=8443 http://127.0.0.1:8770
```

Open `https://host.tailnet.ts.net:8443/` from a device on the same
tailnet. This demo has shared in-memory state across visitors; tailnet access
rules are its access boundary, not separate per-user login. Stop only this
proxy with `tailscale serve --https=8443 off`; do not reset unrelated services.

For direct diagnostic access, `--host <tailscale-ip>` can bind a tailnet interface
instead. This does not also bind loopback, so adapt the proxy target if needed.
Avoid `--host 0.0.0.0`: it exposes all IPv4 interfaces and is not necessary for
normal use. HTTPS Serve needs its certificate name, not a bare IP URL.

This viewer **does** run the portable firmware core via the existing simulator,
with the round panel profile and native `TouchGestures`. It is not CPU emulation
of an ESP32, nor evidence of real panel speed, power, Wi-Fi or audio behavior.
The viewer starts with simulated Wi-Fi down and enables the local habitat mode;
there are no real Hermes agents attached. Data/acknowledgements are mock and
in-memory; restarting resets them. While this opt-in demo is shown, touch is
reserved for habitat selection rather than push-to-talk. `habitat off` restores
the ordinary UI and voice controls.

## Native core commands and assets

The following commands work through the simulator console or the board serial
console. Do not expose unrestricted console access to a network client.

| Command | Effect |
|---|---|
| `habitat on` / `habitat off` | Enter the local demo / return to normal UI |
| `habitat status` | Native resident state, clock and pixel coordinates |
| `habitat clock {"epoch":1791496799,"offset":120}` | Sync real Unix seconds and UTC offset minutes |
| `habitat notify palmon [info\|question\|error]` | Add a typed mock notice; omitted kind is information |
| `habitat read` / `habitat back` | Review one information/incident notice / return home |
| `habitat yes` / `habitat no` | Record an explicit local answer to the current question |
| `habitat details` | Toggle the selected notice's local detail view |
| `habitat pause` / `habitat motion` | Toggle pause / reduced motion |

No habitat state is stored in NVS. Pairing, Wi-Fi, identity and session reset
commands are unchanged. Pairing prompts, active turns, overlays and OTA can
take priority; entering the demo during an active interaction is rejected.

The asset compiler exports eight registered poses per resident (source offsets
0, 1, 7, 6, 2, 3, 4, 5): idle A/B, rest, attention, upright steps A/B and
more extended movement A/B. Each resident's poses share the same crop from
their original 64x64 canvas, preventing body jumps when a frame changes.
The data uses RGB565 color and row-padded one-bit opacity masks, plus the complete
beach background, four notification icons and two cropped ambient overlays.
The current private set is 400,734 payload bytes (including font glyph masks), excluding
bitmap metadata. It does not embed all twelve frames or claim the poses are
verified original-game animation sequences.

## Notification interaction

The home is scenery-first: the welcome title/hint disappear after three seconds,
and no global counter covers the landscape. Information uses the owner's white
speech bubble with `!`; a question uses the blue question mark; an incident uses
the bandage bubble. `NEW` appears for three seconds after a new arrival, then
the unread cue remains. Reduced motion leaves cues visible without animation.
Simultaneous bubbles are placed apart inside the circle with small owner links
when displaced; touch picking gives these foreground cues priority over sprites.

Each resident has a bounded eight-item FIFO inbox. A new notice cannot replace
an unanswered question; a full inbox rejects the addition. The card shows the
current type, summary and remaining count. Tapping the message reveals the local
demo detail line without acknowledging anything. Reading advances one item only.
Questions cannot be dismissed with READ; YES/NO record a response and its notice
ID locally. The answer buttons arm after 350 ms of wall time, including while
the demo is paused. A new question arms again after advancing the inbox, so a
rapid follow-through tap cannot silently approve it. Incidents are merely reviewed;
no repair or financial/mail action is performed.

The external checkout must contain `icons/source/7_0_0.png` (NEW),
`16_0_0.png` (question), `17_0_0.png` (bandage) and `17_1_0.png` (information
bubble). These are the verified filenames of the supplied attachments. The slot
graphics are retained privately but are not invented progress/health meters.
All pixels stay outside this public repository; default builds draw original
geometric cue stand-ins.

## Home clock and Pixel Digivolve

The native home adds a small, outlined **HH:MM** clock and weekday/date over the
sky, leaving the circular landscape visible. A pending count appears only when
there are unread notices. The green/amber dot reflects the device core's actual
paired Hermes connection, not browser/Tailscale reachability: this offline mock
demo shows amber. No fabricated battery or weather data is displayed.

Without synchronization the core shows `--:--` and `NO SYNC`; it does not turn
elapsed uptime into a pretend clock. Clock/date continue during decorative
pause or reduced motion. The clock extrapolates from explicit Unix seconds and
offset using monotonic milliseconds and handles midnight, leap years and millis
wrap, including multiple wraps without resynchronization, provided app ticks are
less than 49.7 days apart. Synchronization while the habitat is off uses the
current uptime; clock advancement continues while off. The viewer resynchronizes
periodically; its `images` extra supplies IANA timezone data even on hosts without
a system database. A physical ESP32 still needs a
trusted host/SNTP/RTC time source and timezone updates wired into this input.
There is no physical RTC or SNTP implementation claimed by this prototype.

Pixel Digivolve Regular is loaded from
`fonts/pixel-digivolve/Pixel Digivolve.otf` in the external asset directory.
The host compiler rasterizes ASCII at 18 and 32 px into baseline-registered
one-bit glyph masks. Clock/date, profile headings and action buttons use them;
small body text keeps the existing readable font. No OTF parser or FreeType
runs on the ESP32. Default builds without private assets use the existing font.
The glyph masks add 7,867 bytes of flash payload, plus metadata. Clock changes
refresh a small header band, once per minute, rather than invalidating every
frame. Typed notice cues reserve the header region so they cannot hide the clock.

The author archive's license is personal/non-commercial with software embedding
permission, not blanket MIT/OFL/free-commercial permission. Keep font/license
externally and obtain a commercial license before selling or commercially
deploying the device. See [Third-party notices](../THIRD_PARTY_NOTICES.md).

## Ambient animation and resource budget

The original beach layers are spatial overlays, not recovered animation frames.
The asset compiler requires `environments/beach-island/layer_water.png` and
`layer_sand_sea.png` as 384x128 RGBA canvases. It exports a registered 384x20
water crop at `(0,108)` and a 384x14 shoreline crop at `(0,94)`. Shore opacity
includes only nontransparent pixels whose RGB differs from the immutable base.
The additional RGB565/mask payload is 27,744 bytes.

The core restores from the base and composes a newly authored, 5 Hz tide/foam
cycle, while resident movement remains at 20 Hz. Shore writes start at source
row 97, below the walkable sand ending at source row 96. Thus the hut, rocks,
palms and walking ground never slide with the water. Wave opacity falls to zero
at its sampling reset rather than jumping visibly to the first position.

There is no independent cloud or palm layer in this beach artwork. The ambient
sky effect is a very slow horizontal drift of flattened sky/cloud pixels in
source rows 0..19, tapered to zero at the lower boundary. No pixels from trees
or buildings are sampled. Vegetation remains static rather than inventing an
unsupported separation. Pausing freezes ambient motion; reduced motion restores
the static environment and residents while retaining readable cues.

The slow sky band is repainted separately, not by making every movement update
full-screen. Source X coordinates are cached once per band (932 bytes on the
stack); there is no second framebuffer, runtime PNG decoder or RGBA scene copy.
All rendering still runs through the portable core.

| Resource | Current evidence |
|---|---|
| Immutable asset arrays | 400,734 bytes including glyph masks; compiled flash data, metadata excluded |
| RGB565 framebuffer | 434,312 bytes in PSRAM, unchanged |
| Existing DMA bounce buffer | 14,912 bytes internal DMA memory, unchanged |
| Habitat object | 1,384 bytes on the measured desktop ABI before the clock/HUD additions; current and ESP32 sizes unmeasured |
| Source-column cache | 932 bytes of temporary stack per band |
| Average pixel transfer demand | Before clock/HUD: about 6.00 MB/s at 20 movement updates/s, including rounded row bands |
| Configured QSPI | 40 MHz, four lanes: ideal 20 MB/s before protocol/copy/DMA overhead |
| OTA app slot | 2,031,616 bytes; the size check also requires 10% free |

A native desktop benchmark before the clock/HUD additions, with real private
assets, fake display and 180 seconds
of simulated time measured average render CPU at 2.55 ms (P95 3.38 ms), versus
1.92 ms before ambient effects. The linked core was not optimized in that run.
These are Intel desktop timings, not ESP32 timings. Panel bytes rose only 1.14%
because sky updates use their own narrow band. At the configured ideal QSPI rate,
pixels alone use about 30% of link capacity; physical flush latency is higher.

The 1.75 board configuration documents 8 MB octal PSRAM, 16 MB flash and 240 MHz
CPU, so asset/RAM quantities are plausible, but physical flash size does not
enlarge the OTA app slots. No ESP32 performance or firmware-size guarantee is
made. Measure render/flush latency, stack headroom, audio/Wi-Fi coexistence,
power and final firmware image size on the exact board. If necessary, reduce
display update rate before reducing physics responsiveness or adding buffers.

## Free movement and gait

Movement remains in the portable C++ core. Eight scattered starting points are
not fixed zones: each resident chooses independent targets throughout the
hand-authored sand area (feet at y=270..350 in the full-cover 466x466 scene).
Targets exclude the shoreline/cabin and require the whole pose/badge to remain
inside the circular glass. Q8 subpixel ground coordinates make slow movement
smooth without floating-point simulation state.

Nearby destinations (24..100 pixels) have their route checked in bounded
segments, instead of picking clear endpoints across an obstructed beach. Oval
support footprints (50x34 pixels before subpixel rounding) let residents cross
at different depths; they are not the heights of the sprite billboards.
Acceleration and braking are gradual. Peers' velocities are checked about
400 ms ahead, with direct or axis-aligned progress only: opposing perpendicular
escape steps were removed because they produced rapid left/right oscillation.
A stalled resident waits briefly and picks another route rather than teleporting.
On arrival, residents stand and occasionally take a longer sleeping rest;
collision waits do not automatically become sleep. Pending or selected residents
hold their position; others continue moving. Depth order follows ground Y,
and hit-testing checks visible foreground pixels before padded fallback targets.

Gaits advance with actual distance travelled, not a shared wall-clock phase;
blocked sprites do not keep cycling their legs. Agumon, Gabumon, Biyomon,
Tentomon, Palmon and Gomamon use source 4/5: the grounded strides or seal-like
scooting selected from the supplied art. Patamon and Gatomon use the gentler
upright source 2/3 pair. Small gait-linked bobbing is omitted for Gomamon.
Source 8 (attack) and 11 (back view) are not locomotion substitutes. A 300 ms
walking-pose hold avoids idle/walk flashing during small speed corrections;
it does not advance the foot phase without travel. Sprite facing ignores tiny
near-vertical corrections and requires a sustained opposite heading, with an
800 ms minimum between facing changes. Rested departures can turn deliberately
before accelerating. The viewer polls up to 20 fps, subject to actual transfer
and encoding time; GIF preview export remains sampled at 10 fps.

```bash
python -m hermes_gadget.habitat_assets --assets /path/to/digimon-assets --out /tmp/habitat_assets.cpp
cmake -S firmware -B build/habitat -DHG_HABITAT_ASSETS_SOURCE=/tmp/habitat_assets.cpp
cmake --build build/habitat
```

Without `HG_HABITAT_ASSETS_SOURCE`, the core compiles with geometric stand-ins,
so CI needs no third-party pixels. Generated source, libraries, screenshots and
GIFs with private art must stay outside git and public release packages. The
same source option is supported by the ESP-IDF core component, but an ESP32
build/physical report is still required before claiming device validation.

## Verification and remaining decisions

Build the default simulator with `hermes-gadget build-sim --test`, then run
`pytest tests/test_habitat.py tests/test_habitat_assets.py`. Converter tests use
synthetic artwork; native integration tests use the built default placeholder
library. Set `HERMES_HABITAT_LIBRARY` to test a custom generated library.
Verify browser touch, in-display READ/BACK, notice persistence, pause and
reduced motion with real assets locally. The site keeps this page in navigation
and search. The previous independent Python scene has been replaced, not kept
as a competing implementation.

Before device implementation, choose the physical panel and agree the final
portrait format, memory budget, aggregator interface and touch navigation.
Three minutes of deterministic core simulation verify land bounds, ground
clearance, limited per-tick movement, independent X/Y travel and depth order.
Additional checks cover 50 ms ticks, bounded velocity, smooth departure,
facing-change intervals, walking-pose stability, ambient pause/reduced motion,
fixed scenery and full-vs-multiband recomposition. A fixed-seed native
diagnostic with the current private assets reduced rapid within-bout horizontal
reversals from 1,986 to zero and facing flips from 2,283 to 67 in three minutes.
These counts are simulation evidence, not a hardware or all-scenario guarantee.
This is new habitat behavior, not recovered movement rules from the original game.
