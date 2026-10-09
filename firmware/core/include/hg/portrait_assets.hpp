#pragma once

#include "hg/habitat_assets.hpp"

namespace hg::portrait_assets {

using habitat_assets::Bitmap;

struct TileRef { uint16_t x, y; const Bitmap* bitmap; };
// Full-canvas replacement: clear or restore the backdrop before drawing tiles.
// Omitted transparent tiles must not retain pixels from the previous frame.
struct Frame {
  uint16_t width, height;
  const TileRef* tiles;
  uint16_t count;
};
struct Step { const Frame* frame; uint16_t duration_ms; };
struct Clip { const Step* steps; uint16_t count; bool loop; };

}  // namespace hg::portrait_assets
