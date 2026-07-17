# PyttiAPRS User Guide

## Overview

PyttiAPRS is a lightweight APRS client with a `curses` terminal interface. It sends and receives unconnected AX.25 UI frames through a KISS TCP TNC such as Direwolf. The interface is convenient for short satellite contacts, but the protocol layer is not satellite-only.

There is one operator-configurable digipeater path:

- Enter a current satellite alias such as `RS0ISS` when appropriate.
- Enter a terrestrial path such as `WIDE2-2` or `WIDE1-1,WIDE2-2` when appropriate.
- Leave the path blank for a direct packet.

PyttiAPRS never substitutes `ARISS`, `RS0ISS`, or any other alias automatically. Satellite operation changes over time, so always check the current instructions for the spacecraft and mode you intend to use.

## Requirements

- Python 3.7 or newer
- A KISS-compatible TNC reachable over TCP
- A terminal of at least 80×24 characters

No third-party Python packages are required. Windows users may need an environment that provides `curses`.

## Starting the application

Run:

```bash
python3 PyttiAPRS.py
```

On the first run, enter:

- your callsign and optional SSID;
- the TOCALL, with `APZ001` as the default;
- the digipeater path, or leave it blank;
- latitude and longitude;
- the APRS symbol table and symbol code;
- an optional position comment;
- the KISS host and port.

The path accepts comma- or space-separated AX.25 addresses. Each address is validated, including its optional SSID, and a maximum of eight digipeaters is allowed.

The AX.25 destination TOCALL defaults to the experimental identifier `APZ001`. It can be changed during initial setup or later with `c`, is validated like any other AX.25 address, and is saved in the configuration. The operator is responsible for choosing an appropriate registered or experimental identifier.

## Screen layout

- The status bar shows callsign, TOCALL, path, position, symbol, ACK mode, and the most recent delivery state.
- The command bar shows the available single-key commands.
- The left pane shows transmitted and received packets.
- The right pane lists recently heard stations. Clicking one selects it as the next message destination.

The visual layout remains the same for satellite and terrestrial operation; only the configured path changes.

## Commands

| Key | Action |
|---|---|
| `m` | Compose and send an APRS message. |
| `p` | Send the configured position beacon. |
| `c` | Edit callsign, path, position, symbol, comment, and KISS endpoint. |
| `d` | Send a raw APRS information field. |
| `t` | Repeat the last raw payload. |
| `r` | Repeat the last message. |
| `1` / `2` | Send the configured quick messages. |
| `x` | Clear the packet list on screen. |
| `h` | Clear the Heard list. |
| `a` | Toggle outgoing message IDs and acknowledgement tracking. |
| `q` | Quit and save the configuration. |

Press Escape to cancel an interactive prompt without applying partial configuration changes.
Changes to the KISS host or port take effect on the next launch; the current
TCP connection is not moved while the TUI is running.

## Choosing a path

The path is blank by default. Examples:

```text
RS0ISS
WIDE2-2
WIDE1-1,WIDE2-2
```

These examples are not profiles and receive no special handling. `RS0ISS` and `WIDE2-2` are encoded by the same AX.25 routine. Changing the path in the configuration changes subsequent messages, acknowledgements, beacons, and raw transmissions.

Do not assume that a satellite alias remains valid indefinitely. Confirm the current uplink, mode, path, and operating policy before transmitting.

## Messages and acknowledgements

Messages use the fixed 9-character APRS addressee field and UTF-8 text. Message text is limited to 67 characters while the final AX.25 information field is also kept within 256 bytes.

ACK mode is off by default:

- With ACK off, outgoing messages have no message ID and are sent once. This is often useful during a short pass.
- With ACK on, outgoing messages include a three-digit ID. PyttiAPRS waits for `ack` or `rej`; if neither arrives, it makes one retry after 60 seconds and then reports `NO ACK`.

Incoming messages addressed exactly to your configured callsign are acknowledged when they contain an ID, regardless of the outgoing ACK toggle. Duplicate acknowledgements for the same message are rate-limited to at least 30 seconds. Incoming reply-ack identifiers are also correlated with pending messages.

The configured path is used for acknowledgements. A satellite is a digipeater, not the endpoint producing the end-to-end ACK.

## Position beacons

Press `p` to send an uncompressed APRS position. Because PyttiAPRS can receive and acknowledge messages, the beacon uses the messaging-capable `=` data type identifier. Coordinates are rounded with carry into `DDMM.mm` / `DDDMM.mm` format.

The position comment accepts UTF-8 and is limited to 43 characters. Primary and alternate symbol tables are supported, along with numeric or upper-case overlays.

## Raw payloads

Press `d` to send a raw APRS information field with the configured TOCALL and current path. Raw mode is intentionally low-level: PyttiAPRS validates control characters and the 256-byte AX.25 limit, but the operator is responsible for supplying a meaningful APRS data type and payload.

## Reception and Mic-E

PyttiAPRS receives AX.25 UI frames with control `0x03` and PID `0xF0`. It displays the H bit on repeated digipeater addresses with `*`.

Mic-E current and old position packets are converted to a readable position for display. Longitude wrap, course/speed, and position ambiguity are decoded; the original over-the-air packet remains authoritative.

Human-readable received data is decoded as UTF-8. Latin-1 is used as a fallback for older or binary-bearing packets.

## Configuration and logging

On exit, configuration is written to the first writable candidate:

1. `aprs_tui_config.json` beside the script;
2. `~/.aprs_tui_config.json`;
3. `aprs_tui_config.json` in the current directory.

Saved settings include callsign, TOCALL, path, position, symbol, KISS endpoint, position comment, quick messages, ACK preference, and log filename. The message counter is not persisted.

Packets are appended to the configured log file, normally `aprs_tui.log`, in this form:

```text
HH:MM:SS SRC> DEST PATH: payload
```

## Protocol scope

The implementation covers the APRS features used by this client: messages and acknowledgements, uncompressed positions, raw information fields, and Mic-E display decoding. It is not a complete implementation of every APRS 1.2 data type, telemetry extension, object format, weather format, or connected AX.25 mode.

KISS parsing supports fragmented TCP reads, standard escaping, consecutive frames, and data commands from any KISS port. Malformed escape sequences and malformed AX.25 address fields are rejected.

## Testing

Run the regression suite with:

```bash
python3 -m unittest -v
```

The suite covers satellite and terrestrial paths, AX.25 address bits, KISS fragmentation, UTF-8 limits, message ACK/reply-ack behavior, position rounding, and Mic-E decoding.

## Troubleshooting

- **Cannot connect:** check that the TNC is listening on the configured host and port.
- **Invalid configuration:** verify callsign/SSID, path addresses, coordinate ranges, symbol, and TCP port.
- **No satellite traffic:** verify the current spacecraft frequency, mode, path alias, pass timing, radio/TNC levels, and operating policy.
- **No terrestrial repeat:** verify that the chosen WIDEn-N path is suitable for the local network.
- **Strange characters:** the payload may be a binary APRS data type rather than UTF-8 text.
- **Settings not saved:** ensure at least one candidate configuration location is writable and quit with `q`.

## License and author

PyttiAPRS is released under the Apache 2.0 license.

Original author: Lorenzo Gianlorenzi (IU1BOT) — `iu1bot@xzgroup.net`.
