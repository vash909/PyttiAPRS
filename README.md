# PyttiAPRS — APRS TUI over KISS (Direwolf‑compatible)

A single‑file, dependency‑free terminal UI to make APRS AX.25 contacts through any KISS‑compatible TNC (e.g. Direwolf over TCP). It can compose APRS **messages**, send **position beacons**, and show a live log with a **heard stations** side panel.

> Script filename in this repo: `aprs_tui.py`

---

## Highlights (new & improved)

- **Self‑contained KISS I/O**  
  Native KISS framing/unframing (FEND/FESC escaping) and AX.25 UI frame encode/decode. No external packages needed.

- **APRS Message flow (with optional ACK IDs)**  
  Proper 9‑char addressee padding, optional automatic `{`NNN message IDs for ACKs, and recognition of received `ackNNN`.

- **Uncompressed APRS Position beacons**  
  Build `!` position payloads with configurable symbol **table** (`/` or `\`) and **code** (e.g. `>`), plus an optional default comment.

- **TUI built with `curses`**  
  Clean two‑pane layout: scrolling packet log on the left, **Heard** list on the right. **Mouse support** lets you click a callsign to target it quickly.

- **Quick‑reply shortcuts**  
  `1` sends `QSL? 73`, `2` sends `QSL! 73` to the selected (or prompted) station.

- **Resend controls**  
  `r` repeats the **last message**, `t` repeats the **last raw payload**.

- **ACK toggle for satellites**  
  Press `a` to enable/disable including message IDs (useful when ACKs aren’t supported on a pass).

- **Writable config & session persistence**  
  On exit, settings are saved to the first writable path among:
  - repo dir: `./aprs_tui_config.json`
  - home: `~/.aprs_tui_config.json`
  - cwd: `./aprs_tui_config.json`

  Persisted fields include: callsign, tocall, path, lat/lon, symbol table/code, host/port, default position comment, quick‑messages, and log file.

- **File logging**  
  Appends compact single‑line entries to `aprs_tui.log` (configurable).

---

## Requirements

- Python 3.7+  
- A KISS‑compatible TNC reachable via **TCP** (Direwolf recommended)  
- A terminal of at least **80×24**

No third‑party Python dependencies.

---

## Quick start

1. Start your TNC (e.g. Direwolf) with KISS TCP enabled (default shown in examples is port **8001**).
2. Run:

```bash
python3 aprs_tui.py
```

3. On first run, you’ll be prompted for:
   - **Callsign** (e.g. `IU1BOT-9`)
   - **TOCALL** (software ID, default `APZ001`)
   - **Digipeater path** (comma/space‑separated, e.g. `ARISS`, `WIDE1-1 WIDE2-1`, or leave blank)
   - **Latitude/Longitude** and **N/S**, **E/W**
   - **Symbol table** (`/` or `\`) and **symbol code** (single char)
   - Optional default **position comment**

Connection parameters (host/port) default to `localhost:8001` and can be edited later.

---

## Key bindings

- `m` — compose & send APRS **message** (ID auto‑appended when ACK is ON)  
- `p` — send **position beacon** using stored position/comment  
- `c` — edit station **config** (call, tocall, path, lat/lon, symbol, comment, etc.)  
- `d` — send **raw APRS payload** (no addressee/ID)  
- `t` — **repeat last raw** payload  
- `r` — **repeat last message** (keeps same dest and, if ACK is ON, same ID)  
- `1` / `2` — quick messages: `QSL? 73` / `QSL! 73`  
- `x` — clear message log in the UI  
- `h` — clear **Heard** list  
- `a` — toggle **ACK** on/off  
- `q` — quit

**Mouse:** click a callsign in **Heard** to select it as default destination for `m`, `1`, or `2`.
**Note:** if you press `m` with an highlighted callsign the software will still ask for the destination, just press enter and it'll be the callsign you selected in the heard list.
---

## How it works (short technical tour)

- **AX.25 UI frames**  
  Addresses are encoded to 7‑byte fields (6 shifted ASCII chars + SSID byte with bits 5–6 set). The last address sets bit 0. Only **UI** frames (control `0x03`, PID `0xF0`) are parsed.

- **KISS**  
  Frames are wrapped with `FEND (0xC0)`; embedded `FEND`/`FESC` are escaped to `FESC TFEND`/`FESC TFESC`. Only KISS **data** frames (`0x00`) are processed.

- **APRS payloads**  
  - Messages: `:{addressee(9)}:{text}{{ID}` (ID optional)  
  - Positions: `!DDMM.mmN/S{table}DDDMM.mmE/W{symbol}{comment}`

- **Encoding choices**  
  Payloads are encoded as **Latin‑1** when sending/logging to preserve arbitrary bytes.

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
- Only **unconnected UI** frames are decoded. Connected‑mode frames are ignored.  
- Message ACKs are recognized; automatic retry of un‑ACKed messages is **not** implemented.

---

## Tips

- For **satellite APRS**, consider toggling **ACK OFF** (`a`) so messages don’t carry IDs.  
- Use the **Heard** list + mouse to target quick replies without retyping callsigns.  
- Keep the terminal at least **80×24** for the best layout.
- Remember to press `q` instead of closing your terminal window to save changes and log.

---

## Troubleshooting

- **Cannot connect to TNC** — ensure Direwolf (or your TNC) is running with KISS over TCP and that host/port match the config.
- **Config not saved** — run from a writable location (script dir, home, or CWD). The app writes to the first writable candidate.
- **Strange characters** — the UI decodes payloads as Latin‑1. Binary data or non‑ASCII may be rendered with substitutions.

---

## Contributing

PRs are welcome. Please:
1. Fork the repo and create a feature branch.
2. Keep changes focused and well‑commented.
3. Verify `python3 -m py_compile PyttiAPRS.py` passes.
4. Open a PR with a short rationale and screenshots if UI‑related.

---

## License & author

- **Apache 2.0**  
- Author: Lorenzo Gianlorenzi (IU1BOT) — iu1bot@xzgroup.net

---

## Changelog (recent)

- TUI layout refinements; highlighted command bar and status line  
- **Mouse selection** in Heard list + default destination behavior  
- **Quick messages** (`1`/`2`) and **ACK toggle** (`a`)  
- **Repeat last message/raw** (`r`/`t`)  
- **Raw data** send mode (`d`)  
- **Config persistence** with multiple candidate paths  
- **File logging** with robust error handling

*Updated: 2025-08-11*
