A tiny Kotlin ForegroundService that binds the Meshtastic Android app via IMeshService (AIDL) and exposes a localhost TCP socket for Reticulum/Sideband. It lets you run RNS-over-Meshtastic on Android without touching BLE/USB or recompiling Sideband.

TL;DR: Meshtastic app owns the radio. This service rides on top of it and gives Reticulum a simple socket: 127.0.0.1:45832 → PRIVATE_APP/Stream.

Features

Binds IMeshService (Meshtastic app) — no direct BLE/USB in your app

Localhost TCP bridge (127.0.0.1:45832, u16 length-prefixed frames)

Broadcast or Unicast to gateway (destinationId), toggle at runtime

MTU default 180 bytes (LoRa-friendly fragmentation for RNS)

PRIVATE_APP by default; optional Stream (e.g., "RNS")

Auto-reconnect with backoff; ForegroundService + persistent notification

127.0.0.1 only (safe by default); optional token/HMAC handshake supported

Why

Keep it simple: Let the Meshtastic app own BLE/USB; you only speak AIDL.

Sideband/Reticulum friendly: 60–100 LOC Python External Interface can plug straight in.

Air-efficient: Use RNS reliability, keep Meshtastic link-layer ACKs off, MTU ≈ 180.

Architecture
[Sideband / Reticulum]  <--TCP-->  [IMeshService Bridge (this app)]  <--AIDL-->  [Meshtastic app]  <--RF-->  Mesh
         ^                                                                               ^
         |  External Interface (60–100 LOC)                                              |  Your radio
         |  len-prefixed frames (u16 | bytes)                                            |

Requirements

Android 8+ (API 26+)

Meshtastic Android app installed and connected to your device

This app’s only special permission: Foreground Service (for long-running bind)

Install

Releases: download and sideload the APK, or

Build: Android Studio → Build > Generate Signed APK… → install the release APK.

Usage

Open the Meshtastic app and confirm it’s connected to your radio.

Start IMeshService Bridge → the notification will show “Bridge active”.

Point Reticulum at the local socket.
