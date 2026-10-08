#include "hg/habitat.hpp"

#include <algorithm>
#include <cstdlib>
#include <cstdio>
#include <string>

#include "hg/canvas.hpp"
#include "hg/habitat_assets.hpp"

namespace hg {
namespace {
constexpr const char* kNames[] = {"agumon", "gabumon", "biyomon", "tentomon",
                                 "palmon", "gomamon", "patamon", "gatomon"};
constexpr const char* kRoles[] = {"Research", "Orchestration", "Mail / agenda", "Development",
                                 "Media", "Automation", "Infrastructure", "Finance"};
constexpr const char* kSummaries[] = {
    "Research report ready.", "Two tasks ready for review.", "New mail needs a reply.",
    "Tests completed. Review results.", "The Incredibles: import complete.",
    "Workflow completed.", "Security audit ready for review.", "Expense report ready."};
constexpr const char* kQuestions[] = {
    "Continue this research task?", "Approve the suggested plan?", "Approve sending this draft?",
    "Approve the proposed change?", "Approve this media request?", "Run the suggested workflow?",
    "Approve the suggested check?", "Approve the suggested update?"};
constexpr const char* kErrors[] = {
    "Research task failed. Review details.", "Task dispatch failed. Review details.",
    "Mail sync failed. Review details.", "Tests failed. Review the results.",
    "Cruella: import failed.", "Workflow failed. Review details.",
    "A check failed. Review details.", "Finance sync failed. Check the data."};

const char* kind_name(Habitat::NoticeKind kind) {
  return kind == Habitat::NoticeKind::Question ? "question" : kind == Habitat::NoticeKind::Error ? "error" : "info";
}
const char* summary(size_t resident, Habitat::NoticeKind kind) {
  return kind == Habitat::NoticeKind::Question ? kQuestions[resident] :
         kind == Habitat::NoticeKind::Error ? kErrors[resident] : kSummaries[resident];
}
size_t kind_icon(Habitat::NoticeKind kind) {
  return kind == Habitat::NoticeKind::Question ? habitat_assets::Question :
         kind == Habitat::NoticeKind::Error ? habitat_assets::Incident : habitat_assets::Notice;
}
constexpr uint16_t kDark = rgb565(13, 29, 36), kText = rgb565(227, 245, 234);
constexpr uint16_t kGold = rgb565(255, 223, 130), kSea = rgb565(80, 178, 211);
constexpr int kFixed = 256, kSandTop = 270, kSandBottom = 350;
// Ground support footprints, not billboard heights: residents must be able
// to pass at a different depth within the 80-pixel strip of sand.
constexpr int kClearX = 50, kClearY = 34;
constexpr int kStepMs = 50, kAcceleration = 32, kPrediction = 8;

int triangle(uint32_t age, int period) {
  int phase = static_cast<int>(age % static_cast<uint32_t>(period));
  return phase <= period / 2 ? phase : period - phase;
}
int sky_offset(uint32_t frame, bool reduced) {
  constexpr int drift[] = {0, 1, 2, 3, 4, 3, 2, 1, 0, -1, -2, -3, -4, -3, -2, -1};
  return reduced ? 0 : drift[(frame / 20) % 16];
}
uint16_t mix565(uint16_t base, uint16_t overlay, int amount) {
  int inverse = 16 - amount;
  int r = (((base >> 11) * inverse + (overlay >> 11) * amount + 8) >> 4);
  int g = ((((base >> 5) & 63) * inverse + ((overlay >> 5) & 63) * amount + 8) >> 4);
  int b = (((base & 31) * inverse + (overlay & 31) * amount + 8) >> 4);
  return static_cast<uint16_t>((r << 11) | (g << 5) | b);
}

uint32_t roll(uint32_t& state) {
  state = state * 1664525u + 1013904223u;
  return state >> 8;
}
int pixel(int position) { return (position + kFixed / 2) / kFixed; }
int norm(int dx, int dy) {
  return std::max(std::abs(dx), std::abs(dy)) + std::min(std::abs(dx), std::abs(dy)) / 2;
}
int approach(int value, int goal) {
  return value + std::max(-kAcceleration, std::min(kAcceleration, goal - value));
}
int sprite_percent(int feet) {
  return 120 + std::max(0, std::min(80, feet - kSandTop)) * 30 / 80;
}

void bitmap(Canvas& c, const habitat_assets::Bitmap* image, int left, int top,
            int percent, bool mirrored) {
  if (!image) return;
  const int width = std::max(1, image->width * percent / 100);
  const int height = std::max(1, image->height * percent / 100);
  for (int y = 0; y < height; ++y) {
    int sy = y * image->height / height;
    for (int x = 0; x < width; ++x) {
      int sx = x * image->width / width;
      if (mirrored) sx = image->width - sx - 1;
      if (image->mask && !(image->mask[sy * ((image->width + 7) / 8) + sx / 8] & (0x80 >> (sx % 8)))) continue;
      c.pixel(left + x, top + y, image->pixels[sy * image->width + sx]);
    }
  }
}
void centered(Canvas& c, int y, std::string_view text, int scale, uint16_t color) {
  c.text((c.width() - Canvas::text_width(text, scale)) / 2, y, text, scale, color);
}
int face_width(std::string_view text, size_t size) {
  int width = 0;
  for (unsigned char ch : text) {
    if (const auto* g = habitat_assets::glyph(size, ch)) width += g->advance;
    else width += 6 * (size == habitat_assets::Large ? 3 : 2);
  }
  return width;
}
void face_text(Canvas& c, int x, int y, std::string_view text, size_t size, uint16_t color) {
  for (unsigned char ch : text) {
    if (const auto* g = habitat_assets::glyph(size, ch)) {
      if (g->bits && g->width && g->height)
        c.bitmap1(x + g->x_offset, y + habitat_assets::ascent(size) + g->y_offset,
                  g->width, g->height, g->bits, color);
      x += g->advance;
    } else {
      x = c.text(x, y, std::string(1, static_cast<char>(ch)), size == habitat_assets::Large ? 3 : 2, color);
    }
  }
}
void home_text(Canvas& c, int y, std::string_view text, size_t size) {
  int x = (c.width() - face_width(text, size)) / 2;
  // One-pixel outline reads over bright clouds without putting a dark bar
  // across the landscape. Glyphs are compiled masks, not runtime OTF drawing.
  face_text(c, x - 1, y, text, size, kDark);
  face_text(c, x + 1, y, text, size, kDark);
  face_text(c, x, y - 1, text, size, kDark);
  face_text(c, x, y + 1, text, size, kDark);
  face_text(c, x, y, text, size, kText);
}
}  // namespace

void Habitat::enable(uint32_t now) {
  enabled_ = true;
  last_ = now;
  frame_ = 0;
  selected_ = -1;
  next_id_ = 1;
  detail_ = question_ready_ = false;
  card_at_ = now;
  painted_sky_ = 0;
  clock_minute_ = -1;
  hud_dirty_ = true;
  update_clock(now);
  paused_ = reduced_ = false;
  // Scattered starting points, not lanes. All later destinations are picked
  // independently from the sand area; these points are not movement limits.
  constexpr int spawn[8][2] = {{104, 284}, {187, 303}, {319, 276}, {376, 310},
                               {92, 332}, {248, 339}, {347, 350}, {159, 345}};
  for (size_t i = 0; i < residents_.size(); ++i) {
    residents_[i] = Resident{};
    residents_[i].px = spawn[i][0] * kFixed;
    residents_[i].py = spawn[i][1] * kFixed;
    residents_[i].target_x = residents_[i].px;
    residents_[i].target_y = residents_[i].py;
    residents_[i].random = 0x6d2b79f5u + static_cast<uint32_t>(i) * 0x9e3779b9u;
    residents_[i].speed = 176 + static_cast<int>(i % 4) * 16;
    residents_[i].resting = i % 3 == 0;
    residents_[i].sleeping = residents_[i].resting;
    residents_[i].rest_age = residents_[i].resting ? 50 : 0;
    residents_[i].remaining = 16 + static_cast<int>(i) * 9;
    residents_[i].direction = i % 2 ? 1 : -1;
  }
  for (size_t i = 0; i < residents_.size(); ++i) if (!residents_[i].resting) target(i);
  invalidate();
}

bool Habitat::clock(int64_t epoch, int offset_minutes, uint32_t now) {
  if (epoch < 946684800LL || epoch >= 4102444800LL || offset_minutes < -840 || offset_minutes > 840) return false;
  clock_epoch_ = epoch;
  clock_offset_ = offset_minutes;
  clock_at_ = now;
  clock_elapsed_ = 0;
  clock_known_ = true;
  update_clock(now);
  return true;
}

void Habitat::connection(bool online) {
  if (link_online_ == online) return;
  link_online_ = online;
  hud_dirty_ = dirty_ = true;
}

bool Habitat::update_clock(uint32_t now) {
  if (!clock_known_) return false;
  // Rebase each app tick, including while disabled, so successive millis wraps
  // do not discard elapsed days. App ticks must be less than one wrap apart.
  clock_elapsed_ += static_cast<uint32_t>(now - clock_at_);
  clock_at_ = now;
  int64_t local = clock_epoch_ + static_cast<int64_t>(clock_elapsed_ / 1000) + clock_offset_ * 60;
  int64_t minute = local / 60;
  if (minute == clock_minute_) return false;
  clock_minute_ = minute;
  char text[16];
  std::snprintf(text, sizeof(text), "%02d:%02d", static_cast<int>(local / 3600 % 24), static_cast<int>(local / 60 % 60));
  clock_text_ = text;
  int days = static_cast<int>(local / 86400), weekday = (days + 4) % 7, year = 1970;
  auto leap = [](int y) { return y % 4 == 0 && (y % 100 != 0 || y % 400 == 0); };
  while (days >= (leap(year) ? 366 : 365)) { days -= leap(year) ? 366 : 365; ++year; }
  constexpr int month_days[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  int month = 0;
  while (days >= month_days[month] + (month == 1 && leap(year) ? 1 : 0)) {
    days -= month_days[month] + (month == 1 && leap(year) ? 1 : 0); ++month;
  }
  constexpr const char* weekdays[] = {"DOM", "LUN", "MAR", "MIE", "JUE", "VIE", "SAB"};
  constexpr const char* months[] = {"ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"};
  std::snprintf(text, sizeof(text), "%s %02d %s", weekdays[weekday], days + 1, months[month]);
  clock_date_ = text;
  hud_dirty_ = dirty_ = true;
  return true;
}

int Habitat::x(size_t i) const {
  return pixel(residents_[i].px);
}
int Habitat::feet(size_t i) const {
  return pixel(residents_[i].py);
}
size_t Habitat::pose(size_t i) const {
  const auto& r = residents_[i];
  using namespace habitat_assets;
  if (reduced_) return IdleA;
  if (r.pending) {
    auto kind = r.notices[r.head].kind;
    if (kind == NoticeKind::Error) return IdleA;  // Incident is a task state, not injury/sleep.
    if (frame_ < r.fresh_until && kind == NoticeKind::Info)
      return ((frame_ + i * 6) / 8) % 2 ? Attention : IdleA;
    return (frame_ + i * 11) % 80 < 12 ? Attention : IdleA;
  }
  if (selected_ == static_cast<int>(i)) return IdleA;
  if (r.resting) return r.sleeping && r.rest_age >= 50 ? Rest : ((frame_ + i * 14) / 24) % 2;
  if (!r.gait_hold) return IdleA;
  // Grounded strides/scooting for the first six; gentle upright paw/ear
  // motion for Patamon and Gatomon. No attack poses are used as walking.
  const size_t first = i >= 6 ? WalkA : MoveA;
  return first + static_cast<size_t>(r.distance / (4 * kFixed) % 2);
}

Habitat::Box Habitat::box(size_t i) const {
  const auto* art = habitat_assets::frame(i, pose(i));
  int percent = sprite_percent(feet(i));
  int width = std::max(1, (art ? art->width : 24) * percent / 100);
  int height = std::max(1, (art ? art->height : 24) * percent / 100);
  const auto& r = residents_[i];
  int phase = r.distance / (2 * kFixed) % 4;
  int bob = r.gait_hold && !r.pending && !r.resting && !reduced_ && selected_ != static_cast<int>(i) &&
      i != 5 && (phase == 1 || phase == 2) ? -1 : 0;
  return {x(i) - width / 2, feet(i) - height + bob, width, height, percent};
}

Habitat::Box Habitat::bubble(size_t i) const {
  auto anchor = [this](size_t owner) {
    Box actor = box(owner);
    auto kind = residents_[owner].notices[residents_[owner].head].kind;
    const auto* art = habitat_assets::icon(kind_icon(kind));
    int percent = art ? std::min(100, 3200 / std::max(art->width, art->height)) : 100;
    int width = art ? std::max(1, art->width * percent / 100) : 30;
    int height = art ? std::max(1, art->height * percent / 100) : 28;
    int head = actor.left + actor.width * (residents_[owner].direction > 0 ? 2 : 1) / 3;
    return Box{head - width / 2, actor.top - height - 4, width, height, percent};
  };
  if (!residents_[i].pending) return anchor(i);
  std::array<Box, 8> placed{}, occupied{};
  std::array<bool, 8> active{};
  const auto info = display_.info();
  // Keep simultaneously visible cues apart, including the temporary NEW tags.
  // Deterministic offsets avoid a hidden rear cue selecting a different inbox.
  constexpr int offsets[] = {0, -36, 36, -72, 72, -108, 108};
  for (size_t owner : order()) {
    if (!residents_[owner].pending) continue;
    Box original = anchor(owner), chosen = original, area{};
    bool found = false;
    for (int row : {0, -36}) {
      for (int offset : offsets) {
        Box candidate = original;
        candidate.left += offset;
        candidate.top += row;
        int extra = frame_ < residents_[owner].fresh_until ? 17 : 0;
        Box bounds{candidate.left - 5, candidate.top - extra - 5,
                   candidate.width + 12, candidate.height + extra + 12, 100};
        bool fits = true;
        for (int x : {bounds.left, bounds.left + bounds.width})
          for (int y : {bounds.top, bounds.top + bounds.height}) {
            int dx = x - info.width / 2, dy = y - info.height / 2;
            if (dx * dx + dy * dy > (info.height / 2 - 2) * (info.height / 2 - 2)) fits = false;
          }
        if (bounds.top < 130) fits = false;  // Home clock/date remains readable.
        for (size_t other = 0; other < active.size(); ++other) {
          if (!active[other]) continue;
          const Box& b = occupied[other];
          if (bounds.left < b.left + b.width && bounds.left + bounds.width > b.left &&
              bounds.top < b.top + b.height && bounds.top + bounds.height > b.top) fits = false;
        }
        if (fits) { chosen = candidate; area = bounds; found = true; break; }
      }
      if (found) break;
    }
    placed[owner] = chosen;
    occupied[owner] = found ? area : Box{chosen.left - 5, chosen.top - 22, chosen.width + 12, chosen.height + 34, 100};
    active[owner] = true;
  }
  return placed[i];
}

Habitat::Box Habitat::new_marker(size_t i) const {
  Box notice = bubble(i);
  const auto* art = habitat_assets::icon(habitat_assets::New);
  int percent = art ? std::min(100, std::min(3200 / art->width, 1400 / art->height)) : 100;
  int width = art ? std::max(1, art->width * percent / 100) : 26;
  int height = art ? std::max(1, art->height * percent / 100) : 14;
  return {notice.left + (notice.width - width) / 2, notice.top - height - 3, width, height, percent};
}

void Habitat::card_changed() {
  detail_ = false;
  card_at_ = last_;
  question_ready_ = false;
  invalidate();
}

void Habitat::open(size_t i) {
  selected_ = static_cast<int>(i);
  residents_[i].vx = residents_[i].vy = residents_[i].gait_hold = 0;
  residents_[i].moving = false;
  card_changed();
}

std::array<size_t, 8> Habitat::order() const {
  std::array<size_t, 8> indices = {0, 1, 2, 3, 4, 5, 6, 7};
  std::sort(indices.begin(), indices.end(), [this](size_t a, size_t b) {
    return feet(a) == feet(b) ? a < b : feet(a) < feet(b);
  });
  return indices;
}

bool Habitat::walkable(size_t i, int px, int py) const {
  if (i >= residents_.size() || py < kSandTop || py > kSandBottom) return false;
  int margin = 60 + std::max(0, py - 310) / 2;
  auto info = display_.info();
  if (px < margin || px > info.width - margin) return false;
  int width = 24, height = 24;
  for (size_t p = 0; p < habitat_assets::PoseCount; ++p) {
    if (const auto* image = habitat_assets::frame(i, p)) {
      width = std::max(width, static_cast<int>(image->width));
      height = std::max(height, static_cast<int>(image->height));
    }
  }
  width = width * sprite_percent(py) / 100;
  height = height * sprite_percent(py) / 100;
  // Keep the whole pose and notice badge inside the circular glass.
  int xs[] = {px - width / 2 - 20, px + (width + 1) / 2 + 20};
  int ys[] = {py - height - 54, py + 4};
  int radius = info.height / 2 - 4;
  for (int xx : xs) for (int yy : ys) {
    int dx = xx - info.width / 2, dy = yy - info.height / 2;
    if (dx * dx + dy * dy > radius * radius) return false;
  }
  return true;
}

bool Habitat::separated(size_t i, int px, int py, int prediction) const {
  for (size_t j = 0; j < residents_.size(); ++j) {
    if (j == i) continue;
    const auto& other = residents_[j];
    int ox = other.px, oy = other.py;
    if (prediction && !other.resting && !other.pending && selected_ != static_cast<int>(j)) {
      int nx = ox + other.vx * prediction, ny = oy + other.vy * prediction;
      if (walkable(j, pixel(nx), pixel(ny))) { ox = nx; oy = ny; }
    }
    int64_t dx = static_cast<int64_t>(px) - ox;
    int64_t dy = static_cast<int64_t>(py) - oy;
    // An oval footprint leaves more room for wide sprites than a small circle.
    const int64_t radius = static_cast<int64_t>(kClearX) * kClearY * kFixed;
    if (dx * dx * kClearY * kClearY + dy * dy * kClearX * kClearX < radius * radius) return false;
  }
  return true;
}

bool Habitat::path_clear(size_t i, int px, int py) const {
  const auto& r = residents_[i];
  int count = std::max(1, norm(px - r.px, py - r.py) / (8 * kFixed));
  for (int step = 1; step <= count; ++step) {
    int x = r.px + (px - r.px) * step / count;
    int y = r.py + (py - r.py) * step / count;
    if (!walkable(i, pixel(x), pixel(y)) || !separated(i, x, y)) return false;
  }
  return true;
}

void Habitat::target(size_t i) {
  auto& r = residents_[i];
  r.blocked = r.distance = r.rest_age = r.gait_hold = 0;
  r.moving = r.stopping = r.sleeping = false;
  for (int attempt = 0; attempt < 24; ++attempt) {
    int tx = r.px + (static_cast<int>(roll(r.random) % 181) - 90) * kFixed;
    int ty = r.py + (static_cast<int>(roll(r.random) % 121) - 60) * kFixed;
    int64_t dx = static_cast<int64_t>(tx) - r.px, dy = static_cast<int64_t>(ty) - r.py;
    // Prefer continuing the current facing; allow reversal if space is limited.
    if (attempt < 8 && dx * r.direction < -10 * kFixed) continue;
    if (!walkable(i, pixel(tx), pixel(ty)) || !separated(i, tx, ty) ||
        dx * dx + dy * dy < static_cast<int64_t>(24 * kFixed) * (24 * kFixed) ||
        dx * dx + dy * dy > static_cast<int64_t>(100 * kFixed) * (100 * kFixed) ||
        !path_clear(i, tx, ty)) continue;
    r.target_x = tx; r.target_y = ty;
    r.resting = false;
    r.travel = std::min(1000, norm(static_cast<int>(dx), static_cast<int>(dy)) / r.speed + 120);
    r.progress_timer = 20;
    r.progress_distance = norm(static_cast<int>(dx), static_cast<int>(dy));
    r.stalled = 0;
    if (!r.face_hold && norm(r.vx, r.vy) <= 16 && std::abs(dx) >= 8 * kFixed) {
      r.direction = dx > 0 ? 1 : -1;
      r.face_votes = 0;
      r.face_hold = 16;
    }
    return;
  }
  // Wait and try again instead of teleporting or entering occupied terrain.
  r.resting = true;
  r.vx = r.vy = 0;
  r.remaining = 16 + static_cast<int>(roll(r.random) % 25);
}

void Habitat::settle(size_t i, bool sleep_allowed) {
  auto& r = residents_[i];
  r.resting = true;
  r.moving = r.stopping = false;
  r.vx = r.vy = r.blocked = r.rest_age = r.face_votes = r.gait_hold = 0;
  r.sleeping = sleep_allowed && roll(r.random) % 4 == 0;
  r.remaining = r.sleeping ? 100 + static_cast<int>(roll(r.random) % 81) :
      sleep_allowed ? 32 + static_cast<int>(roll(r.random) % 59) :
      12 + static_cast<int>(roll(r.random) % 21);
}

void Habitat::motion() {
  reduced_ = !reduced_;
  if (reduced_) for (auto& r : residents_) { r.vx = r.vy = r.gait_hold = 0; r.moving = false; }
  invalidate();
}

bool Habitat::notify(std::string_view name, NoticeKind kind) {
  if (kind != NoticeKind::Info && kind != NoticeKind::Question && kind != NoticeKind::Error) return false;
  for (size_t i = 0; i < residents_.size(); ++i) {
    if (name != kNames[i]) continue;
    auto& r = residents_[i];
    if (r.pending == r.notices.size()) return false;  // Never overwrite an unanswered request.
    r.notices[(r.head + r.pending) % r.notices.size()] = {kind, next_id_++};
    if (!next_id_) ++next_id_;
    ++r.pending;
    r.fresh_until = frame_ + 60;
    r.moving = false;
    r.vx = r.vy = r.gait_hold = 0;
    if (selected_ == static_cast<int>(i) && r.pending == 1) card_changed();
    invalidate();
    return true;
  }
  return false;
}
void Habitat::remove_notice(uint8_t action) {
  auto& r = residents_[selected_];
  r.last_id = r.notices[r.head].id;
  r.last_action = action;
  r.head = static_cast<uint8_t>((r.head + 1) % r.notices.size());
  --r.pending;
  card_changed();
}

bool Habitat::read() {
  if (selected_ < 0 || !residents_[selected_].pending) return true;
  if (residents_[selected_].notices[residents_[selected_].head].kind == NoticeKind::Question) return false;
  remove_notice(1);
  return true;
}

bool Habitat::answer(bool yes) {
  if (selected_ < 0 || !question_ready_ || !residents_[selected_].pending ||
      residents_[selected_].notices[residents_[selected_].head].kind != NoticeKind::Question) return false;
  remove_notice(yes ? 2 : 3);
  return true;
}

void Habitat::details() {
  if (selected_ < 0 || !residents_[selected_].pending) return;
  detail_ = !detail_;
  invalidate();
}

bool Habitat::tick(uint32_t now) {
  update_clock(now);  // Wall time continues while the decorative simulation is off or paused.
  if (!enabled_) return false;
  const uint32_t steps = (now - last_) / kStepMs;
  if (!steps) return dirty_;
  last_ += steps * kStepMs;
  if (selected_ >= 0 && !question_ready_ && last_ - card_at_ >= 350) {
    question_ready_ = true;
    invalidate();
  }
  if (paused_) return dirty_;
  // Limit catch-up after a sleeping viewer without blocking the app task.
  for (uint32_t t = 0; t < std::min<uint32_t>(steps, 1000 / kStepMs); ++t) {
    ++frame_;
    if (frame_ == 60) invalidate();  // Intro HUD disappears after three seconds.
    for (const auto& r : residents_) if (r.pending && frame_ == r.fresh_until) invalidate();
    if (frame_ == 6000 / kStepMs) notify("palmon");
    // Rotate update priority so the same resident does not always win a crossing.
    for (size_t k = 0; k < residents_.size(); ++k) {
      size_t i = (frame_ + k) % residents_.size();
      auto& r = residents_[i];
      if (r.face_hold > 0) --r.face_hold;
      if (r.pending || reduced_ || selected_ == static_cast<int>(i)) continue;
      if (r.gait_hold > 0) --r.gait_hold;
      r.moving = false;
      if (r.resting) {
        ++r.rest_age;
        if (--r.remaining <= 0) target(i);
        continue;
      }
      int dx = r.target_x - r.px, dy = r.target_y - r.py;
      int distance = norm(dx, dy);
      if (distance <= 2 * kFixed || --r.travel <= 0) r.stopping = true;
      if (!r.stopping && --r.progress_timer <= 0) {
        // Detect net progress, not just leg motion. This ends a congested trip
        // rather than alternating escape directions indefinitely.
        r.stalled = r.progress_distance - distance < 2 * kFixed ? r.stalled + 1 : 0;
        r.progress_distance = distance;
        r.progress_timer = 20;
        if (r.stalled >= 2) { settle(i, false); continue; }
      }
      int pace = r.stopping ? 0 : std::min(r.speed, std::max(24, distance / 8));
      int sx = distance ? dx * pace / distance : 0, sy = distance ? dy * pace / distance : 0;
      int bx = approach(r.vx, 0), by = approach(r.vy, 0);
      int moves[][2] = {{approach(r.vx, sx), approach(r.vy, sy)},
                       {approach(r.vx, sx), by}, {bx, approach(r.vy, sy)}};
      bool forward = false;
      auto advance = [&](int vx, int vy) {
        int nx = r.px + vx, ny = r.py + vy;
        if (!walkable(i, pixel(nx), pixel(ny)) || !separated(i, nx, ny)) return false;
        r.px = nx; r.py = ny;
        r.vx = vx; r.vy = vy;
        r.distance += std::max(std::abs(vx), std::abs(vy));
        r.moving = norm(vx, vy) > 16;
        // A brief pose hold prevents idle/walk flashing near congestion. The
        // step phase still follows real distance, so stationary feet do not cycle.
        if (norm(vx, vy) >= 64) r.gait_hold = 6;
        return true;
      };
      for (int candidate = 0; candidate < (r.stopping ? 1 : 3); ++candidate) {
        int vx = moves[candidate][0], vy = moves[candidate][1];
        if (!vx && !vy) continue;
        // Look ahead before contact; never use the two opposing 90-degree
        // escape steps which made the old sprites vibrate and flip every tick.
        if (!r.stopping && !separated(i, r.px + vx * kPrediction, r.py + vy * kPrediction, kPrediction)) continue;
        if (!advance(vx, vy)) continue;
        forward = true;
        break;
      }
      if (forward) r.blocked = 0;
      else {
        // Brake where legal; hard clearance still wins over smoothing.
        if (!advance(bx, by)) r.vx = r.vy = 0;
        ++r.blocked;
      }
      if (r.stopping && norm(r.vx, r.vy) <= 16) { settle(i, true); continue; }
      if (r.blocked >= 32) { settle(i, false); continue; }
      if (r.moving && std::abs(r.vx) >= 48) {
        int facing = r.vx > 0 ? 1 : -1;
        r.face_votes = facing == r.direction ? 0 : r.face_votes + 1;
        if (!r.face_hold && r.face_votes >= 6) {
          r.direction = facing;
          r.face_votes = 0;
          r.face_hold = 16;
        }
      } else {
        r.face_votes = 0;
      }
    }
  }
  if (!reduced_) dirty_ = true;
  return dirty_;
}

void Habitat::tap(int px, int py) {
  auto info = display_.info();
  const int cx = info.width / 2, cy = info.height / 2;
  if (px < 0 || py < 0 || px >= info.width || py >= info.height) return;
  if (info.round && (px - cx) * (px - cx) + (py - cy) * (py - cy) > cy * cy) return;
  if (selected_ >= 0) {
    const auto& r = residents_[selected_];
    bool question = r.pending && r.notices[r.head].kind == NoticeKind::Question;
    if (question) {
      const int y = info.height * 83 / 100;
      if (py >= y && py < y + info.height * 7 / 100) {
        if (px >= cx - 136 && px < cx - 52) back();
        else if (px >= cx - 42 && px < cx + 42) answer(false);
        else if (px >= cx + 52 && px < cx + 136) answer(true);
        return;
      }
    }
    const int y = info.height * 84 / 100;
    if (!question && py >= y && py < y + info.height / 12) {
      if (px >= cx - 120 && px < cx - 10) back();
      else if (px >= cx + 10 && px < cx + 120) read();
      return;
    }
    if (px >= cx - 138 && px < cx + 138 && py >= info.height * 65 / 100 + 43 &&
        py < info.height * 65 / 100 + 86) details();
    return;
  }
  // Pick visible foreground pixels first. Registered crops include transparent
  // padding, which must not swallow a touch on a resident behind them.
  int best = -1, best_distance = 1000000;
  auto indices = order();
  for (auto it = indices.rbegin(); it != indices.rend(); ++it) {
    size_t i = *it;
    if (residents_[i].pending) {
      Box notice = bubble(i);
      bool hit = px >= notice.left - 5 && px <= notice.left + notice.width + 5 &&
                 py >= notice.top - 5 && py <= notice.top + notice.height + 5;
      if (frame_ < residents_[i].fresh_until) {
        Box fresh = new_marker(i);
        hit = hit || (px >= fresh.left - 3 && px <= fresh.left + fresh.width + 3 &&
                      py >= fresh.top - 3 && py <= fresh.top + fresh.height + 3);
      }
      if (hit) { open(i); return; }
    }
  }
  for (auto it = indices.rbegin(); it != indices.rend(); ++it) {
    size_t i = *it;
    Box b = box(i);
    int dx = px - (b.left + b.width / 2), dy = py - (b.top + b.height / 2);
    bool opaque = false;
    int local_x = px - b.left, local_y = py - b.top;
    if (local_x >= 0 && local_x < b.width && local_y >= 0 && local_y < b.height) {
      if (const auto* art = habitat_assets::frame(i, pose(i))) {
        int sx = local_x * art->width / b.width, sy = local_y * art->height / b.height;
        if (residents_[i].direction > 0) sx = art->width - sx - 1;
        opaque = !art->mask || (art->mask[sy * ((art->width + 7) / 8) + sx / 8] & (0x80 >> (sx % 8)));
      } else opaque = dx * dx + dy * dy <= (b.width / 2 - 2) * (b.width / 2 - 2);
    }
    if (opaque) { open(i); return; }
    if (local_x >= -6 && local_x <= b.width + 6 && local_y >= -6 && local_y <= b.height + 6 &&
        dx * dx + dy * dy < best_distance) {
      best = static_cast<int>(i);
      best_distance = dx * dx + dy * dy;
    }
  }
  if (best >= 0) open(static_cast<size_t>(best));
}

json::Value Habitat::status() const {
  auto value = json::Value::object();
  value.set("selected", selected_).set("paused", paused_).set("reduced_motion", reduced_)
       .set("frame", frame_).set("assets", habitat_assets::available()).set("details", detail_)
       .set("question_ready", question_ready_ && selected_ >= 0 && residents_[selected_].pending &&
            residents_[selected_].notices[residents_[selected_].head].kind == NoticeKind::Question);
  value.set("clock_known", clock_known_).set("time", clock_text_).set("date", clock_date_).set("link_online", link_online_);
  auto residents = json::Value::array();
  for (size_t i = 0; i < residents_.size(); ++i) {
    const auto& r = residents_[i];
    const auto& notice = r.notices[r.head];
    constexpr const char* actions[] = {"none", "read", "yes", "no"};
    Box b = box(i);
    Box cue = bubble(i);
    auto item = json::Value::object();
    item.set("name", kNames[i]).set("role", kRoles[i]).set("summary", r.pending ? summary(i, notice.kind) : "No pending information.")
        .set("pending", static_cast<int>(r.pending)).set("mode", r.pending ? "pending" : r.resting || selected_ == static_cast<int>(i) ? "rest" : "walk")
        .set("x", x(i)).set("y", b.top + b.height / 2).set("feet", feet(i))
        .set("target_x", pixel(r.target_x)).set("target_y", pixel(r.target_y))
        .set("pose", static_cast<int>(pose(i))).set("moving", r.moving && !reduced_ && !paused_ && selected_ != static_cast<int>(i))
        .set("direction", r.direction).set("vx", r.vx).set("vy", r.vy)
        .set("walking", r.gait_hold > 0 && !r.resting && !r.pending && !reduced_ && selected_ != static_cast<int>(i))
        .set("walkable", walkable(i, x(i), feet(i)))
        .set("kind", r.pending ? kind_name(notice.kind) : "none")
        .set("notice_id", r.pending ? notice.id : 0).set("fresh", r.pending && frame_ < r.fresh_until)
        .set("last_action", actions[r.last_action]).set("last_id", r.last_id)
        .set("cue_x", r.pending ? cue.left + cue.width / 2 : 0)
        .set("cue_y", r.pending ? cue.top + cue.height / 2 : 0);
    residents.push(std::move(item));
  }
  value.set("residents", std::move(residents));
  auto indices = json::Value::array();
  for (size_t i : order()) indices.push(static_cast<int>(i));
  value.set("draw_order", std::move(indices));
  return value;
}

void Habitat::render() {
  if (!dirty_) return;
  auto info = display_.info();
  const int w = info.width, h = info.height;
  // Repaint the moving band only; selected cards and header are static until
  // a notification or input invalidates them. ESP32 ports flush these same rows.
  int from = full_ ? 0 : h * 32 / 100;
  if (!full_) {
    // Include the tallest pose AND its badge, not just today's sprite bounds,
    // so a shorter next frame cannot leave old ears/wings above the dirty band.
    for (size_t i = 0; i < residents_.size(); ++i) {
      for (size_t p = 0; p < habitat_assets::PoseCount; ++p) {
        const auto* image = habitat_assets::frame(i, p);
        from = std::min(from, feet(i) - (image ? image->height : 24) * sprite_percent(feet(i)) / 100 - 56);
      }
    }
    from = std::max(0, from);
  }
  const int to = h;  // Water now reaches the bottom of the glass.
  paint(from, to);
  int sky = sky_offset(frame_, reduced_);
  if (!full_ && sky != painted_sky_) {
    // A slow sky refresh must not turn every sprite update into a full-panel
    // transfer. Only the 0..19 source-row band is sky; vegetation starts below it.
    if (const auto* bg = habitat_assets::background()) {
      int source_h = bg->height;
      if (bg->width * h <= bg->height * w) source_h = bg->width * h / w;
      int end = std::min(h, (20 * h + source_h - 1) / source_h);
      if (from >= end) paint(0, end);
      else paint(0, from);
    }
  }
  if (!full_ && hud_dirty_ && from >= 130) paint(0, 130);
  painted_sky_ = sky;
  hud_dirty_ = false;
  dirty_ = full_ = false;
}

void Habitat::paint(int from, int to) {
  auto info = display_.info();
  const int w = info.width, h = info.height;
  Canvas c(display_.framebuffer(), w, h, info.swap_bytes);
  c.set_clip_rows(from, to);
  const auto* bg = habitat_assets::background();
  if (bg) {
    // Cover the full panel at the original aspect ratio: crop the panorama,
    // never stretch it or allocate another framebuffer. Round glass clips it.
    int source_w = bg->width, source_h = bg->height;
    if (source_w * h > source_h * w) source_w = source_h * w / h;
    else source_h = source_w * h / w;
    const int ox = (bg->width - source_w) / 2, oy = (bg->height - source_h) / 2;
    // Cache X coordinates once per band, not one integer division per pixel.
    // The habitat is deliberately limited to the 466x466 round target.
    std::array<uint16_t, 466> columns{};
    for (int x = 0; x < w; ++x) columns[x] = static_cast<uint16_t>(ox + x * source_w / w);
    const auto* water = habitat_assets::layer(habitat_assets::Water);
    const auto* shore = habitat_assets::layer(habitat_assets::Shoreline);
    uint32_t ambient = reduced_ ? 0 : frame_ / 4;  // Water at 5 Hz, physics at 20 Hz.
    int tide = triangle(ambient, 40);
    int shore_y = 5 - tide / 10;  // Never flood the walkable sand above source row 97.
    int shore_strength = reduced_ ? 0 : tide * 12 / 20;
    int wave_phase = static_cast<int>(ambient % 32);
    int water_strength = reduced_ ? 0 : triangle(ambient, 32) / 2;
    int sky = sky_offset(frame_, reduced_);
    auto layer_color = [](const habitat_assets::Layer* layer, int sx, int sy, uint16_t& color) {
      if (!layer) return false;
      sx -= layer->x; sy -= layer->y;
      const auto& bitmap = layer->bitmap;
      if (sx < 0 || sy < 0 || sx >= bitmap.width || sy >= bitmap.height) return false;
      if (bitmap.mask && !(bitmap.mask[sy * ((bitmap.width + 7) / 8) + sx / 8] & (0x80 >> (sx % 8)))) return false;
      color = bitmap.pixels[sy * bitmap.width + sx];
      return true;
    };
    for (int y = from; y < to; ++y) {
      int sy = oy + y * source_h / h;
      int sky_shift = sy < 14 ? sky : sy < 20 ? sky * (20 - sy) / 6 : 0;
      uint16_t* row = display_.framebuffer() + static_cast<size_t>(y) * w;
      for (int x = 0; x < w; ++x) {
        int sx = columns[std::max(0, std::min(w - 1, x + sky_shift))];
        uint16_t color = bg->pixels[sy * bg->width + sx], overlay = 0;
        // Restore the immutable base every time, then compose only the sea edge
        // and foam. House, rocks, palms and the walking sand never shift.
        if (shore_strength && sy >= 97 && layer_color(shore, sx, sy - shore_y, overlay))
          color = mix565(color, overlay, shore_strength);
        if (water_strength && sy >= 108) {
          int water_x = columns[std::max(0, std::min(w - 1, x + wave_phase))];
          if (layer_color(water, water_x, sy, overlay)) color = mix565(color, overlay, water_strength);
        }
        row[x] = info.swap_bytes ? static_cast<uint16_t>((color << 8) | (color >> 8)) : color;
      }
    }
  } else {
    c.fill_rect(0, 0, w, h, rgb565(133, 208, 215));
    c.fill_rect(0, h * 55 / 100, w, h * 28 / 100, rgb565(218, 195, 136));
    c.fill_rect(0, h * 83 / 100, w, h, kSea);
  }
  home_text(c, 30, clock_text_, habitat_assets::Large);
  if (clock_known_) home_text(c, 75, clock_date_, habitat_assets::Small);
  else centered(c, 82, "SIN HORA / NO SYNC", 1, kText);
  int clock_right = (w + face_width(clock_text_, habitat_assets::Large)) / 2;
  c.fill_circle(clock_right + 14, 47, 4, link_online_ ? rgb565(101, 221, 157) : rgb565(238, 166, 88));
  int pending = 0;
  for (const auto& resident : residents_) pending += resident.pending;
  if (pending) home_text(c, 105, std::to_string(pending) + " PEND", habitat_assets::Small);
  for (size_t i : order()) {
    const auto& r = residents_[i];
    const auto* art = habitat_assets::frame(i, pose(i));
    const Box b = box(i);
    const int sw = b.width, sh = b.height, left = b.left, top = b.top;
    int shadow = std::max(10, sw * 2 / 3);
    c.fill_round_rect(x(i) - shadow / 2, feet(i) - 2, shadow, 4, 2, rgb565(120, 113, 78));
    if (art) bitmap(c, art, left, top, b.percent, r.direction > 0);
    else {
      // Original geometric stand-ins let CI and builds without private art run.
      uint16_t color = rgb565(70 + static_cast<uint8_t>(i * 20), 150, 100);
      c.fill_circle(x(i), top + sh / 2, sw / 2 - 2, color);
      c.text(x(i) - 3, top + sh / 2 - 4, std::to_string(i + 1), 1, kDark);
    }
    if (selected_ == static_cast<int>(i)) c.rect(left - 3, top - 3, sw + 6, sh + 6, kText);
  }
  // A displaced cue keeps a subtle connection to its owner when several inboxes
  // are pending at once. Draw these before the icons, never through their text.
  for (size_t i : order()) {
    if (!residents_[i].pending) continue;
    Box actor = box(i), cue = bubble(i);
    int head = actor.left + actor.width * (residents_[i].direction > 0 ? 2 : 1) / 3;
    int x0 = cue.left + cue.width / 2, y0 = cue.top + cue.height - 2;
    if (std::abs(x0 - head) <= 20 && actor.top - y0 <= 10) continue;
    int dx = head - x0, dy = actor.top - 2 - y0;
    int steps = std::max(std::abs(dx), std::abs(dy));
    if (!steps) continue;
    for (int step = 0; step <= steps; step += 2)
      c.pixel(x0 + dx * step / steps, y0 + dy * step / steps, rgb565(190, 211, 200));
  }
  // Draw bubbles above all resident art so a nearer sprite cannot hide a cue.
  for (size_t i : order()) {
    const auto& r = residents_[i];
    if (!r.pending) continue;
    auto kind = r.notices[r.head].kind;
    Box notice = bubble(i);
    if (const auto* art = habitat_assets::icon(kind_icon(kind)))
      bitmap(c, art, notice.left, notice.top, notice.percent, false);
    else {
      c.fill_round_rect(notice.left, notice.top, notice.width, notice.height, 8, kText);
      c.fill_rect(notice.left + notice.width - 8, notice.top + notice.height - 3, 5, 6, kText);
      const char* glyph = kind == NoticeKind::Question ? "?" : kind == NoticeKind::Error ? "+" : "!";
      c.text(notice.left + (notice.width - Canvas::text_width(glyph, 2)) / 2, notice.top + 5,
             glyph, 2, kind == NoticeKind::Question ? rgb565(32, 101, 192) : rgb565(215, 62, 56));
    }
    if (r.pending > 1) {
      c.fill_circle(notice.left + notice.width - 2, notice.top + 2, 7, kDark);
      c.text(notice.left + notice.width - 5, notice.top - 2, std::to_string(r.pending), 1, kText);
    }
    if (frame_ < r.fresh_until) {
      Box fresh = new_marker(i);
      if (const auto* art = habitat_assets::icon(habitat_assets::New))
        bitmap(c, art, fresh.left, fresh.top, fresh.percent, false);
      else {
        c.fill_round_rect(fresh.left, fresh.top, fresh.width, fresh.height, 5, rgb565(192, 45, 46));
        c.text(fresh.left + 4, fresh.top + 3, "NEW", 1, kText);
      }
    }
  }
  if (selected_ >= 0) {
    const auto& r = residents_[selected_];
    bool question = r.pending && r.notices[r.head].kind == NoticeKind::Question;
    bool error = r.pending && r.notices[r.head].kind == NoticeKind::Error;
    uint16_t accent = question ? rgb565(91, 170, 246) : error ? rgb565(248, 143, 112) : kGold;
    int card_x = w / 2 - 150, card_y = h * 65 / 100;
    c.fill_round_rect(card_x, card_y, 300, 87, 16, accent);
    c.fill_round_rect(card_x + 1, card_y + 1, 298, 85, 15, kDark);
    if (r.pending) {
      const auto* icon = habitat_assets::icon(kind_icon(r.notices[r.head].kind));
      if (icon) bitmap(c, icon, card_x + 12, card_y + 8,
                       std::min(100, 2800 / std::max(icon->width, icon->height)), false);
      else c.text(card_x + 18, card_y + 10, question ? "?" : error ? "+" : "!", 2, accent);
    }
    face_text(c, card_x + 50, card_y + 9, kNames[selected_], habitat_assets::Small, kText);
    c.text(card_x + 50, card_y + 29, question ? "REPLY NEEDED / DEMO" : error ? "INCIDENT / DEMO" : r.pending ? "INFORMATION" : "PROFILE / DEMO", 1, accent);
    if (r.pending) c.text(card_x + 245, card_y + 12, std::to_string(r.pending) + " left", 1, accent);
    std::string text = r.pending ? summary(selected_, r.notices[r.head].kind) :
        r.last_action == 2 ? "Demo response accepted." : r.last_action == 3 ? "Demo response declined." : "No pending information.";
    auto lines = wrap_text(text, 44);
    for (size_t line = 0; line < std::min<size_t>(2, lines.size()); ++line)
      c.text(card_x + 12, card_y + 47 + static_cast<int>(line) * 10, lines[line], 1, kText);
    c.text(card_x + 12, card_y + 74, detail_ ? "Local demo. No external action sent." :
           r.pending ? "Tap message for details" : kRoles[selected_], 1, detail_ ? accent : rgb565(158, 191, 186));
    int y = h * 84 / 100;
    auto button = [&](int x, int width, int height, const char* label, uint16_t fill, uint16_t ink) {
      c.fill_round_rect(x, y, width, height, 6, fill);
      face_text(c, x + (width - face_width(label, habitat_assets::Small)) / 2, y + 8, label, habitat_assets::Small, ink);
    };
    if (question) {
      y = h * 83 / 100;
      int height = h * 7 / 100;
      button(w / 2 - 136, 84, height, "BACK", rgb565(34, 70, 67), kText);
      button(w / 2 - 42, 84, height, "NO", rgb565(79, 57, 61), question_ready_ ? kText : rgb565(132, 137, 140));
      button(w / 2 + 52, 84, height, "YES", question_ready_ ? accent : rgb565(34, 70, 67), question_ready_ ? kDark : rgb565(132, 137, 140));
    } else {
      button(w / 2 - 120, 110, h / 12, "BACK", rgb565(34, 70, 67), kText);
      button(w / 2 + 10, 110, h / 12, error ? "REVIEW" : "READ", r.pending ? accent : rgb565(34, 70, 67), r.pending ? kDark : rgb565(132, 137, 140));
    }
  } else if (frame_ < 60) {
    c.fill_round_rect(w / 2 - 110, h * 87 / 100, 220, 26, 6, kDark);
    centered(c, h * 87 / 100 + 6, "Tap a resident", 1, kText);
  }
  display_.flush(static_cast<uint16_t>(from), static_cast<uint16_t>(to));
}
}  // namespace hg
