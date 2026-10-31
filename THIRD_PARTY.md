# Third-party notices

## Native account and transport implementation

Files in `okam_bridge/vendor/` derive from [shymonke/okam-ha-native](https://github.com/shymonke/okam-ha-native), commit `8594fe09fe2b422e8f5b48ed02a6f9e05eaabbbe`:

- `account.py` — vendor account access.
- `p2p.py` — transport bootstrap and UID resolution.
- `cs2.py` — CS2/PPPP transport and video handling, adapted here with reliability changes.

These files are inherited and may carry local adaptations; they are not claimed to be an unchanged upstream snapshot. The original MIT copyright and license notice is preserved in [okam_bridge/vendor/LICENSE](okam_bridge/vendor/LICENSE). The local/relay transport adapter, API, CLI and dashboard are maintained in this project. The optional relay mode reuses this inherited CS2 session implementation; its handshake was also cross-checked with [oleandor/okam-ha-native](https://github.com/oleandor/okam-ha-native/blob/main/src/okam_native/cs2.py) and its [amd64 transport report](https://github.com/oleandor/okam-ha-native/blob/main/docs/amd64-development-handoff.md).

`okam_bridge/credentials.py` adapts the AES camera-password decoding approach from upstream `vp_credentials.py` under MIT. The fixed securityPwd interoperability salt was verified against the official client and authorized account records and is included in the decoder. Actual camera/account credentials and proprietary executables are not distributed. No external client file is required for the supported protocol.

## Protocol references

Command numbers and field meanings were cross-checked against the published [VSDK 1.0.0+1 API/source](https://pub.dev/packages/vsdk), [VStarcam CGI command list](https://shop.vstarcam.cn/docs/cgi-command-list/) and [VeeSky RTSP documentation](https://open.veesky.com/docs/open-rtsp/). No Dart SDK source or SDK binary is included. Published protocol documentation does not establish model compatibility or verify a running camera service.

## MediaMTX

Optional bridge RTSP publication uses [MediaMTX v1.21.2](https://github.com/bluenviron/mediamtx/tree/v1.21.2), maintained upstream by the MediaMTX project and distributed separately as `bluenviron/mediamtx:1.21.2`. It is MIT licensed; see its [upstream license](https://github.com/bluenviron/mediamtx/blob/v1.21.2/LICENSE). MediaMTX source or binaries are not bundled in `okam_bridge/vendor/`; Compose retrieves the separate container image. Its copyright and license remain applicable.

## Runtime dependencies

The project uses Python, the `cryptography` package, FFmpeg and nginx. Their respective licenses and distribution terms remain applicable; the project's MIT license does not replace them. Container base images and operating-system packages also retain their own licenses.
