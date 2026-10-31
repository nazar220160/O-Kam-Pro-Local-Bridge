# Third-party notices

## Native account and transport implementation

Files in `okam_bridge/vendor/` derive from [shymonke/okam-ha-native](https://github.com/shymonke/okam-ha-native), commit `8594fe09fe2b422e8f5b48ed02a6f9e05eaabbbe`:

- `account.py` — vendor account access.
- `p2p.py` — transport bootstrap and UID resolution.
- `cs2.py` — CS2/PPPP transport and video handling, adapted here with reliability changes.

These files are inherited and may carry local adaptations; they are not claimed to be an unchanged upstream snapshot. The original MIT copyright and license notice is preserved in [okam_bridge/vendor/LICENSE](okam_bridge/vendor/LICENSE). The local LAN adapter, API, CLI and dashboard are maintained in this project.

`okam_bridge/credentials.py` adapts the AES camera-password decoding approach from upstream `vp_credentials.py` under MIT. No embedded vendor keys or proprietary executables are distributed. Where required, a user supplies a compatible official client file, inspected locally as data only.

## Protocol references

Command numbers and field meanings were cross-checked against the published [VSDK 1.0.0+1 API/source](https://pub.dev/packages/vsdk), [VStarcam CGI command list](https://shop.vstarcam.cn/docs/cgi-command-list/) and [VeeSky RTSP documentation](https://open.veesky.com/docs/open-rtsp/). No Dart SDK source or SDK binary is included. Published protocol documentation does not establish model compatibility or verify a running camera service.

## Runtime dependencies

The project uses Python, the `cryptography` package, FFmpeg and nginx. Their respective licenses and distribution terms remain applicable; the project's MIT license does not replace them. Container base images and operating-system packages also retain their own licenses.
