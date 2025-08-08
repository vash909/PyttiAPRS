# PyttiAPRS — Terminal APRS Client (TUI)

PyttiAPRS is a **curses-based** terminal client that lets you send/receive APRS UI frames via a **KISS** TNC (e.g., Direwolf), transmit **position beacons**, and inspect the **AX.25 header/path** in a compact, keyboard‑driven UI.

> This README reflects the latest changes as of **2025‑08‑08** and supersedes prior docs. It aligns with the updated code and UI behavior.

---

## Highlights

- **KISS over TCP** (e.g., Direwolf on `localhost:8001`).
- **APRS messages & position beacons** (uncompressed format).
- **Header viewer**: see `SRC > DEST DIGI…` path for each frame.
- **Heard panel**: unique stations heard since startup.
- **No external APRS libs required** — self‑contained AX.25/KISS helpers.

---

## What’s new (2025‑08‑08)

- **Configurable quick replies**: keys **1** and **2** read phrases from JSON (`quick_msg1`, `quick_msg2`). The **command bar** shows the actual configured texts.
- **RX/TX header parity**: for our **TX** packets the field _after_ `>` now shows your configured **TOCALL** (as RX already does). The APRS **ADDRESSEE** stays in the payload (`::ADDRESSEE:…`).
- **Source‑side `>` alignment**: the **source** callsign field is padded so that the `>` character is vertically aligned across lines. No extra padding is applied to destination or digipeaters; they are just separated by a single space.
- **File logging**: every RX/TX packet is appended to `log_file` (configurable) with timestamp, header, and payload.
- **Command bar** improvements: dynamically reflects configured quick replies.
- **Mouse quick‑select** (documented): click a callsign in **Heard** to make it the default destination for messages and quick replies.

Example (monospace alignment in terminal):
```
17:21:37 IU1BOT    > JN44QH IR1ZXE-11* WIDE2-1: …
17:23:18 IR1ZXE-11 > APMI04 WIDE1-1: …
17:25:56 IN3DNS-13 > T5SWU4 IR1ZXE-11* WIDE1* WIDE2-1: …
```

---

## Requirements

- **Python 3.7+**
- A **KISS‑capable TNC** reachable over TCP (e.g., Direwolf)
- **Windows only**: `pip install windows-curses`

---

## Install & Run

```bash
git clone https://github.com/vash909/PyttiAPRS.git
cd PyttiAPRS
python3 PyttiAPRS.py
```

If connection fails, confirm your TNC is running and the KISS TCP port/host are correct.

---

## First‑run Setup

On first launch you’ll be prompted for:

- **Callsign & SSID** (e.g., `IK2ABC-7`)
- **TOCALL** (software identifier, up to 6 chars; default `APZ001`. For satellites you may prefer a WW Locator per your workflow)
- **Digipeater path** (comma/space separated, e.g., `RS0ISS WIDE2-1` — **hyphens stay inside SSIDs** like `WIDE2-1`)
- **Latitude / Longitude** and hemispheres (N/S, E/W)
- **Symbol table** (`/` or `\`) and **symbol code** (single char), plus **default beacon comment**
- **KISS host/port** (default `localhost:8001`)

These values are saved to a JSON file (see **Configuration & persistence**).

---

## UI Overview

- **Header**: your callsign, TOCALL, PATH, lat/lon, symbol, and **ACK ON/OFF**.
- **Messages** (left): timestamped list of RX/TX packets with `SRC > DEST DIGI…: text`. Your callsign is highlighted.
- **Heard** (right): unique stations heard. Click to set as default destination.

**Escape** cancels any input prompt and returns to the main view.

---

## Keyboard Reference

- `m` — compose and send a **message** (prompts for addressee and text; uses selected **Heard** station as default)
- `p` — send **position beacon** (uncompressed; uses configured comment)
- `c` — **configure** station (callsign, tocall, path, position, symbol, host/port, comment)
- `x` — **clear** messages panel
- `h` — **clear** Heard list
- `d` — send **raw APRS** payload (no padded addressee, no ID; TOCALL is still the AX.25 dest)
- `t` — **repeat last raw**
- `r` — **repeat last message** (reuses ID when ACK is enabled)
- `1` — send **`quick_msg1`** from JSON (text shown in the command bar)
- `2` — send **`quick_msg2`** from JSON (text shown in the command bar)
- `a` — toggle **ACK** on/off (controls appending a `{ID}` to outgoing messages)
- `q` — **quit** (saves config, closes TNC)

---

## Display & Headers

- **TX header**: after `>`, the UI shows your **TOCALL** (software identifier). The APRS **ADDRESSEE** of a message is encoded **in the payload** (`::ADDRESSEE:…`) and not repeated in the header.
- **`>` alignment**: only the **source** field is padded, so the `>` column lines up. **Destination and digipeaters** are rendered without fixed‑width padding — just **single spaces** in between.
- **Digipeater `*`**: a digipeater that actually repeated the packet is shown with `*` (derived from the AX.25 H bit).

---

## Configuration & Persistence

PyttiAPRS reads/writes a JSON config file named **`aprs_tui_config.json`**. It searches these locations (first writable wins):

1. Script directory
2. User home as `.aprs_tui_config.json`
3. Current working directory

### Keys

- `callsign`: string (e.g., `"IK2ABC-7"`)
- `tocall`: string (max 6, e.g., `"APZ001"`)
- `path`: list of strings (e.g., `["RS0ISS","WIDE2-1"]`)
- `latitude`: float; `longitude`: float
- `symbol_table`: `"/"` or `"\\"`
- `symbol_code`: single character (e.g., `">"`)
- `host`: string (default `"localhost"`)
- `port`: int (default `8001`)
- `pos_comment`: string
- `quick_msg1`: string (default `"QSL? 73"`)
- `quick_msg2`: string (default `"QSL! 73"`)
- `log_file`: string (default `"aprs_tui.log"`)

---

## Technical Notes

- **APRS messages** use the format `::ADDRESSEE:TEXT{ID}` (ADDRESSEE padded to 9 chars; `{ID}` optional and used for ACKs).
- **Position beacons** are sent in **uncompressed** format with your configured table/code and comment.
- **AX.25/KISS**: the app builds AX.25 UI frames (dest, source, digis, control `0x03`, PID `0xF0`) and KISS‑encodes them (FEND/FESC escaping) before sending to the TNC.

---

## Logging

When `log_file` is set (default `aprs_tui.log`), each packet is appended with local time, aligned header, and payload. Example format:

```
HH:MM:SS SRC> DEST DIGI1 DIGI2: payload
```

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

## License

Apache‑2.0. See `LICENSE` for details.

