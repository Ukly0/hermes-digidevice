#include "hg/habitat_assets.hpp"

namespace hg::habitat_assets {
const Bitmap* frame(size_t, size_t) { return nullptr; }
const Bitmap* background() { return nullptr; }
const Bitmap* icon(size_t) { return nullptr; }
const Layer* layer(size_t) { return nullptr; }
const Glyph* glyph(size_t, unsigned char) { return nullptr; }
uint16_t ascent(size_t) { return 0; }
uint16_t line_height(size_t) { return 0; }
bool available() { return false; }
}  // namespace hg::habitat_assets
