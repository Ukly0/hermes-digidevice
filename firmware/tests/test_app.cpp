// Drives hg::App through a fake HAL the way a Hermes gateway would.
#include <algorithm>
#include <cstdlib>
#include <deque>
#include <map>
#include <string>
#include <vector>

#include "check.hpp"
#include "hg/app.hpp"
#include "hg/crypto.hpp"
#include "hg/habitat_assets.hpp"
#include "hg/protocol.hpp"
#include "hg/setup.hpp"
#include "hg/touch.hpp"

using hg::json::Value;

namespace {

struct FakeHal : hg::Display, hg::AudioIn, hg::AudioOut, hg::Transport, hg::Storage, hg::System {
  // System
  uint32_t clock = 1000;
  uint32_t now_ms() override { return clock; }
  void random_bytes(uint8_t* out, size_t len) override {
    for (size_t i = 0; i < len; ++i) out[i] = static_cast<uint8_t>(i);
  }
  void log(hg::LogLevel, std::string_view) override {}

  // Transport
  std::string url;
  int connects = 0, closes = 0;
  std::vector<Value> sent;
  std::vector<std::vector<uint8_t>> sent_binary;
  void connect(const std::string& u, const std::string&) override {
    url = u;
    ++connects;
  }
  bool send_text(std::string_view text) override {
    Value v;
    if (hg::json::parse(text, v)) sent.push_back(v);
    return true;
  }
  bool send_binary(const uint8_t* data, size_t len) override {
    sent_binary.emplace_back(data, data + len);
    return true;
  }
  void close() override { ++closes; }

  // Storage
  std::map<std::string, std::string> kv;
  std::optional<std::string> get(std::string_view key) override {
    auto it = kv.find(std::string(key));
    if (it == kv.end()) return std::nullopt;
    return it->second;
  }
  void set(std::string_view key, std::string_view value) override { kv[std::string(key)] = std::string(value); }
  void erase(std::string_view key) override { kv.erase(std::string(key)); }

  // Display
  int width = 320, height = 240;
  bool round = false;
  bool backlight = false;
  int brightness = 0, volume = 0;
  std::vector<uint16_t> fb = std::vector<uint16_t>(320 * 240, 0);
  int flushes = 0;
  int flushed_rows = 0;
  hg::DisplayInfo info() const override {
    hg::DisplayInfo d;
    d.width = static_cast<uint16_t>(width);
    d.height = static_cast<uint16_t>(height);
    d.round = round;
    d.has_backlight = backlight;
    return d;
  }
  void make_round(int diameter) {
    width = height = diameter;
    round = true;
    fb.assign(static_cast<size_t>(diameter * diameter), 0);
  }
  uint16_t* framebuffer() override { return fb.data(); }
  void set_backlight(uint8_t percent) override { brightness = percent; }
  void flush(uint16_t y0, uint16_t y1) override {
    ++flushes;
    flushed_rows += y1 - y0;
  }

  // Mic
  bool mic_on = false;
  bool start(uint32_t) override { return mic_on = true; }
  void stop() override { mic_on = false; }

  // Speaker
  bool spk_open = false;
  size_t spk_samples = 0;
  bool begin(uint32_t) override { return spk_open = true; }
  void write(const int16_t*, size_t n) override { spk_samples += n; }
  void end() override { spk_open = false; }
  void abort() override { spk_open = false; }
  bool busy() const override { return spk_open; }
  void set_volume(uint8_t percent) override { volume = percent; }

  hg::Hal hal() {
    hg::Hal h;
    h.system = this;
    h.transport = this;
    h.storage = this;
    h.display = this;
    h.mic = this;
    h.speaker = this;
    return h;
  }

  const Value* last(const std::string& type) const {
    for (auto it = sent.rbegin(); it != sent.rend(); ++it)
      if ((*it)["type"].as_string() == type) return &*it;
    return nullptr;
  }
};

struct FakeUpdater : hg::Updater {
  size_t slot = 64 * 1024;
  std::vector<uint8_t> image;
  bool open = false, installed = false, restarted = false, pending = false, confirmed = false;
  bool reject_image = false;
  size_t capacity() const override { return slot; }
  bool begin(size_t, std::string&) override {
    image.clear();
    return open = true;
  }
  bool write(const uint8_t* data, size_t len, std::string&) override {
    image.insert(image.end(), data, data + len);
    return open;
  }
  bool finish(std::string& error) override {
    open = false;
    if (reject_image) error = "not an app image";
    return installed = !reject_image;
  }
  void abort() override { open = false; }
  void restart() override { restarted = true; }
  bool pending_verify() const override { return pending; }
  void confirm() override {
    pending = false;
    confirmed = true;
  }
};

struct Rig {
  FakeHal fake;
  hg::Hal hal = fake.hal();
  hg::App app;

  explicit Rig(const std::string& server = "ws://hermes.local:8765/gadget") : app(hal, profile(server)) {}
  explicit Rig(hg::DeviceProfile p) : app(hal, std::move(p)) {}

  static hg::DeviceProfile touch_profile() {
    hg::DeviceProfile p = profile("ws://hermes.local:8765/gadget");
    p.touch_screen = true;
    p.cancel_label = "Swipe down";
    p.extra_settings = {"touch_cancel"};
    return p;
  }

  static hg::DeviceProfile profile(const std::string& server) {
    hg::DeviceProfile p;
    p.board = "test-board";
    p.firmware = "1.2.3";
    p.default_server_url = server;
    return p;
  }

  void advance(uint32_t ms) {
    for (uint32_t t = 0; t < ms; t += 10) {
      fake.clock += 10;
      app.tick();
    }
  }

  void server(const std::string& json) { app.on_transport_text(json); }

  // Boot, connect, authenticate and (optionally) get approved.
  void bring_online(bool paired) {
    app.begin();
    app.on_network(true, "test-wifi");
    advance(1000);
    app.on_transport_open();
    server(R"({"type":"challenge","nonce":"bm9uY2U=","enrolled":false})");
    server(std::string(R"({"type":"welcome","session":"s1","heartbeat_s":20,"paired":)") +
           (paired ? "true" : "false") + "}");
  }
};

}  // namespace

TEST("app: connects after boot and sends a hello describing the device") {
  Rig r;
  r.app.begin();
  CHECK(r.app.screen() == hg::Screen::Boot);
  r.app.on_network(true, "wifi");
  r.advance(1000);
  CHECK_EQ(r.fake.connects, 1);
  CHECK_EQ(r.fake.url, std::string("ws://hermes.local:8765/gadget"));
  CHECK(r.app.screen() == hg::Screen::Connecting);
  r.app.on_transport_open();
  const Value* hello = r.fake.last("hello");
  CHECK(hello != nullptr);
  if (!hello) return;
  CHECK_EQ((*hello)["proto"].as_int(), int64_t(1));
  CHECK_EQ((*hello)["device_id"].as_string(), r.app.device_id());
  CHECK_EQ((*hello)["board"].as_string(), std::string("test-board"));
  CHECK_EQ((*hello)["caps"]["display"]["width"].as_int(), int64_t(320));
  CHECK_EQ((*hello)["caps"]["mic"]["rate"].as_int(), int64_t(16000));
  CHECK((*hello)["caps"]["speaker"].is_object());
  bool has_volume = false;
  for (const auto& a : (*hello)["actions"].elements()) has_volume |= a["name"].as_string() == "speaker.volume";
  CHECK(has_volume);
}

TEST("app: first contact enrolls the key, later contact proves it with an HMAC") {
  Rig r;
  r.app.begin();
  r.app.on_network(true);
  r.advance(1000);
  r.app.on_transport_open();
  r.server(R"({"type":"challenge","nonce":"abc","enrolled":false})");
  const Value* auth = r.fake.last("auth");
  CHECK(auth && (*auth)["key"].is_string() && !(*auth)["mac"].is_string());
  std::vector<uint8_t> key;
  CHECK(hg::crypto::base64_decode((*auth)["key"].as_string(), key));
  CHECK_EQ(hg::proto::device_id_for_key(key.data(), key.size()), r.app.device_id());

  r.fake.sent.clear();
  r.app.on_transport_closed("bye");
  r.advance(3000);
  r.app.on_transport_open();
  r.server(R"({"type":"challenge","nonce":"n2","enrolled":true})");
  auth = r.fake.last("auth");
  CHECK(auth && !(*auth)["key"].is_string());
  CHECK_EQ((*auth)["mac"].as_string(), hg::proto::auth_mac(key.data(), key.size(), r.app.device_id(), "n2"));
}

TEST("app: the device key persists across restarts") {
  Rig r;
  r.app.begin();
  std::string id = r.app.device_id();
  hg::Hal hal = r.fake.hal();
  hg::App again(hal, Rig::profile("ws://x"));
  again.begin();
  CHECK_EQ(again.device_id(), id);
}

TEST("app: unpaired devices show the pairing code until approved") {
  Rig r;
  r.bring_online(false);
  CHECK(r.app.screen() == hg::Screen::Pairing);
  r.server(R"({"type":"pairing","code":"ABCD2345","command":"hermes pairing approve gadget ABCD2345"})");
  CHECK_EQ(r.app.model().code, std::string("ABCD2345"));
  // Talking is refused while unpaired.
  r.app.on_button(hg::Button::Talk, true);
  CHECK(!r.fake.mic_on);
  r.server(R"({"type":"paired"})");
  CHECK(r.app.screen() == hg::Screen::Ready);
}

TEST("app: push-to-talk streams audio and shows the reply") {
  Rig r;
  r.bring_online(true);
  CHECK(r.app.screen() == hg::Screen::Ready);
  r.app.on_button(hg::Button::Talk, true);
  CHECK(r.fake.mic_on);
  CHECK(r.app.screen() == hg::Screen::Listening);
  const Value* start = r.fake.last("audio.start");
  CHECK(start != nullptr);
  int stream = start ? static_cast<int>((*start)["stream"].as_int()) : -1;

  std::vector<int16_t> pcm(1600, 1000);  // 100 ms
  for (int i = 0; i < 6; ++i) {
    r.app.on_mic_samples(pcm.data(), pcm.size());
    r.advance(100);
  }
  CHECK(!r.fake.sent_binary.empty());
  hg::proto::BinaryFrame f;
  CHECK(hg::proto::parse_binary(r.fake.sent_binary[0].data(), r.fake.sent_binary[0].size(), f));
  CHECK(f.channel == hg::proto::Channel::Audio);
  CHECK_EQ(int(f.stream), stream);
  size_t samples = 0;
  for (auto& b : r.fake.sent_binary) samples += (b.size() - hg::proto::kBinaryHeader) / 2;
  CHECK_EQ(samples, size_t(9600));

  r.app.on_button(hg::Button::Talk, false);
  CHECK(!r.fake.mic_on);
  CHECK(r.fake.last("audio.end") != nullptr);
  CHECK(r.app.screen() == hg::Screen::Thinking);

  r.server(R"({"type":"turn.start","turn":"a1"})");
  r.server(R"({"type":"status","text":"Searching the web"})");
  CHECK_EQ(r.app.model().detail, std::string("Searching the web"));
  r.server(R"({"type":"reply.delta","turn":"a1","text":"It is"})");
  CHECK(r.app.screen() == hg::Screen::Responding);
  r.server(R"({"type":"reply","turn":"a1","text":"It is sunny."})");
  CHECK_EQ(r.app.model().body, std::string("It is sunny."));
  r.server(R"({"type":"turn.end","turn":"a1","outcome":"success"})");
  r.advance(200);
  CHECK(r.app.screen() == hg::Screen::Ready);
  CHECK_EQ(r.app.model().body, std::string("It is sunny."));
}

TEST("app: a short tap is discarded instead of sent") {
  Rig r;
  r.bring_online(true);
  r.app.on_button(hg::Button::Talk, true);
  r.advance(100);
  r.app.on_button(hg::Button::Talk, false);
  CHECK(r.fake.last("audio.cancel") != nullptr);
  CHECK(r.fake.last("audio.end") == nullptr);
  CHECK(r.app.screen() == hg::Screen::Ready);
}

TEST("app: reply audio plays through the speaker and barge-in stops it") {
  Rig r;
  r.bring_online(true);
  r.server(R"({"type":"audio.start","stream":3,"rate":16000,"format":"pcm16"})");
  CHECK(r.fake.spk_open);
  std::vector<uint8_t> frame(hg::proto::kBinaryHeader + 640, 0);
  hg::proto::write_binary_header(frame.data(), hg::proto::Channel::Audio, 3, 0);
  r.app.on_transport_binary(frame.data(), frame.size());
  CHECK_EQ(r.fake.spk_samples, size_t(320));
  // Frames for another stream are ignored.
  hg::proto::write_binary_header(frame.data(), hg::proto::Channel::Audio, 4, 1);
  r.app.on_transport_binary(frame.data(), frame.size());
  CHECK_EQ(r.fake.spk_samples, size_t(320));
  r.advance(200);
  CHECK(r.app.model().speaking);
  r.app.on_button(hg::Button::Talk, true);
  CHECK(!r.fake.spk_open);
  CHECK(r.app.screen() == hg::Screen::Listening);
}

TEST("app: agent actions run on the device and report results") {
  Rig r;
  int calls = 0;
  hg::Action led;
  led.name = "led.set";
  led.description = "Set the LED colour";
  led.handler = [&](const Value& args, Value& result, std::string& error) {
    ++calls;
    if (args["color"].as_string().empty()) {
      error = "color required";
      return false;
    }
    result.set("color", args["color"]);
    return true;
  };
  r.app.add_action(led);
  r.bring_online(true);
  r.server(R"({"type":"action","id":"x1","name":"led.set","args":{"color":"red"}})");
  const Value* res = r.fake.last("action.result");
  CHECK(res && (*res)["ok"].as_bool() && (*res)["result"]["color"].as_string() == "red");
  r.server(R"({"type":"action","id":"x2","name":"led.set","args":{}})");
  res = r.fake.last("action.result");
  CHECK(res && !(*res)["ok"].as_bool() && (*res)["error"].as_string() == "color required");
  r.server(R"({"type":"action","id":"x3","name":"nope","args":{}})");
  res = r.fake.last("action.result");
  CHECK(res && (*res)["id"].as_string() == "x3" && !(*res)["ok"].as_bool());
  CHECK_EQ(calls, 2);
}

TEST("app: lost connections retry with backoff") {
  Rig r;
  r.bring_online(true);
  r.app.on_transport_closed("server restarted");
  CHECK(r.app.screen() == hg::Screen::Connecting);
  int before = r.fake.connects;
  r.advance(500);
  CHECK_EQ(r.fake.connects, before);
  r.advance(1000);
  CHECK_EQ(r.fake.connects, before + 1);
}

TEST("app: a silent server is detected by the heartbeat timeout") {
  Rig r;
  r.bring_online(true);
  r.advance(61000);
  CHECK(r.fake.closes >= 1);
  CHECK(r.app.screen() == hg::Screen::Connecting);
}

TEST("app: console reconfigures the server and reconnects") {
  Rig r("");
  r.app.begin();
  r.app.on_network(true);
  r.advance(1000);
  CHECK(r.app.screen() == hg::Screen::Error);
  CHECK_EQ(r.app.console("set server ws://10.0.0.5:8765/gadget"), std::string("@ok server"));
  r.advance(100);
  CHECK_EQ(r.fake.url, std::string("ws://10.0.0.5:8765/gadget"));
  CHECK(r.app.console("get token").find("\"value\":\"\"") != std::string::npos);
  r.app.console("set token secret");
  CHECK(r.app.console("get token").find("<set>") != std::string::npos);
  CHECK(r.app.console("status").rfind("@status {", 0) == 0);
}

TEST("app: diag reports the core's state plus what the port adds") {
  Rig r;
  r.bring_online(true);
  CHECK_EQ(r.app.console("diag log"), std::string("@error this device keeps no log"));
  CHECK(r.app.console("help").find("diag") != std::string::npos);

  r.app.on_diag = [](Value& report) { report.set("reset_reason", "brownout"); };
  r.app.recent_log = [] { return std::string("I (10) hg: booted"); };
  std::string out = r.app.console("diag");
  CHECK(out.rfind("@diag {", 0) == 0);
  Value v;
  CHECK(hg::json::parse(out.substr(6), v));
  CHECK_EQ(v["board"].as_string(), std::string("test-board"));
  CHECK_EQ(v["firmware"].as_string(), std::string("1.2.3"));
  CHECK_EQ(v["app"]["phase"].as_string(), std::string("online"));
  CHECK_EQ(v["connection"]["network"].as_string(), std::string("test-wifi"));
  CHECK_EQ(v["reset_reason"].as_string(), std::string("brownout"));
  CHECK_EQ(r.app.console("diag log"), std::string("I (10) hg: booted\n@log end"));

  r.app.on_transport_closed("server went away");
  CHECK(hg::json::parse(r.app.console("diag").substr(6), v));
  CHECK_EQ(v["connection"]["last_close"].as_string(), std::string("server went away"));
}

namespace {

// The server's side of a firmware update, as the hub runs it.
struct OtaServer {
  Rig& r;
  std::vector<uint8_t> image;
  std::string sha;
  uint8_t stream = 9;
  uint16_t seq = 0;

  OtaServer(Rig& rig, size_t size) : r(rig), image(size) {
    for (size_t i = 0; i < size; ++i) image[i] = static_cast<uint8_t>(i * 7);
    hg::crypto::Digest d = hg::crypto::sha256(image.data(), image.size());
    sha = hg::crypto::hex(d.data(), d.size());
  }

  std::string key_b64() const { return r.fake.kv.at("device_key"); }

  std::string offer(size_t size = 0) {
    r.fake.sent.clear();
    r.server(R"({"type":"ota.offer","stream":9,"version":"9.9.9","size":)" +
             std::to_string(size ? size : image.size()) + R"(,"sha256":")" + sha + "\"}");
    const Value* ready = r.fake.last("ota.ready");
    return ready ? (*ready)["nonce"].as_string() : std::string();
  }

  void begin(const std::string& nonce, bool wrong_key = false) {
    std::vector<uint8_t> key;
    hg::crypto::base64_decode(key_b64(), key);
    if (wrong_key) key[0] ^= 1;
    std::string mac = hg::proto::ota_mac(key.data(), key.size(), r.app.device_id(), nonce, sha, image.size());
    r.server(R"({"type":"ota.begin","mac":")" + mac + "\"}");
  }

  void chunk(size_t off, size_t len) {
    std::vector<uint8_t> frame(hg::proto::kBinaryHeader + len);
    hg::proto::write_binary_header(frame.data(), hg::proto::Channel::Firmware, stream, seq++);
    std::copy(image.begin() + static_cast<long>(off), image.begin() + static_cast<long>(off + len),
              frame.begin() + hg::proto::kBinaryHeader);
    r.app.on_transport_binary(frame.data(), frame.size());
  }

  void send_all() {
    for (size_t off = 0; off < image.size(); off += 4096) chunk(off, std::min<size_t>(4096, image.size() - off));
  }

  std::string error_code() const {
    const Value* e = r.fake.last("ota.error");
    return e ? (*e)["code"].as_string() : std::string();
  }
};

}  // namespace

TEST("ota: an authorized image streams in, is checked, and the device restarts into it") {
  FakeUpdater upd;
  Rig r;
  r.hal.updater = &upd;
  r.bring_online(true);
  const Value* hello = r.fake.last("hello");
  CHECK(hello && (*hello)["caps"]["ota"]["max_size"].as_int() == 64 * 1024);

  OtaServer s(r, 40000);
  std::string nonce = s.offer();
  CHECK(!nonce.empty());
  s.begin(nonce);
  const Value* ack = r.fake.last("ota.ack");
  CHECK(ack && (*ack)["offset"].as_int() == 0);
  CHECK(upd.open);
  CHECK_EQ(r.app.screen(), hg::Screen::Updating);
  CHECK(r.app.model().detail.find("9.9.9: 0% of 40 KB") != std::string::npos);

  s.send_all();
  ack = r.fake.last("ota.ack");
  CHECK(ack && (*ack)["offset"].as_int() == 40000);  // 16 KB steps, then the end
  CHECK_EQ(r.app.model().detail, std::string("firmware 9.9.9: 100% of 40 KB"));
  r.server(R"({"type":"ota.end"})");
  const Value* done = r.fake.last("ota.done");
  CHECK(done && (*done)["version"].as_string() == "9.9.9");
  CHECK(upd.installed && upd.image == s.image);
  CHECK(!upd.restarted);  // ota.done leaves first
  r.advance(1100);
  CHECK(upd.restarted);
}

TEST("ota: the device refuses images it can't trust or hold") {
  FakeUpdater upd;
  Rig r;
  r.hal.updater = &upd;
  r.bring_online(true);
  OtaServer s(r, 20000);

  s.begin(s.offer(), /*wrong_key=*/true);
  CHECK_EQ(s.error_code(), std::string("unauthorized"));
  CHECK(!upd.open);

  s.offer(100 * 1024);
  CHECK_EQ(s.error_code(), std::string("too_large"));

  r.server(R"({"type":"ota.begin","mac":"x"})");
  CHECK_EQ(s.error_code(), std::string("no_offer"));

  // A wrong SHA-256: the bytes arrive, but don't match what was offered.
  s.begin(s.offer());
  s.image[5] ^= 0xFF;
  s.send_all();
  r.server(R"({"type":"ota.end"})");
  CHECK_EQ(s.error_code(), std::string("checksum"));
  CHECK(!upd.installed);

  // The port rejects the image itself.
  s.image[5] ^= 0xFF;
  s.seq = 0;
  upd.reject_image = true;
  s.begin(s.offer());
  s.send_all();
  r.server(R"({"type":"ota.end"})");
  CHECK_EQ(s.error_code(), std::string("invalid"));
  CHECK(r.fake.last("ota.done") == nullptr);
  CHECK(r.app.model().detail.find("Update failed: not an app image") != std::string::npos);
}

TEST("ota: a missing chunk, a stall or a dropped connection abandons the update") {
  FakeUpdater upd;
  Rig r;
  r.hal.updater = &upd;
  r.bring_online(true);
  OtaServer s(r, 20000);

  s.begin(s.offer());
  s.chunk(0, 4096);
  ++s.seq;  // skip one
  s.chunk(8192, 4096);
  CHECK_EQ(s.error_code(), std::string("sequence"));
  CHECK(!upd.open);
  CHECK(r.app.screen() != hg::Screen::Updating);

  s.seq = 0;
  s.begin(s.offer());
  s.chunk(0, 4096);
  r.advance(31000);
  CHECK_EQ(s.error_code(), std::string("timeout"));
  CHECK(!upd.open);

  s.seq = 0;
  s.begin(s.offer());
  s.chunk(0, 4096);
  r.app.on_transport_closed("gone");
  CHECK(!upd.open);
  CHECK(r.app.status_json().find("\"update\"") == std::string::npos);

  // Devices without an update slot don't advertise one, and say so if offered an image.
  Rig plain;
  plain.bring_online(true);
  const Value* hello = plain.fake.last("hello");
  CHECK(hello && !(*hello)["caps"]["ota"].is_object());
  OtaServer p(plain, 100);
  p.offer();
  CHECK_EQ(p.error_code(), std::string("unsupported"));
}

TEST("ota: a newly installed firmware is kept once it reaches Hermes") {
  FakeUpdater upd;
  upd.pending = true;
  Rig r;
  r.hal.updater = &upd;
  r.app.begin();
  r.app.on_network(true, "test-wifi");
  r.advance(1000);
  r.app.on_transport_open();
  r.server(R"({"type":"challenge","nonce":"bm9uY2U=","enrolled":false})");
  CHECK(!upd.confirmed);  // authenticating isn't enough
  r.server(R"({"type":"welcome","session":"s1","heartbeat_s":20,"paired":false})");
  CHECK(upd.confirmed);
}

TEST("app: sensor readings are reported, rate limited") {
  Rig r;
  r.bring_online(true);
  r.fake.sent.clear();
  r.app.set_sensor("battery_pct", 80);
  r.advance(100);
  const Value* st = r.fake.last("state");
  CHECK(st && (*st)["sensors"]["battery_pct"].as_number() == 80);
  r.fake.sent.clear();
  r.app.set_sensor("battery_pct", 79);
  r.advance(100);
  CHECK(r.fake.last("state") == nullptr);
  r.advance(2100);
  CHECK(r.fake.last("state") != nullptr);
}

TEST("app: the mascot fills idle, listening and thinking screens") {
  Rig r;
  r.bring_online(true);
  CHECK(r.app.model().hero);  // idle
  r.app.on_button(hg::Button::Talk, true);
  CHECK(r.app.screen() == hg::Screen::Listening && r.app.model().hero);
  r.advance(500);
  r.app.on_button(hg::Button::Talk, false);
  CHECK(r.app.screen() == hg::Screen::Thinking && r.app.model().hero);
  // Audio before text: the mascot speaks; text arrives: the reply takes the screen.
  r.server(R"({"type":"audio.start","stream":2,"rate":16000,"format":"pcm16"})");
  CHECK(r.app.screen() == hg::Screen::Responding && r.app.model().hero);
  r.server(R"({"type":"reply","text":"Done."})");
  CHECK(!r.app.model().hero);
}

TEST("app: a finished reply stays readable, then the mascot returns; UP brings it back") {
  Rig r;
  r.bring_online(true);
  r.server(R"({"type":"turn.start","turn":"t"})");
  r.server(R"({"type":"reply","turn":"t","text":"Here is the answer."})");
  r.server(R"({"type":"turn.end","turn":"t","outcome":"success"})");
  r.advance(200);
  CHECK(r.app.screen() == hg::Screen::Ready);
  CHECK(!r.app.model().hero);
  CHECK_EQ(r.app.model().body, std::string("Here is the answer."));
  r.advance(21000);
  CHECK(r.app.model().hero);
  r.app.on_button(hg::Button::Up, true);
  CHECK(!r.app.model().hero);
  CHECK_EQ(r.app.model().body, std::string("Here is the answer."));
}

TEST("app: hero animation redraws only a slice of the screen") {
  Rig r;
  r.bring_online(true);
  r.advance(200);
  int flushes = r.fake.flushes, rows = r.fake.flushed_rows;
  r.advance(6000);  // at least one blink cycle, nothing else changing
  flushes = r.fake.flushes - flushes;
  rows = r.fake.flushed_rows - rows;
  CHECK(flushes > 0);
  // Each blink flushes only the eye rows (~25 of the 196-row mascot area).
  CHECK(rows / flushes < 60);
}

TEST("app: holding CANCEL starts a new session; a short press still cancels") {
  Rig r;
  r.bring_online(true);
  r.server(R"({"type":"turn.start","turn":"t1"})");
  CHECK(r.app.screen() == hg::Screen::Thinking);
  r.app.on_button(hg::Button::Cancel, true);
  r.advance(200);
  r.app.on_button(hg::Button::Cancel, false);
  CHECK(r.fake.last("cancel") != nullptr);
  CHECK(r.fake.last("session.new") == nullptr);

  r.fake.sent.clear();
  r.app.on_button(hg::Button::Cancel, true);
  r.advance(1000);
  CHECK(r.app.model().hint.find("New session in") == 0);  // countdown while holding
  CHECK(r.fake.last("session.new") == nullptr);
  r.advance(1200);
  CHECK(r.fake.last("session.new") != nullptr);  // fires without waiting for release
  CHECK(r.app.screen() == hg::Screen::Thinking);
  r.app.on_button(hg::Button::Cancel, false);
  CHECK(r.fake.last("cancel") == nullptr);  // the release does not also cancel
}

TEST("app: a new session discards a recording in progress") {
  Rig r;
  r.bring_online(true);
  r.app.on_button(hg::Button::Talk, true);
  CHECK(r.fake.mic_on);
  CHECK(r.app.console("new-session") == "@ok new-session");
  CHECK(!r.fake.mic_on);
  CHECK(r.fake.last("audio.cancel") != nullptr);
  CHECK(r.fake.last("session.new") != nullptr);
}

TEST("app: rendering is deterministic for the same model") {
  Rig a, b;
  a.bring_online(true);
  b.bring_online(true);
  a.server(R"({"type":"reply","text":"Hello from Hermes"})");
  b.server(R"({"type":"reply","text":"Hello from Hermes"})");
  a.advance(300);
  b.advance(300);
  CHECK(a.fake.fb == b.fake.fb);
  CHECK(a.fake.flushes > 0);
}

TEST("app: a question from Hermes shows the mascot with TALK/CANCEL answers") {
  Rig r;
  r.bring_online(true);
  r.server(R"({"type":"turn.start","turn":"t"})");
  r.server(R"({"type":"prompt","id":"q1","title":"Confirm /new","text":"This starts a fresh session."})");
  CHECK(r.app.screen() == hg::Screen::Prompt);
  CHECK(r.app.model().hero);
  CHECK_EQ(r.app.model().headline, std::string("Confirm /new"));
  CHECK_EQ(r.app.model().yes, std::string("TALK: Yes"));
  CHECK_EQ(r.app.model().no, std::string("CANCEL: No"));
  // A press that lands as the question appears was meant for something else.
  r.app.on_button(hg::Button::Talk, true);
  r.app.on_button(hg::Button::Talk, false);
  CHECK(r.fake.last("prompt.reply") == nullptr);
  CHECK(r.app.screen() == hg::Screen::Prompt);
  r.advance(700);
  r.app.on_button(hg::Button::Talk, true);
  const Value* reply = r.fake.last("prompt.reply");
  CHECK(reply != nullptr);
  if (!reply) return;
  CHECK_EQ((*reply)["id"].as_string(), std::string("q1"));
  CHECK_EQ((*reply)["answer"].as_string(), std::string("yes"));
  CHECK(!r.fake.mic_on);  // answering does not start a recording
  r.app.on_button(hg::Button::Talk, false);
  CHECK(r.app.screen() == hg::Screen::Thinking);
}

TEST("app: CANCEL answers no and holding it does not start a new session") {
  Rig r;
  r.bring_online(true);
  r.server(R"({"type":"prompt","id":"q2","title":"Allow command?","text":"rm -rf build"})");
  r.advance(700);
  r.app.on_button(hg::Button::Cancel, true);
  r.advance(2500);
  CHECK(r.fake.last("session.new") == nullptr);
  r.app.on_button(hg::Button::Cancel, false);
  const Value* reply = r.fake.last("prompt.reply");
  CHECK(reply && (*reply)["answer"].as_string() == "no");
  CHECK(r.app.screen() == hg::Screen::Ready);
}

TEST("app: a question waits for a recording, and can be withdrawn or expire") {
  Rig r;
  r.bring_online(true);
  r.app.on_button(hg::Button::Talk, true);
  r.server(R"({"type":"prompt","id":"q3","text":"Continue?"})");
  CHECK(r.app.screen() == hg::Screen::Listening);
  r.advance(500);
  r.app.on_button(hg::Button::Talk, false);
  CHECK(r.fake.last("audio.end") != nullptr);
  CHECK(r.app.screen() == hg::Screen::Prompt);
  CHECK(r.app.status_json().find("\"prompt\":\"q3\"") != std::string::npos);

  r.server(R"({"type":"prompt.close","id":"other"})");
  CHECK(r.app.screen() == hg::Screen::Prompt);
  r.server(R"({"type":"prompt.close","id":"q3"})");
  CHECK(r.app.screen() != hg::Screen::Prompt);

  r.server(R"({"type":"prompt","id":"q4","text":"Quick?","ttl_s":5})");
  CHECK(r.app.screen() == hg::Screen::Prompt);
  r.advance(5100);
  CHECK(r.app.screen() != hg::Screen::Prompt);
  CHECK(r.fake.last("prompt.reply") == nullptr);  // expiry is silent; Hermes times out on its own

  r.server(R"({"type":"prompt","id":"q5","text":"Via console?"})");
  CHECK(r.app.console("yes") == "@ok yes");
  CHECK(r.fake.last("prompt.reply") && (*r.fake.last("prompt.reply"))["id"].as_string() == "q5");
  CHECK(r.app.console("no") == "@error no question to answer");
}

TEST("app: connection, pairing and setup screens show the mascot") {
  Rig r;
  r.app.begin();
  r.app.on_network(true, "wifi");
  r.advance(1000);
  CHECK(r.app.screen() == hg::Screen::Connecting && r.app.model().hero);
  r.app.on_transport_open();
  r.server(R"({"type":"challenge","nonce":"bm9uY2U=","enrolled":false})");
  r.server(R"({"type":"welcome","session":"s1","heartbeat_s":20,"paired":false})");
  CHECK(r.app.screen() == hg::Screen::Pairing && r.app.model().hero);
  r.server(R"({"type":"pairing","code":"ABCD2345","command":"hermes pairing approve gadget ABCD2345"})");
  CHECK(r.app.model().headline.find("ABCD2345") != std::string::npos);
  CHECK(r.app.model().detail.find("hermes pairing approve gadget ABCD2345") != std::string::npos);
  CHECK(r.app.model().caption_lines >= 3);

  Rig unset("");
  unset.app.begin();
  unset.app.on_network(true);
  unset.advance(1000);
  CHECK(unset.app.screen() == hg::Screen::Error && unset.app.model().hero);
}

TEST("app: short cards sit under the mascot, long ones use the text layout") {
  Rig r;
  r.bring_online(true);
  r.server(R"({"type":"display","title":"Timer","body":"Pasta: 9 min"})");
  CHECK(r.app.screen() == hg::Screen::Card && r.app.model().hero);
  CHECK_EQ(r.app.model().detail, std::string("Pasta: 9 min"));
  std::string body;
  for (int i = 0; i < 30; ++i) body += "line " + std::to_string(i) + " of a long card. ";
  r.server(R"({"type":"display","title":"Notes","ttl_s":0,"body":")" + body + "\"}");
  CHECK(r.app.screen() == hg::Screen::Card && !r.app.model().hero);
  CHECK_EQ(r.app.model().scroll, 0);
  r.advance(8100);
  CHECK(r.app.model().scroll > 0);  // pages without scroll buttons
}

TEST("app: long replies page themselves; UP/DOWN pauses the paging") {
  Rig r;
  r.bring_online(true);
  std::string text;
  for (int i = 0; i < 40; ++i) text += "sentence " + std::to_string(i) + " of a long answer. ";
  r.server(R"({"type":"turn.start","turn":"t"})");
  r.server(R"({"type":"reply","turn":"t","text":")" + text + "\"}");
  r.server(R"({"type":"turn.end","turn":"t","outcome":"success"})");
  CHECK_EQ(r.app.model().scroll, 0);
  r.advance(4000);
  CHECK_EQ(r.app.model().scroll, 0);  // the first page gets its reading time
  r.advance(4100);
  int page2 = r.app.model().scroll;
  CHECK(page2 > 0);
  r.advance(8100);
  CHECK(r.app.model().scroll > page2);

  r.server(R"({"type":"ping","ts":1})");  // keep the heartbeat alive through the long waits
  int before = r.app.model().scroll;
  r.app.on_button(hg::Button::Up, true);
  int manual = r.app.model().scroll;
  CHECK(manual < before);
  r.advance(12000);
  CHECK_EQ(r.app.model().scroll, manual);  // paused after a manual scroll
  CHECK(!r.app.model().hero);              // and the reply is still on screen

  // Paging stops at the last page, which stays readable before the mascot returns.
  int last = -1;
  for (int i = 0; i < 40 && r.app.model().scroll != last; ++i) {
    last = r.app.model().scroll;
    r.server(R"({"type":"ping","ts":1})");
    r.advance(9000);
  }
  CHECK(!r.app.model().hero);
  r.advance(25000);
  CHECK(r.app.model().hero);
}

TEST("app: on a round panel everything stays inside the circle") {
  Rig r;
  r.fake.make_round(466);
  r.bring_online(true);
  const Value* hello = r.fake.last("hello");
  CHECK(hello && (*hello)["caps"]["display"]["shape"].as_string() == "round");
  r.server(R"({"type":"reply","text":"A long enough answer to fill several lines of the round screen with text."})");
  r.advance(300);
  CHECK(r.app.model().body.size() > 0);
  // Every pixel outside the circle is still the background colour.
  const uint16_t bg = r.fake.fb[static_cast<size_t>(233 * 466)];  // left edge of the middle row
  int stray = 0, drawn = 0;
  for (int y = 0; y < 466; ++y) {
    for (int x = 0; x < 466; ++x) {
      int dx = 2 * x + 1 - 466, dy = 2 * y + 1 - 466;
      bool lit = r.fake.fb[static_cast<size_t>(y * 466 + x)] != bg;
      if (dx * dx + dy * dy > 466 * 466) stray += lit;
      else drawn += lit;
    }
  }
  CHECK_EQ(stray, 0);
  CHECK(drawn > 1000);  // and the reply really was drawn inside
}

TEST("touch: hold to talk, lift to send") {
  Rig r(Rig::touch_profile());
  r.bring_online(true);
  CHECK_EQ(r.app.model().hint, std::string("Hold the screen to talk"));
  hg::TouchGestures touch(r.app);
  touch.update(true, 200, 200, r.fake.clock);
  CHECK(!r.fake.mic_on);  // not yet: it could still become a swipe
  r.advance(150);
  touch.tick(r.fake.clock);
  CHECK(r.fake.mic_on);
  CHECK_EQ(r.app.model().detail, std::string("Lift your finger to send"));
  r.advance(600);
  touch.update(true, 204, 203, r.fake.clock);  // a wobbly finger is still a hold
  touch.update(false, 0, 0, r.fake.clock);
  CHECK(!r.fake.mic_on);
  CHECK(r.fake.last("audio.end") != nullptr);
}

TEST("touch: swipe down while holding discards the recording") {
  Rig r(Rig::touch_profile());
  r.bring_online(true);
  hg::TouchGestures touch(r.app);
  touch.update(true, 200, 150, r.fake.clock);
  r.advance(500);
  touch.tick(r.fake.clock);
  CHECK(r.fake.mic_on);
  touch.update(true, 205, 260, r.fake.clock);
  CHECK(!r.fake.mic_on);
  CHECK(r.fake.last("audio.cancel") != nullptr);
  touch.update(false, 0, 0, r.fake.clock);
  CHECK(r.fake.last("audio.end") == nullptr);
}

TEST("touch: tap answers yes, swipe answers no, sideways drags do nothing") {
  Rig r(Rig::touch_profile());
  r.bring_online(true);
  hg::TouchGestures touch(r.app);
  r.server(R"({"type":"prompt","id":"q1","title":"Allow?","text":"rm -rf build"})");
  CHECK_EQ(r.app.model().yes, std::string("Tap: Yes"));
  CHECK_EQ(r.app.model().no, std::string("Swipe: No"));
  r.advance(700);
  touch.update(true, 100, 100, r.fake.clock);  // sideways: ignored
  touch.update(true, 200, 104, r.fake.clock);
  r.advance(300);
  touch.tick(r.fake.clock);
  touch.update(false, 0, 0, r.fake.clock);
  CHECK(r.fake.last("prompt.reply") == nullptr);
  CHECK(!r.fake.mic_on);

  touch.update(true, 200, 200, r.fake.clock);  // quick tap
  r.advance(40);
  touch.update(false, 0, 0, r.fake.clock);
  const Value* yes = r.fake.last("prompt.reply");
  CHECK(yes && (*yes)["answer"].as_string() == "yes");

  r.server(R"({"type":"prompt","id":"q2","title":"Allow?","text":"git push --force"})");
  r.advance(700);
  touch.update(true, 200, 120, r.fake.clock);
  r.advance(30);
  touch.update(true, 202, 220, r.fake.clock);
  touch.update(false, 0, 0, r.fake.clock);
  const Value* no = r.fake.last("prompt.reply");
  CHECK(no && (*no)["id"].as_string() == "q2" && (*no)["answer"].as_string() == "no");
}

TEST("touch: swipes can be turned off; board settings go through the console") {
  Rig r(Rig::touch_profile());
  std::string changed;
  r.app.on_setting_changed = [&](std::string_view key) { changed = std::string(key); };
  r.bring_online(true);
  CHECK_EQ(r.app.console("set touch_cancel pwr"), std::string("@ok touch_cancel"));
  CHECK_EQ(changed, std::string("touch_cancel"));
  CHECK(r.app.console("get touch_cancel").find("\"pwr\"") != std::string::npos);
  CHECK(r.app.console("help").find("touch_cancel") != std::string::npos);
  CHECK_EQ(r.app.console("set nonsense 1"), std::string("@error unknown key"));

  hg::TouchGestures touch(r.app);
  touch.set_swipe_cancel(false);
  r.server(R"({"type":"turn.start","turn":"t"})");
  touch.update(true, 200, 100, r.fake.clock);
  touch.update(true, 200, 260, r.fake.clock);
  touch.update(false, 0, 0, r.fake.clock);
  CHECK(r.fake.last("cancel") == nullptr);
}

TEST("settings: physical chord opens locally and saves volume, brightness and talk mode") {
  Rig r;
  r.fake.backlight = true;
  r.app.begin();
  r.app.on_button(hg::Button::Cancel, true);
  r.app.on_button(hg::Button::Talk, true);
  r.advance(1000);
  CHECK(r.app.screen() == hg::Screen::Settings);
  r.app.on_button(hg::Button::Talk, false);
  r.app.on_button(hg::Button::Cancel, false);
  CHECK_EQ(r.app.model().detail, std::string("Speaker volume"));
  r.app.on_button(hg::Button::Talk, true);
  r.app.on_button(hg::Button::Talk, false);
  CHECK_EQ(r.fake.volume, 80);
  CHECK_EQ(r.fake.kv["volume"], std::string("80"));
  r.app.console("cancel");
  r.app.console("talk");
  r.app.console("release");
  CHECK_EQ(r.fake.brightness, 10);
  CHECK_EQ(r.fake.kv["brightness"], std::string("10"));
  r.app.console("cancel");
  r.app.console("talk");
  r.app.console("release");
  CHECK_EQ(r.fake.kv["talk_mode"], std::string("tap"));
  r.app.on_button(hg::Button::Talk, true);
  r.app.on_button(hg::Button::Cancel, true);
  r.advance(1000);
  r.app.on_button(hg::Button::Cancel, false);
  r.app.on_button(hg::Button::Talk, false);
  CHECK(!r.app.settings_open());
  CHECK_EQ(r.fake.kv["talk_mode"], std::string("tap"));
  Rig reboot;
  reboot.fake.backlight = true;
  reboot.fake.kv = r.fake.kv;
  reboot.app.begin();
  CHECK_EQ(reboot.fake.volume, 80);
  CHECK_EQ(reboot.fake.brightness, 10);
  CHECK_EQ(reboot.app.device_id(), r.app.device_id());
}

TEST("settings: hardware checks are local and prompts release the microphone") {
  Rig r;
  r.bring_online(true);
  CHECK(r.app.open_settings());
  for (int i = 0; i < 3; ++i) r.app.console("cancel");
  CHECK_EQ(r.app.model().detail, std::string("Microphone check"));
  r.app.console("talk");
  r.app.console("release");
  CHECK(r.fake.mic_on);
  const int16_t samples[] = {32767, -32767, 32767, -32767};
  r.app.on_mic_samples(samples, 4);
  CHECK_EQ(r.app.model().level, uint8_t(99));
  CHECK(r.app.model().body.find("Local only") != std::string::npos);
  CHECK(r.fake.sent_binary.empty());
  CHECK(r.fake.last("audio.start") == nullptr);
  r.app.console("cancel");
  CHECK(!r.fake.mic_on);
  CHECK_EQ(r.app.model().detail, std::string("Speaker check"));
  r.app.console("talk");
  r.app.console("release");
  r.advance(20);
  CHECK_EQ(r.fake.spk_samples, size_t(4000));
  CHECK(r.app.model().body.find("Tone finished") != std::string::npos);
  r.app.console("cancel");
  r.app.console("talk");
  r.app.console("release");
  CHECK(r.app.model().color_test);
  CHECK_EQ(r.fake.fb[100 * 320 + 10], uint16_t(0xf800));
  CHECK_EQ(r.fake.fb[100 * 320 + 150], uint16_t(0x001f));
  r.app.close_settings();
  CHECK(r.app.open_settings());
  for (int i = 0; i < 3; ++i) r.app.console("cancel");
  r.app.console("talk");
  r.app.console("release");
  CHECK(r.fake.mic_on);
  r.server(R"({"type":"prompt","id":"local-check","text":"Continue?"})");
  CHECK(!r.fake.mic_on);
  CHECK(r.app.screen() == hg::Screen::Prompt);
  CHECK(!r.app.open_settings());
}

TEST("settings: title hold and menu swipe work without starting a recording") {
  Rig r(Rig::touch_profile());
  r.bring_online(true);
  hg::TouchGestures touch(r.app);
  touch.set_swipe_cancel(false);
  touch.update(true, 100, 4, r.fake.clock);
  r.advance(1100);
  touch.tick(r.fake.clock);
  touch.update(false, 0, 0, r.fake.clock);
  CHECK(r.app.screen() == hg::Screen::Settings);
  CHECK(!r.fake.mic_on);
  CHECK_EQ(r.app.model().detail, std::string("Speaker volume"));
  touch.update(true, 100, 80, r.fake.clock);
  touch.update(true, 100, 150, r.fake.clock + 30);
  touch.update(false, 0, 0, r.fake.clock + 40);
  CHECK_EQ(r.app.model().detail, std::string("Screen brightness"));
  touch.update(true, 100, 4, r.fake.clock);
  r.advance(1100);
  touch.tick(r.fake.clock);
  touch.update(false, 0, 0, r.fake.clock);
  CHECK(!r.app.settings_open());
  CHECK(r.app.screen() == hg::Screen::Ready);
}

TEST("power: idle screen dims, sleeps and consumes the wake input without recording") {
  Rig r;
  r.fake.backlight = true;
  r.bring_online(true);
  CHECK_EQ(r.app.console("set screen_timeout 30"), std::string("@ok screen_timeout"));
  CHECK_EQ(r.app.console("set screen_timeout -1"), std::string("@error screen_timeout must be 0..3600 seconds"));
  r.advance(15000);
  CHECK_EQ(r.fake.brightness, 10);
  r.advance(15000);
  CHECK_EQ(r.fake.brightness, 0);
  r.app.on_button(hg::Button::Talk, true);
  CHECK_EQ(r.fake.brightness, 100);
  CHECK(!r.fake.mic_on);
  r.app.on_button(hg::Button::Talk, false);
  CHECK(r.fake.last("audio.start") == nullptr);
  r.app.console("talk");
  CHECK(r.fake.mic_on);
  r.advance(1000);
  r.app.console("cancel");
  r.app.console("release");
  r.server(R"({"type":"ping"})");
  r.advance(30000);
  CHECK_EQ(r.fake.brightness, 0);
  r.server(R"({"type":"prompt","id":"wake","text":"Continue?"})");
  CHECK_EQ(r.fake.brightness, 100);
  CHECK(r.app.screen() == hg::Screen::Prompt);
  r.advance(30000);
  CHECK_EQ(r.fake.brightness, 100);
}

TEST("power: failed readings replace stale data and shutdown requires a second local selection") {
  struct Battery : hg::Power {
    bool failed = false;
    int shutdowns = 0;
    std::optional<hg::PowerStatus> read() override {
      if (failed) return std::nullopt;
      return hg::PowerStatus{true, 3850, 65, false, false};
    }
    bool power_off() override { ++shutdowns; return true; }
  } battery;
  Rig r;
  r.hal.power = &battery;
  r.bring_online(true);
  Value status;
  CHECK(hg::json::parse(r.app.status_json(), status));
  CHECK_EQ(status["power"]["battery_mv"].as_int(), int64_t(3850));
  r.advance(5000);
  CHECK_EQ((*r.fake.last("state"))["sensors"]["battery_percent"].as_int(), int64_t(65));
  battery.failed = true;
  r.advance(5000);
  CHECK(hg::json::parse(r.app.status_json(), status));
  CHECK(!status["power"]["available"].as_bool());
  CHECK(status["power"]["battery_mv"].is_null());
  CHECK((*r.fake.last("state"))["sensors"]["battery_mv"].is_null());
  r.app.open_settings();
  for (int i = 0; i < 10; ++i) r.app.console("cancel");
  CHECK_EQ(r.app.model().detail, std::string("Power off"));
  r.app.console("talk"); r.app.console("release");
  CHECK_EQ(battery.shutdowns, 0);
  r.app.console("talk"); r.app.console("release");
  CHECK_EQ(battery.shutdowns, 1);
}

TEST("power: a peripheral rail cannot be selected as device power-off") {
  struct PeripheralRail : hg::Power {
    int shutdowns = 0;
    std::optional<hg::PowerStatus> read() override { return hg::PowerStatus{}; }
    bool can_power_off() const override { return false; }
    bool power_off() override { ++shutdowns; return true; }
  } rail;
  Rig r;
  r.hal.power = &rail;
  r.bring_online(true);
  CHECK(r.app.open_settings());
  for (int i = 0; i < 10; ++i) r.app.console("cancel");
  CHECK(r.app.model().detail != "Power off");
  r.app.console("talk"); r.app.console("release");
  r.app.console("talk"); r.app.console("release");
  CHECK_EQ(rail.shutdowns, 0);
}

TEST("Wi-Fi setup: bounded credentials require the current session and never replace valid output on failure") {
  hg::WifiCredentials out;
  std::string error;
  const std::string body = R"({"nonce":"current","ssid":"Kitchen","password":"example pass","server":"ws://192.168.1.20:8765/gadget"})";
  CHECK(hg::parse_wifi_setup(body, "current", out, error));
  CHECK_EQ(std::string(out.ssid), std::string("Kitchen"));
  CHECK_EQ(std::string(out.password), std::string("example pass"));
  CHECK_EQ(std::string(out.server), std::string("ws://192.168.1.20:8765/gadget"));
  CHECK(!hg::parse_wifi_setup(body, "expired", out, error));
  CHECK(!hg::parse_wifi_setup(body, "", out, error));
  for (const std::string& url : {"http://example.com", "ws://", "ws://host:0", "ws://host:65536",
                                 "ws://user:pass@host", "ws://host/#secret", "ws://host\n/path"}) {
    Value form;
    CHECK(hg::json::parse(body, form));
    form.set("server", url);
    CHECK(!hg::parse_wifi_setup(form.dump(), "current", out, error));
  }
  Value form;
  CHECK(hg::json::parse(body, form));
  form.set("ssid", std::string(33, 'x'));
  CHECK(!hg::parse_wifi_setup(form.dump(), "current", out, error));
  form.set("ssid", std::string("x\0y", 3));
  CHECK(!hg::parse_wifi_setup(form.dump(), "current", out, error));
  CHECK_EQ(std::string(out.ssid), std::string("Kitchen"));
  form.set("ssid", std::string(32, 'x')).set("password", "").set("server", "wss://[::1]:8765/gadget");
  CHECK(hg::parse_wifi_setup(form.dump(), "current", out, error));
  CHECK_EQ(std::string(out.password), std::string());
  form.set("password", "short");
  CHECK(!hg::parse_wifi_setup(form.dump(), "current", out, error));
  form.set("password", std::string(64, 'a'));
  CHECK(hg::parse_wifi_setup(form.dump(), "current", out, error));
  form.set("password", std::string(64, 'z'));
  CHECK(!hg::parse_wifi_setup(form.dump(), "current", out, error));
  CHECK(!hg::parse_wifi_setup(std::string(1025, ' '), "current", out, error));
}

TEST("Wi-Fi setup: private instructions stay out of diagnostics and prompts close the temporary network") {
  Rig r(Rig::touch_profile());
  r.bring_online(true);
  int closed = 0;
  r.app.on_wifi_setup = [] { return "Network: Hermes-test\nPassword: private-setup-key"; };
  r.app.on_wifi_setup_close = [&] { ++closed; };
  CHECK(r.app.start_wifi_setup());
  CHECK(r.app.screen() == hg::Screen::Setup);
  CHECK(r.app.model().body.find("private-setup-key") != std::string::npos);
  CHECK(r.app.console("diag").find("private-setup-key") == std::string::npos);
  CHECK(r.app.status_json().find("private-setup-key") == std::string::npos);
  r.app.console("talk"); r.app.console("release");
  CHECK(!r.fake.mic_on);
  hg::TouchGestures touch(r.app);
  touch.set_swipe_cancel(false);
  touch.update(true, 100, 50, r.fake.clock);
  touch.update(true, 100, 150, r.fake.clock + 30);
  touch.update(false, 0, 0, r.fake.clock + 40);
  CHECK_EQ(closed, 1);
  CHECK(!r.app.wifi_setup_open());
  CHECK(r.app.start_wifi_setup());
  r.server(R"({"type":"prompt","id":"setup-test","text":"Continue?"})");
  CHECK_EQ(closed, 2);
  CHECK(!r.app.wifi_setup_open());
  CHECK(r.app.screen() == hg::Screen::Prompt);
  CHECK(!r.app.start_wifi_setup());
}

TEST("Wi-Fi setup: opening from USB releases an active talk button") {
  Rig r;
  r.bring_online(true);
  r.app.console("set screen_timeout 30");
  r.app.on_wifi_setup = [] { return "Temporary setup network"; };
  r.app.on_button(hg::Button::Talk, true);
  CHECK(r.fake.mic_on);
  CHECK(r.app.start_wifi_setup());
  CHECK(!r.fake.mic_on);
  r.app.on_button(hg::Button::Talk, false);
  r.app.on_button(hg::Button::Cancel, true);
  r.app.on_button(hg::Button::Cancel, false);
  CHECK(!r.app.wifi_setup_open());
  r.advance(30000);
  CHECK_EQ(r.fake.brightness, 0);
}

TEST("habitat: opt-in, core-driven round framebuffer, normal screen restored") {
  Rig r(Rig::touch_profile());
  r.fake.make_round(466);
  r.app.begin();
  r.advance(1000);
  CHECK_EQ(r.app.screen(), hg::Screen::Offline);
  CHECK_EQ(r.app.console("habitat on"), "@ok habitat");
  CHECK_EQ(r.app.screen(), hg::Screen::Habitat);
  const auto* background = hg::habitat_assets::background();
  uint16_t top = background ? background->pixels[(20 * background->height / 466) * background->width + background->width / 2]
                            : hg::rgb565(133, 208, 215);
  uint16_t bottom = background ? background->pixels[(450 * background->height / 466) * background->width + background->width / 2]
                               : hg::rgb565(80, 178, 211);
  // Scenery reaches both poles of the circular glass, outside the HUD overlays.
  CHECK_EQ(r.fake.fb[20 * 466 + 233], top);
  CHECK_EQ(r.fake.fb[450 * 466 + 233], bottom);
  auto pixels = r.fake.fb;
  r.advance(3000);
  CHECK(r.fake.fb != pixels);
  CHECK(!r.fake.mic_on);
  CHECK_EQ(r.app.console("habitat off"), "@ok habitat");
  CHECK_EQ(r.app.screen(), hg::Screen::Offline);
}

TEST("habitat: touch opens native card without reading, card buttons and swipe work") {
  Rig r(Rig::touch_profile());
  r.fake.make_round(466);
  r.app.begin();
  r.app.console("habitat on");
  r.app.console("habitat notify palmon");
  hg::TouchGestures touch(r.app);
  Value state;
  CHECK(hg::json::parse(r.app.console("habitat status").substr(9), state));
  int x = static_cast<int>(state["residents"].at(4)["x"].as_int());
  int y = static_cast<int>(state["residents"].at(4)["y"].as_int());
  touch.update(true, x, y, r.fake.clock);
  r.advance(200);
  touch.tick(r.fake.clock);  // A habitat hold must never press TALK.
  CHECK(!r.fake.mic_on);
  touch.update(false, x, y, r.fake.clock);
  CHECK(hg::json::parse(r.app.console("habitat status").substr(9), state));
  CHECK_EQ(state["selected"].as_int(), 4);
  CHECK_EQ(state["residents"].at(4)["pending"].as_int(), 1);
  touch.update(true, 310, 414, r.fake.clock);
  touch.update(false, 310, 414, r.fake.clock);
  CHECK(hg::json::parse(r.app.console("habitat status").substr(9), state));
  CHECK_EQ(state["residents"].at(4)["pending"].as_int(), 0);
  int held_x = static_cast<int>(state["residents"].at(4)["x"].as_int());
  int held_y = static_cast<int>(state["residents"].at(4)["feet"].as_int());
  r.advance(500);  // Reading the notice does not move the selected card's resident.
  CHECK(hg::json::parse(r.app.console("habitat status").substr(9), state));
  CHECK_EQ(state["residents"].at(4)["x"].as_int(), held_x);
  CHECK_EQ(state["residents"].at(4)["feet"].as_int(), held_y);
  touch.update(true, 220, 320, r.fake.clock);
  touch.update(true, 220, 390, r.fake.clock + 10);
  touch.update(false, 220, 390, r.fake.clock + 20);
  CHECK(hg::json::parse(r.app.console("habitat status").substr(9), state));
  CHECK_EQ(state["selected"].as_int(), -1);
}

TEST("habitat: deterministic tick, freeze and partial redraw") {
  FakeHal a, b;
  a.make_round(466);
  b.make_round(466);
  hg::Habitat ha(a), hb(b);
  ha.enable(0); hb.enable(0);
  ha.render(); hb.render();
  CHECK_EQ(a.flushed_rows, 466);
  for (uint32_t time = 100; time <= 3000; time += 100) {
    ha.tick(time); hb.tick(time);
    ha.render(); hb.invalidate(); hb.render();
    CHECK(a.fb == b.fb);  // Partial updates must equal a full redraw.
  }
  CHECK_EQ(ha.status().dump(), hb.status().dump());
  CHECK(a.fb == b.fb);
  int before = a.flushed_rows;
  ha.tick(3100); ha.render();
  CHECK(a.flushed_rows - before < 466);
  ha.pause(); ha.render();
  auto paused = ha.status().dump();
  ha.tick(5000);
  CHECK_EQ(ha.status().dump(), paused);
  ha.pause(); ha.motion();
  auto positions = ha.status()["residents"].dump();
  ha.tick(5100);
  CHECK_EQ(ha.status()["residents"].dump(), positions);
  for (uint32_t time = 5200; time < 30000; time += 100) ha.tick(time);
  CHECK(ha.status()["residents"].at(4)["pending"].as_int() > 0);
  CHECK(!ha.notify("not-a-resident"));
}

TEST("habitat: other panels remain on the normal UI") {
  Rig r;
  r.app.begin();
  CHECK(r.app.console("habitat on").find("@error") == 0);
  CHECK(r.app.screen() != hg::Screen::Habitat);
}

TEST("habitat: never hides pairing") {
  Rig r(Rig::touch_profile());
  r.fake.make_round(466);
  r.bring_online(false);
  CHECK(r.app.console("habitat on").find("@error") == 0);
  CHECK(r.app.screen() != hg::Screen::Habitat);
}

TEST("habitat: free walking stays on sand, separated, ordered and never teleports") {
  FakeHal fake;
  fake.make_round(466);
  hg::Habitat habitat(fake);
  habitat.enable(0);
  int min_x[8], max_x[8], min_y[8], max_y[8], last_x[8], last_y[8];
  auto initial = habitat.status();
  for (size_t i = 0; i < 8; ++i) {
    min_x[i] = max_x[i] = last_x[i] = static_cast<int>(initial["residents"].at(i)["x"].as_int());
    min_y[i] = max_y[i] = last_y[i] = static_cast<int>(initial["residents"].at(i)["feet"].as_int());
  }
  for (uint32_t time = 100; time <= 180000; time += 100) {
    habitat.tick(time);
    auto state = habitat.status();
    for (size_t i = 0; i < 8; ++i) {
      const auto& r = state["residents"].at(i);
      int x = static_cast<int>(r["x"].as_int()), y = static_cast<int>(r["feet"].as_int());
      CHECK(y >= 270 && y <= 350);
      CHECK(habitat.walkable(i, x, y));
      CHECK(std::abs(x - last_x[i]) <= 2 && std::abs(y - last_y[i]) <= 2);
      min_x[i] = std::min(min_x[i], x); max_x[i] = std::max(max_x[i], x);
      min_y[i] = std::min(min_y[i], y); max_y[i] = std::max(max_y[i], y);
      last_x[i] = x; last_y[i] = y;
      if (r["walking"].as_bool()) {
        int p = static_cast<int>(r["pose"].as_int());
        CHECK(i >= 6 ? (p == 4 || p == 5) : (p == 6 || p == 7));
      }
      for (size_t j = 0; j < i; ++j) {
        int dx = x - static_cast<int>(state["residents"].at(j)["x"].as_int());
        int dy = y - static_cast<int>(state["residents"].at(j)["feet"].as_int());
        // Ground footprint is 50x34; billboards can overlap at different depths.
        // Leave 2px tolerance only for rounding exact Q8 support positions.
        CHECK(dx * dx * 32 * 32 + dy * dy * 48 * 48 >= 48 * 48 * 32 * 32);
      }
      if (i) {
        auto previous = state["draw_order"].at(i - 1).as_int();
        auto current = state["draw_order"].at(i).as_int();
        CHECK(state["residents"].at(previous)["feet"].as_int() <= state["residents"].at(current)["feet"].as_int());
      }
    }
  }
  for (size_t i = 0; i < 8; ++i) if (i != 4) {  // Palmon waits for its demo notice.
    CHECK(max_x[i] - min_x[i] > 10);
    CHECK(max_y[i] - min_y[i] > 5);
  }
  auto state = habitat.status();
  int total = 0;
  for (const auto& resident : state["residents"].elements()) total += resident["pending"].as_int();
  CHECK_EQ(total, 1);
  CHECK_EQ(state["residents"].at(4)["pending"].as_int(), 1);
}

TEST("habitat: 20Hz movement has calm facing and bounded velocities") {
  FakeHal fake;
  fake.make_round(466);
  hg::Habitat habitat(fake);
  habitat.enable(0);
  int facing[8], last_change[8], changes = 0, gait_start[8] = {};
  bool walking[8] = {}, was_walk[8] = {};
  auto initial = habitat.status();
  for (size_t i = 0; i < 8; ++i) {
    facing[i] = static_cast<int>(initial["residents"].at(i)["direction"].as_int());
    last_change[i] = -10000;
  }
  for (uint32_t time = 50; time <= 180000; time += 50) {
    habitat.tick(time);
    auto state = habitat.status();
    CHECK_EQ(state["frame"].as_int(), time / 50);
    for (size_t i = 0; i < 8; ++i) {
      const auto& r = state["residents"].at(i);
      int direction = static_cast<int>(r["direction"].as_int());
      if (direction != facing[i]) {
        CHECK(static_cast<int>(time) - last_change[i] >= 800);
        last_change[i] = static_cast<int>(time);
        facing[i] = direction;
        ++changes;
      }
      CHECK(std::abs(r["vx"].as_int()) <= 224);
      CHECK(std::abs(r["vy"].as_int()) <= 224);
      bool is_walk = r["mode"].as_string() == "walk";
      bool gait = r["walking"].as_bool();
      if (is_walk && was_walk[i] && walking[i] && !gait)
        CHECK(static_cast<int>(time) - gait_start[i] >= 250);
      if (gait && !walking[i]) gait_start[i] = static_cast<int>(time);
      walking[i] = gait;
      was_walk[i] = is_walk;
    }
  }
  CHECK(changes < 300);  // Regression: the old demo flipped over 2,000 times.
}

TEST("habitat: departure accelerates instead of jumping to cruising speed") {
  FakeHal fake;
  fake.make_round(466);
  hg::Habitat habitat(fake);
  habitat.enable(0);
  habitat.tick(50);
  auto state = habitat.status();
  bool started = false;
  for (const auto& r : state["residents"].elements()) {
    CHECK(std::abs(r["vx"].as_int()) <= 32);
    CHECK(std::abs(r["vy"].as_int()) <= 32);
    started |= r["moving"].as_bool();
  }
  CHECK(started);
}

TEST("habitat: typed inbox preserves requests, details and explicit responses") {
  FakeHal fake;
  fake.make_round(466);
  hg::Habitat habitat(fake);
  habitat.enable(0);
  using Kind = hg::Habitat::NoticeKind;
  CHECK(habitat.notify("palmon", Kind::Info));
  CHECK(habitat.notify("palmon", Kind::Question));
  CHECK(habitat.notify("palmon", Kind::Error));
  auto state = habitat.status();
  auto palmon = state["residents"].at(4);
  CHECK_EQ(palmon["pending"].as_int(), 3);
  CHECK(palmon["fresh"].as_bool());
  // Tap the bubble itself, not an HTML profile button.
  habitat.tap(static_cast<int>(palmon["cue_x"].as_int()), static_cast<int>(palmon["cue_y"].as_int()));
  CHECK_EQ(habitat.status()["selected"].as_int(), 4);
  CHECK_EQ(habitat.status()["residents"].at(4)["pending"].as_int(), 3);
  habitat.details();
  CHECK(habitat.status()["details"].as_bool());
  CHECK(habitat.read());
  CHECK_EQ(habitat.status()["residents"].at(4)["kind"].as_string(), "question");
  CHECK(!habitat.status()["details"].as_bool());
  CHECK(!habitat.read());
  CHECK(!habitat.answer(true));
  for (uint32_t time = 50; time <= 400; time += 50) habitat.tick(time);
  CHECK(habitat.status()["question_ready"].as_bool());
  CHECK(habitat.answer(false));
  palmon = habitat.status()["residents"].at(4);
  CHECK_EQ(palmon["kind"].as_string(), "error");
  CHECK_EQ(palmon["last_action"].as_string(), "no");
  CHECK_EQ(palmon["last_id"].as_int(), 2);
  CHECK(habitat.read());
  palmon = habitat.status()["residents"].at(4);
  CHECK_EQ(palmon["pending"].as_int(), 0);
  CHECK_EQ(palmon["last_action"].as_string(), "read");
  CHECK_EQ(palmon["last_id"].as_int(), 3);
  CHECK(!palmon["fresh"].as_bool());
}

TEST("habitat: native question buttons debounce consent even while paused") {
  FakeHal fake;
  fake.make_round(466);
  hg::Habitat habitat(fake);
  habitat.enable(0);
  CHECK(habitat.notify("biyomon", hg::Habitat::NoticeKind::Question));
  auto bird = habitat.status()["residents"].at(2);
  habitat.tap(static_cast<int>(bird["cue_x"].as_int()), static_cast<int>(bird["cue_y"].as_int()));
  habitat.pause();
  habitat.tap(327, 403);  // YES before the user has had time to see the question.
  CHECK_EQ(habitat.status()["residents"].at(2)["pending"].as_int(), 1);
  habitat.tick(400);
  CHECK(habitat.status()["question_ready"].as_bool());
  CHECK_EQ(habitat.status()["frame"].as_int(), 0);
  habitat.tap(233, 403);  // Native NO button.
  CHECK_EQ(habitat.status()["residents"].at(2)["last_action"].as_string(), "no");
  CHECK(habitat.notify("biyomon", hg::Habitat::NoticeKind::Question));
  habitat.tap(327, 403);  // Cannot accidentally answer a newly arriving question.
  CHECK_EQ(habitat.status()["residents"].at(2)["pending"].as_int(), 1);
  habitat.tick(800);
  habitat.tap(327, 403);
  CHECK_EQ(habitat.status()["residents"].at(2)["pending"].as_int(), 0);
  CHECK_EQ(habitat.status()["residents"].at(2)["last_action"].as_string(), "yes");
}

TEST("habitat: bounded queues reject overflow without losing existing notices") {
  FakeHal fake;
  fake.make_round(466);
  hg::Habitat habitat(fake);
  habitat.enable(0);
  constexpr const char* names[] = {"agumon", "gabumon", "biyomon", "tentomon", "palmon", "gomamon", "patamon", "gatomon"};
  for (const char* name : names) {
    for (int i = 0; i < 8; ++i) CHECK(habitat.notify(name, hg::Habitat::NoticeKind::Error));
    CHECK(!habitat.notify(name, hg::Habitat::NoticeKind::Question));
  }
  auto state = habitat.status();
  CHECK(state.dump().size() + 9 < 4096);  // Fits the simulator console binding.
  CHECK_EQ(state["residents"].at(0)["notice_id"].as_int(), 1);
  auto first = state["residents"].at(0);
  habitat.tap(static_cast<int>(first["cue_x"].as_int()), static_cast<int>(first["cue_y"].as_int()));
  CHECK(habitat.read());
  CHECK(habitat.notify("agumon", hg::Habitat::NoticeKind::Question));
  CHECK_EQ(habitat.status()["residents"].at(0)["pending"].as_int(), 8);
  CHECK_EQ(habitat.status()["residents"].at(0)["notice_id"].as_int(), 2);
  CHECK_EQ(habitat.status()["residents"].at(0)["kind"].as_string(), "error");
}

TEST("habitat: NEW expires but the unread bubble remains") {
  FakeHal fake;
  fake.make_round(466);
  hg::Habitat habitat(fake);
  habitat.enable(0);
  CHECK(habitat.notify("gatomon"));
  for (uint32_t time = 50; time <= 3100; time += 50) habitat.tick(time);
  auto cat = habitat.status()["residents"].at(7);
  CHECK(!cat["fresh"].as_bool());
  CHECK_EQ(cat["pending"].as_int(), 1);
  habitat.tap(static_cast<int>(cat["cue_x"].as_int()), static_cast<int>(cat["cue_y"].as_int()));
  CHECK_EQ(habitat.status()["selected"].as_int(), 7);
  CHECK_EQ(habitat.status()["residents"].at(7)["pending"].as_int(), 1);
}

TEST("habitat: ambient layers change sky and sea but never the fixed scenery") {
  if (!hg::habitat_assets::background() || !hg::habitat_assets::layer(hg::habitat_assets::Water)) return;
  FakeHal fake;
  fake.make_round(466);
  hg::Habitat habitat(fake);
  habitat.enable(0);
  for (uint32_t time = 50; time <= 4000; time += 50) { habitat.tick(time); habitat.render(); }
  auto before = fake.fb;
  for (uint32_t time = 4050; time <= 5000; time += 50) { habitat.tick(time); habitat.render(); }
  bool sky = false, water = false;
  for (int y = 0; y < 466; ++y) for (int x = 0; x < 466; ++x) {
    size_t p = static_cast<size_t>(y * 466 + x);
    if (y < 73 && before[p] != fake.fb[p]) sky = true;
    if (y >= 400 && before[p] != fake.fb[p]) water = true;
    // This band contains the fixed trees/house, no sky, people or UI.
    if (y >= 110 && y < 160) CHECK_EQ(before[p], fake.fb[p]);
  }
  CHECK(sky);
  CHECK(water);
  habitat.pause(); habitat.render();
  auto paused = fake.fb;
  habitat.tick(100000); habitat.render();
  CHECK(fake.fb == paused);
  habitat.pause(); habitat.motion(); habitat.render();
  auto reduced = fake.fb;
  for (uint32_t time = 100050; time <= 100500; time += 50) { habitat.tick(time); habitat.render(); }
  CHECK(fake.fb == reduced);
}

TEST("habitat: fast movement and slow sky redraw equal complete recomposition") {
  FakeHal a, b;
  a.make_round(466); b.make_round(466);
  hg::Habitat partial(a), full(b);
  partial.enable(0); full.enable(0);
  partial.render(); full.render();
  for (uint32_t time = 50; time <= 18000; time += 50) {
    partial.tick(time); full.tick(time);
    partial.render(); full.invalidate(); full.render();
    CHECK(a.fb == b.fb);
  }
  // Separate sky bands are cheaper than making every movement frame full-screen.
  CHECK(a.flushed_rows < b.flushed_rows);
}

TEST("habitat: home clock is unknown until synced and continues while paused") {
  FakeHal fake;
  fake.make_round(466);
  hg::Habitat habitat(fake);
  habitat.enable(0);
  CHECK(!habitat.status()["clock_known"].as_bool());
  CHECK_EQ(habitat.status()["time"].as_string(), "--:--");
  CHECK(habitat.clock(1791496799LL, 120, 0));  // Madrid 23:59:59, Thu 8 Oct 2026.
  CHECK_EQ(habitat.status()["time"].as_string(), "23:59");
  CHECK_EQ(habitat.status()["date"].as_string(), "JUE 08 OCT");
  habitat.pause();
  habitat.tick(2000);
  CHECK_EQ(habitat.status()["time"].as_string(), "00:00");
  CHECK_EQ(habitat.status()["date"].as_string(), "VIE 09 OCT");
  CHECK_EQ(habitat.status()["frame"].as_int(), 0);
  CHECK(!habitat.clock(-1, 120, 2000));
  CHECK(!habitat.clock(1791496799LL, 841, 2000));
  CHECK_EQ(habitat.status()["time"].as_string(), "00:00");
}

TEST("habitat: Gregorian dates and millis rollover work without a platform RTC") {
  FakeHal fake;
  fake.make_round(466);
  hg::Habitat leap(fake);
  leap.enable(0);
  CHECK(leap.clock(1709164799LL, 0, 0));
  leap.pause(); leap.tick(2000);
  CHECK_EQ(leap.status()["date"].as_string(), "JUE 29 FEB");
  hg::Habitat normal(fake);
  normal.enable(0);
  CHECK(normal.clock(1677628799LL, 0, 0));
  normal.pause(); normal.tick(2000);
  CHECK_EQ(normal.status()["date"].as_string(), "MIE 01 MAR");
  hg::Habitat wrap(fake);
  wrap.enable(UINT32_MAX - 2000);
  CHECK(wrap.clock(1791496799LL, 120, UINT32_MAX - 2000));
  wrap.pause(); wrap.tick(499);
  CHECK_EQ(wrap.status()["time"].as_string(), "00:00");
  CHECK_EQ(wrap.status()["date"].as_string(), "VIE 09 OCT");
}

TEST("habitat: validated clock command and connection dot reflect core state") {
  Rig r(Rig::touch_profile());
  r.fake.make_round(466);
  r.bring_online(true);
  CHECK_EQ(r.app.console("habitat on"), "@ok habitat");
  CHECK_EQ(r.app.console(R"(habitat clock {"epoch":1791496799,"offset":120})"), "@ok clock");
  Value state;
  CHECK(hg::json::parse(r.app.console("habitat status").substr(9), state));
  CHECK(state["link_online"].as_bool());
  CHECK_EQ(state["time"].as_string(), "23:59");
  CHECK(r.app.console(R"(habitat clock {"epoch":1791496799,"offset":120.5})").find("@error") == 0);
  CHECK(r.app.console(R"(habitat clock {"epoch":1e99,"offset":0})").find("@error") == 0);
  r.app.on_network(false);
  CHECK(hg::json::parse(r.app.console("habitat status").substr(9), state));
  CHECK(!state["link_online"].as_bool());
}

TEST("habitat: minute-only home header updates equal a full redraw") {
  FakeHal a, b;
  a.make_round(466); b.make_round(466);
  hg::Habitat partial(a), full(b);
  partial.enable(0); full.enable(0);
  CHECK(partial.clock(1791496799LL, 120, 0));
  CHECK(full.clock(1791496799LL, 120, 0));
  partial.render(); full.render();
  for (uint32_t time = 50; time <= 2000; time += 50) {
    partial.tick(time); full.tick(time);
    partial.render(); full.invalidate(); full.render();
    CHECK(a.fb == b.fb);
  }
  CHECK_EQ(partial.status()["time"].as_string(), "00:00");
  CHECK(a.flushed_rows < b.flushed_rows);
}

TEST("habitat: clock sync while disabled uses current uptime and survives multiple wraps") {
  FakeHal fake;
  fake.make_round(466);
  hg::Habitat habitat(fake);
  CHECK(habitat.clock(1791496799LL, 120, 3600000));
  habitat.enable(3600000);
  CHECK_EQ(habitat.status()["time"].as_string(), "23:59");
  CHECK_EQ(habitat.status()["date"].as_string(), "JUE 08 OCT");
  habitat.disable();
  // Keep ticking while disabled, crossing two full uint32 millisecond intervals.
  constexpr uint32_t hour = 3600000;
  for (uint64_t elapsed = hour; elapsed <= 2400ULL * hour; elapsed += hour)
    habitat.tick(static_cast<uint32_t>(hour + elapsed));
  habitat.enable(static_cast<uint32_t>(2401ULL * hour));
  CHECK_EQ(habitat.status()["time"].as_string(), "23:59");
  CHECK_EQ(habitat.status()["date"].as_string(), "SAB 16 ENE");
}
