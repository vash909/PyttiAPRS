# PyttiAPRS — A lightweight APRS client
                                                      
A single-file, dependency-free terminal UI for APRS AX.25 contacts through any KISS-compatible TNC (for example Direwolf over TCP). It is designed with satellite contacts in mind, but uses the same configurable path for terrestrial APRS: `RS0ISS`, `WIDE2-2`, another current alias, or no path at all.

- Full walkthrough: see `user_guide_en.md`
- Telegram user group: https://t.me/pyttiaprs

---

## Highlights of the software

- **Self-contained KISS I/O**
  Native KISS framing/unframing (FEND/FESC escaping) and AX.25 UI frame encode/decode. No external packages needed.

- **APRS message flow (with optional ACK IDs)**
  Proper 9-character addressee padding, UTF-8 text, optional `{NNN` IDs, automatic acknowledgements for addressed incoming messages, `ack`/`rej` correlation, reply-ack parsing, and one conservative retry after 60 seconds.

- **Uncompressed APRS position beacons**
  Builds messaging-capable `=` position payloads with correct coordinate rounding, configurable symbol table/overlay and symbol code, plus an optional UTF-8 comment.

- **Configurable satellite or terrestrial path**
  No digipeater path is assumed or hard-coded. Satellite aliases change over time, so the operator enters the current value; terrestrial paths such as `WIDE2-2` use the same encoder.

- **Colorized `curses` TUI**
  Two-pane layout: scrolling packet log on the left, **Heard** list on the right. Fixed screen regions (status bar, command bar, section titles, packet headers/bodies, heard list) are color-coded so the layout stays easy to scan; your own callsign is highlighted wherever it appears. Falls back to plain attributes automatically on terminals without color support. **Mouse support** lets you click a callsign to target it quickly.

- **Quick-reply shortcuts**
  `1` sends `QSL? 73`, `2` sends `QSL! 73` to the selected (or prompted) station.

- **Resend controls**
  `r` repeats the **last message**, `t` repeats the **last raw payload**.

- **ACK toggle for constrained links**
  Press `a` to enable or disable outgoing message IDs. The default one-shot mode is useful during short satellite passes; acknowledged mode is also usable terrestrially.

- **Writable config & session persistence**
  On exit, settings are saved to the first writable path among:
  - repo dir: `./aprs_tui_config.json`
  - home: `~/.aprs_tui_config.json`
  - cwd: `./aprs_tui_config.json`

  Persisted fields include: callsign, TOCALL, path, lat/lon, symbol table/code, host/port, default position comment, quick messages, ACK preference, and log file. Saved paths are normalized and validated on load.

- **File logging**
  Appends compact single-line entries to `aprs_tui.log` (configurable).

---

## Requirements

- Python 3.7+
- A KISS-compatible TNC reachable via **TCP** (Direwolf recommended)
- A terminal of at least **80×24**

No third-party Python dependencies.

---

## Quick start

1. Start your TNC (e.g. Direwolf) with KISS TCP enabled (default shown in examples is port **8001**).
2. Run:

```bash
python3 PyttiAPRS.py
```

3. On first run, you'll be prompted for:
   - **Callsign** (e.g. `IU1BOT-9`)
   - **TOCALL** (default `APZ001`, editable)
   - **Digipeater path** (comma or space-separated, for example `RS0ISS`, `WIDE2-2`, `WIDE1-1 WIDE2-2`, or blank)
   - **Latitude/Longitude** and **N/S**, **E/W**
   - **Symbol table** (`/` or `\`) and **symbol code** (single char)
   - Optional default **position comment**

The default path is blank. PyttiAPRS does not rewrite aliases or choose a satellite path: verify the current operating instructions for the satellite or terrestrial network you intend to use. Connection parameters default to `localhost:8001` and can be edited with `c`.

---

## How it works (short technical tour)

- **AX.25 UI frames**
  Addresses and SSIDs are validated, reserved bits and the command/response bits are encoded correctly, the last address sets the extension bit, and at most eight digipeaters are accepted. Only UI frames (`0x03`, PID `0xF0`) with a 1–256 byte information field are parsed.

- **KISS**
  Frames are wrapped with `FEND (0xC0)` and escaped normally. The stream parser retains incomplete TCP frames, rejects malformed escapes, and accepts KISS data commands from any KISS port.

- **APRS payloads**
  - Messages: `:{addressee(9)}:{text}{{ID}` (ID optional)
  - Positions: `=DDMM.mmN/S{table}DDDMM.mmE/W{symbol}{comment}`

- **Encoding choices**
  Human-readable text is sent as UTF-8. Received text is decoded as UTF-8 with a Latin-1 fallback for legacy or binary-bearing packets.

- **Logging**
  Lines look like: `HH:MM:SS SRC> DEST PATH...: text`

---

## Configuration & files

- **Saved config**: `aprs_tui_config.json` in the first writable location (see above).
- **Log**: `aprs_tui.log` (path/name configurable in the app).
- **Not persisted**: The sequential message ID counter (resets each run).

---

## Compatibility & scope

- Tested with software TNCs using the standard KISS TCP interface (e.g. Direwolf).
- Only **unconnected UI** frames are decoded. Connected-mode frames are ignored.
- The implemented APRS subset includes messages, acknowledgements, uncompressed positions and Mic-E display decoding; this is not a claim to implement every APRS 1.2 data type.
- `APZ001` is the default development TOCALL, but it can be edited and is persisted. Operators should use an appropriate registered or experimental identifier for their transmission.

---

## Troubleshooting

- **Cannot connect to TNC** — ensure Direwolf (or your TNC) is running with KISS over TCP and that host/port match the config.
- **Config not saved** — run from a writable location (script dir, home, or CWD). The app writes to the first writable candidate.
- **Strange characters** — the UI prefers UTF-8 and falls back to Latin-1. Other binary APRS data types can still contain non-printing bytes.
- **Multi-hop digipeater path gets truncated on transmit** — fixed. Older saved configs affected by this are repaired automatically the next time the app loads them; see the changelog below.

---

## Changelog

**2026-07-16**
- Kept one multi-purpose TUI and made the path fully operator-configurable: blank by default, with no hard-coded `ARISS` or satellite-only profile. Current satellite aliases such as `RS0ISS` and terrestrial paths such as `WIDE2-2` pass through the same AX.25 encoder.
- Corrected AX.25 address validation and bits, KISS TCP fragmentation/escaping and multi-port data handling, UTF-8 limits, position rounding/DTI, Mic-E longitude and ambiguity decoding, and APRS message ID/ACK/reply-ack handling.
- Added automatic ACK transmission, ACK/rejection correlation, a conservative single retry, and 24 protocol regression tests.
- Restored an editable, persisted TOCALL while retaining `APZ001` as the default.

**2026-07-03**
- Fixed a bug where a multi-hop digipeater path (e.g. `WIDE2-1,WIDE1-1`) could silently collapse to a single, SSID-less hop (e.g. `WIDE2`) when transmitted. The status bar and the "Edit configuration" screen were joining the path with `-` instead of `,` when displaying/re-reading its current value; accepting that value unchanged fed a malformed token back into the path parser. Both display points now use `,`, and loading a saved config re-normalizes the `path` field defensively so previously corrupted config files are repaired on load.
- Colorized the TUI: status bar, command bar, section titles, packet header/body text, and the heard list each get a distinct color to make the layout easier to scan at a glance. No layout changes — colors were added to existing screen regions only.

**2026-01-25**
- Added prompts to configure the KISS/TNC connection host (IP/DNS) and port during the initial interactive setup.
- Extended the in-app configuration editor (key `c`) to edit the same host/port values.
- Kept defaults (`localhost:8001`) when the user leaves the fields empty.
- Persisted the selected host/port in the saved config so the next run reconnects to the chosen endpoint.

**2025-09-30**
- Added Mic-E decoding support.

---

## Contributing

PRs are welcome. Please:
1. Fork the repo and create a feature branch.
2. Keep changes focused and well-commented.
3. Run `python3 -m unittest -v`.
4. Open a PR with a short rationale and screenshots if UI-related.

---

## License & author

- **Apache 2.0**
- Author: Lorenzo Gianlorenzi (IU1BOT) — iu1bot@xzgroup.net
