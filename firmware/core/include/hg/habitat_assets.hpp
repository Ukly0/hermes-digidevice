#pragma once

#include <cstddef>
#include <cstdint>

namespace hg::habitat_assets {

struct Bitmap {
  uint16_t width, height;
  const uint16_t* pixels;
  // Optional row-padded MSB-first opacity mask; nullptr means fully opaque.
  const uint8_t* mask;
};
struct Layer { Bitmap bitmap; uint16_t x, y; };
struct Glyph {
  uint16_t width, height, advance;
  int16_t x_offset, y_offset;
  const uint8_t* bits;
};
enum FontSize : size_t { Small, Large, FontCount };

// Resident order: Agumon, Gabumon, Biyomon, Tentomon, Palmon, Gomamon,
// Patamon, Gatomon. Each resident shares one registered crop across its poses.
enum Pose : size_t { IdleA, IdleB, Rest, Attention, WalkA, WalkB, MoveA, MoveB, PoseCount };
enum Icon : size_t { New, Question, Incident, Notice, IconCount };
enum EnvironmentLayer : size_t { Water, Shoreline, LayerCount };
const Bitmap* frame(size_t resident, size_t pose);
const Bitmap* background();
const Bitmap* icon(size_t index);
const Layer* layer(size_t index);
const Glyph* glyph(size_t font, unsigned char character);
uint16_t ascent(size_t font);
uint16_t line_height(size_t font);
bool available();

}  // namespace hg::habitat_assets
