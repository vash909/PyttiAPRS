# PyttiAPRS — APRS TUI over KISS (Direwolf-compatible)

A single-file, dependency-free terminal UI for making APRS AX.25 contacts through any KISS-compatible TNC (e.g. Direwolf over TCP). It composes APRS **messages**, sends **position beacons**, and shows a live packet log alongside a **heard stations** panel.

- Script filename in this repo: `PyttiAPRS.py`
- Full walkthrough: see `user_guide_en.md`
- Telegram user group: https://t.me/pyttiaprs

---

## Highlights

- **Self-contained KISS I/O**
  Native KISS framing/unframing (FEND/FESC escaping) and AX.25 UI frame encode/decode. No external packages needed.

- **APRS message flow (with optional ACK IDs)**
  Proper 9-char addressee padding, optional automatic `{`NNN message IDs for ACKs, and recognition of received `ackNNN`.

- **Uncompressed APRS position beacons**
  Build `!` position payloads with configurable symbol **table** (`/` or `\`) and **code** (e.g. `>`), plus an optional default comment.

- **Colorized `curses` TUI**
  Two-pane layout: scrolling packet log on the left, **Heard** list on the right. Fixed screen regions (status bar, command bar, section titles, packet headers/bodies, heard list) are color-coded so the layout stays easy to scan; your own callsign is highlighted wherever it appears. Falls back to plain attributes automatically on terminals without color support. **Mouse support** lets you click a callsign to target it quickly.

- **Quick-reply shortcuts**
  `1` sends `QSL? 73`, `2` sends `QSL! 73` to the selected (or prompted) station.

- **Resend controls**
  `r` repeats the **last message**, `t` repeats the **last raw payload**.

- **ACK toggle for satellites**
  Press `a` to enable/disable including message IDs (useful when ACKs aren't supported on a pass).

- **Writable config & session persistence**
  On exit, settings are saved to the first writable path among:
  - repo dir: `./aprs_tui_config.json`
  - home: `~/.aprs_tui_config.json`
  - cwd: `./aprs_tui_config.json`

  Persisted fields include: callsign, tocall, path, lat/lon, symbol table/code, host/port, default position comment, quick-messages, and log file. Saved digipeater paths are normalized on load, so a config file written by an older, buggy version is repaired automatically instead of corrupting future transmissions.

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
   - **TOCALL** (software ID, default `APZ001`)
   - **Digipeater path** (comma or space-separated, e.g. `ARISS`, `WIDE1-1 WIDE2-1`, or leave blank)
   - **Latitude/Longitude** and **N/S**, **E/W**
   - **Symbol table** (`/` or `\`) and **symbol code** (single char)
   - Optional default **position comment**

Connection parameters (host/port) default to `localhost:8001` and can be edited later from the in-app configuration screen (key `c`).

---

## How it works (short technical tour)

- **AX.25 UI frames**
  Addresses are encoded to 7-byte fields (6 shifted ASCII chars + SSID byte with bits 5-6 set). The last address sets bit 0. Only **UI** frames (control `0x03`, PID `0xF0`) are parsed.

- **KISS**
  Frames are wrapped with `FEND (0xC0)`; embedded `FEND`/`FESC` are escaped to `FESC TFEND`/`FESC TFESC`. Only KISS **data** frames (`0x00`) are processed.

- **APRS payloads**
  - Messages: `:{addressee(9)}:{text}{{ID}` (ID optional)
  - Positions: `!DDMM.mmN/S{table}DDDMM.mmE/W{symbol}{comment}`

- **Encoding choices**
  Payloads are encoded as **Latin-1** when sending/logging to preserve arbitrary bytes.

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
- Message ACKs are recognized; automatic retry of un-ACKed messages is **not** implemented.

---

## Troubleshooting

- **Cannot connect to TNC** — ensure Direwolf (or your TNC) is running with KISS over TCP and that host/port match the config.
- **Config not saved** — run from a writable location (script dir, home, or CWD). The app writes to the first writable candidate.
- **Strange characters** — the UI decodes payloads as Latin-1. Binary data or non-ASCII may be rendered with substitutions.
- **Multi-hop digipeater path gets truncated on transmit** — fixed. Older saved configs affected by this are repaired automatically the next time the app loads them; see the changelog below.

---

## Changelog

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
3. Verify `python3 -m py_compile PyttiAPRS.py` passes.
4. Open a PR with a short rationale and screenshots if UI-related.

---

## License & author

- **Apache 2.0**
- Author: Lorenzo Gianlorenzi (IU1BOT) — iu1bot@xzgroup.net
