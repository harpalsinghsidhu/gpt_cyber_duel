[app]
title = Cyber Duel
package.name = cyberduel
package.domain = org.cyberduel
source.dir = .
source.include_exts = py
version = 0.1
requirements = python3==3.10.12,hostpython3==3.10.12,pygame
orientation = landscape
fullscreen = 1
android.permissions = INTERNET,ACCESS_NETWORK_STATE,ACCESS_WIFI_STATE
android.ndk = 25b
android.api = 33
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
