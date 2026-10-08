#pragma once

#include <array>
#include <cstdint>
#include <string>
#include <string_view>

#include "hg/hal.hpp"
#include "hg/json.hpp"

namespace hg {

// Opt-in local habitat demo. Rendering and interaction run in the portable
// core; network events and live profile routing are intentionally not simulated.
class Habitat {
 public:
  enum class NoticeKind : uint8_t { Info, Question, Error };
  explicit Habitat(Display& display) : display_(display) {}
  void enable(uint32_t now);
  void disable() { enabled_ = false; }
  bool enabled() const { return enabled_; }
  bool tick(uint32_t now);
  void render();
  void tap(int x, int y);
  void back() { selected_ = -1; detail_ = false; dirty_ = full_ = true; }
  bool read();
  bool answer(bool yes);
  void details();
  bool notify(std::string_view name, NoticeKind kind = NoticeKind::Info);
  bool clock(int64_t epoch, int offset_minutes, uint32_t now);
  void connection(bool online);
  void pause() { paused_ = !paused_; dirty_ = full_ = true; }
  void motion();
  void invalidate() { dirty_ = full_ = true; }
  json::Value status() const;
  // Hand-authored sand area of the full-cover 466x466 beach composition.
  bool walkable(size_t resident, int x, int feet) const;

 private:
  struct Notice { NoticeKind kind = NoticeKind::Info; uint32_t id = 0; };
  struct Resident {
    // Q8 ground coordinates: the core moves subpixel positions, then rounds
    // them for the panel. No float state or random work in the renderer.
    int px = 0, py = 0, target_x = 0, target_y = 0;
    int direction = -1, remaining = 30, rest_age = 0, blocked = 0;
    int distance = 0, speed = 256, travel = 0;
    int vx = 0, vy = 0, face_votes = 0, face_hold = 0;
    int progress_timer = 20, progress_distance = 0, stalled = 0;
    int gait_hold = 0;
    uint32_t random = 1;
    bool resting = false, moving = false, stopping = false, sleeping = false;
    uint8_t pending = 0;
    std::array<Notice, 8> notices{};
    uint8_t head = 0;
    uint32_t fresh_until = 0, last_id = 0;
    uint8_t last_action = 0;  // none, reviewed, yes, no
  };
  struct Box { int left, top, width, height, percent; };
  int x(size_t i) const;
  int feet(size_t i) const;
  size_t pose(size_t i) const;
  Box box(size_t i) const;
  Box bubble(size_t i) const;
  Box new_marker(size_t i) const;
  void open(size_t i);
  void card_changed();
  void remove_notice(uint8_t action);
  std::array<size_t, 8> order() const;
  bool separated(size_t i, int px, int py, int prediction = 0) const;
  bool path_clear(size_t i, int px, int py) const;
  void settle(size_t i, bool sleep_allowed);
  void target(size_t i);
  void paint(int from, int to);
  bool update_clock(uint32_t now);
  Display& display_;
  std::array<Resident, 8> residents_{};
  uint32_t last_ = 0, frame_ = 0;
  uint32_t next_id_ = 1, card_at_ = 0;
  int selected_ = -1;
  bool enabled_ = false, paused_ = false, reduced_ = false;
  bool dirty_ = true, full_ = true;
  bool detail_ = false, question_ready_ = false;
  int painted_sky_ = 0;
  bool clock_known_ = false, hud_dirty_ = true, link_online_ = false;
  int64_t clock_epoch_ = 0, clock_minute_ = -1;
  uint32_t clock_at_ = 0;
  uint64_t clock_elapsed_ = 0;
  int clock_offset_ = 0;
  std::string clock_text_ = "--:--", clock_date_;
};

}  // namespace hg
