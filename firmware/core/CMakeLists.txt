# Portable device core. Builds as an ESP-IDF component or a plain CMake library.
set(HG_CORE_SOURCES
    src/app.cpp
    src/app_settings.cpp
    src/app_power.cpp
    src/canvas.cpp
    src/crypto.cpp
    src/font5x7.cpp
    src/habitat.cpp
    src/json.cpp
    src/mascot_data.cpp
    src/protocol.cpp
    src/setup.cpp
    src/touch.cpp
    src/ui.cpp
    src/vad.cpp
)

set(HG_HABITAT_ASSETS_SOURCE "" CACHE FILEPATH "Generated private habitat artwork; empty uses geometric stand-ins")
if(HG_HABITAT_ASSETS_SOURCE)
  if(NOT EXISTS "${HG_HABITAT_ASSETS_SOURCE}")
    message(FATAL_ERROR "HG_HABITAT_ASSETS_SOURCE does not exist: ${HG_HABITAT_ASSETS_SOURCE}")
  endif()
  list(APPEND HG_CORE_SOURCES "${HG_HABITAT_ASSETS_SOURCE}")
else()
  list(APPEND HG_CORE_SOURCES src/habitat_assets_stub.cpp)
endif()

if(ESP_PLATFORM)
  idf_component_register(SRCS ${HG_CORE_SOURCES} INCLUDE_DIRS include)
  return()
endif()

add_library(hg_core STATIC ${HG_CORE_SOURCES})
target_include_directories(hg_core PUBLIC include)
target_compile_features(hg_core PUBLIC cxx_std_17)
set_target_properties(hg_core PROPERTIES POSITION_INDEPENDENT_CODE ON)
if(MSVC)
  target_compile_options(hg_core PRIVATE /W4 /utf-8)
else()
  target_compile_options(hg_core PRIVATE -Wall -Wextra -fno-exceptions -fno-rtti)
endif()
