
# PyttiAPRS TUI Client – User Guide & Technical Notes

This document serves as both a **user guide** and a **technical overview** for the APRS TUI Client, a Python application that enables APRS messaging via a KISS‑compatible TNC.  The aim is to help end‑users operate the software confidently while providing enough technical context to understand how it works internally.

---

## Table of Contents

1. [Introduction](#introduction)
2. [Getting Started](#getting-started)
3. [Running the Client](#running-the-client)
4. [User Interface Overview](#user-interface-overview)
5. [Command Reference](#command-reference)
6. [Station Configuration](#station-configuration)
7. [APRS and KISS Technical Notes](#aprs-and-kiss-technical-notes)
8. [Configuration File & Persistence](#configuration-file--persistence)
9. [Troubleshooting](#troubleshooting)
10. [Contributing](#contributing)

---

## Introduction

Automatic Packet Reporting System (APRS) is a digital communications protocol for exchanging information such as messages, GPS positions and telemetry over amateur radio.  Satellite digipeaters like the ISS enable global coverage for low‑power stations.  The APRS TUI Client is a lightweight terminal application written in Python that lets you:

- Send and receive APRS **messages** via satellites or terrestrial digipeaters.
- Transmit **position beacons** with user‑configured symbol and comment.
- Monitor the raw AX.25 **path** of each packet to see how and where it was digipeated.
- Operate entirely from a terminal, using a curses‑based interface reminiscent of `htop`.

The client communicates with a **KISS‑compatible TNC**, such as [Direwolf](https://github.com/wb2osz/direwolf), running locally.  KISS (Keep It Simple Stupid) is a framing protocol that encapsulates AX.25 frames for transport over serial or TCP links.

---

## Getting Started

### Prerequisites

- **Python 3.7+** installed on your system.
- A **KISS‑capable TNC** (software or hardware) running locally and listening on a TCP port.  The default Direwolf KISS port is `localhost:8001`.
- On **Windows**, install the `windows-curses` package:
  ```bash
  pip install windows-curses
  ```

### Installation

1. Clone or download this repository:
   ```bash
   git clone https://github.com//vash909/PyttiAPRS.git
   cd PyttiAPRS
   ```

2. Ensure `PyttiAPRS.py` is executable and run it:
   ```bash
   python3 PyttiAPRS.py
   ```

If it cannot connect to the TNC, verify that Direwolf is running and that the KISS port is correctly set.

---

## Running the Client

On the first run, the client prompts you for several **station parameters**:

1. **Callsign & SSID** (e.g. `IK2ABC-7`).
2. **Software identifier** (TOCALL) – a six‑character identifier; default is `APZ001` - In satellite comms you should use your WW Locator.
3. **Digipeater path** – a comma‑ or space‑separated list of digipeaters (e.g. `WIDE2-2,ARISS`).  Hyphens are preserved inside callsigns.
4. **Latitude & Direction** – enter the numeric degrees (e.g. `45.67`) and select `N` or `S`.
5. **Longitude & Direction** – numeric degrees (e.g. `7.89`) and select `E` or `W`.
6. **Symbol table & code** – determines the icon shown on APRS maps.  Table `/` is primary and `\` is secondary; the code is a single character (e.g. `>` for a mobile).  Refer to APRS Symbol Chart for options.
7. **Default position comment** – optional comment appended to all position packets.

These settings are saved and automatically loaded on subsequent runs.  See [Configuration File & Persistence](#configuration-file--persistence) for details.

After configuration, the client connects to the TNC and displays its interface.

---

## User Interface Overview

The curses‑based interface consists of three areas:

- **Header** – shows your callsign, software ID, digipeater path, latitude/longitude and symbol.
- **Messages Panel** (left) – lists received and sent packets with time, source, destination (if any), path and payload.  Your configured callsign is highlighted wherever it appears.
- **Heard Panel** (right) – lists unique stations heard.

A command bar under the header lists the available **single‑character commands**.

### Navigating

The interface is non‑interactive beyond the commands; new packets appear as they arrive.  If the screen fills with messages, old entries scroll off the top but remain in memory for the duration of the session.

---

## Command Reference

| Key | Action |
|---|---|
| `m` | **Send message** – prompts for destination (addressee) and message text.  Messages follow the APRS message format `::DEST:Text{ID}` with a padded nine‑character addressee field and a maximum of ~67 characters.  A numeric ID is appended automatically to support acknowledgements. |
| `p` | **Send position beacon** – transmits your configured latitude/longitude using the uncompressed format `!DDMM.mmN/DDDMM.mmE` and the selected symbol.  The default comment set in your configuration is appended; it is not prompted each time. |
| `c` | **Configure station** – opens a form to edit any station parameter: callsign, tocall, digipeater path, latitude/longitude & directions, symbol table & code and default position comment.  Changes take effect immediately. |
| `q` | **Quit** – exits the program, closes the TNC connection and saves the current configuration. |

When you send a packet, your own transmission appears in the messages panel with the current path.  Incoming packets show the digipeater path (`via ...`) so you can tell if your packets were digipeated and by whom.

---

## Station Configuration

Pressing `c` invokes the configuration editor.  Inputs are taken at the bottom of the screen; if prompts disappear quickly, they will reappear when you begin typing.  Fields include:

- **Callsign** – update your callsign/SSID.
- **TOCALL** – identifies the software; six characters max.
- **Digipeater path** – enter digipeater calls separated by commas or spaces.  Do **not** use hyphens as separators; they are part of the SSID (e.g. `WIDE2-2`).
- **Latitude & Longitude** – enter absolute degrees and choose N/S and E/W directions.  Internally these are stored as positive or negative floats.
- **Symbol** – choose the table (`/` or `\`) and code.
- **Default position comment** – text appended to every beacon.
- **KISS host & port** – adjust if your TNC is not on `localhost:8001`.

Changes are saved automatically on exit. REMEMBER TO PRESS Q INSTEAD OF CLOSING YOUR TERMINAL WINDOW.

---

## APRS and KISS Technical Notes

This section summarises how the client implements APRS and KISS for those interested in the underlying details.

### APRS Messages

APRS messages are sent as **AX.25 UI (Unnumbered Information) frames**.  The info field uses a specific format:

```
::ADDRESSEE:Message text{nnn
```

- The **addressee** is padded to exactly nine characters (spaces if needed).  This ensures fixed field length
- The **message text** should be no longer than 67 characters and remain on a single line to minimise network congestion
- The optional **message ID** (e.g. `{001}`) triggers the recipient to send an acknowledgement (`ack001`).  The client increments this ID automatically for each message.

### Position Packets

Position reports use the **uncompressed APRS format**:

```
!DDMM.mmN/S T DDDMM.mmE/W S Comment
```

Where:

- `!` indicates a position without a timestamp.
- `DDMM.mmN/S` is latitude in degrees, minutes and hundredths with hemisphere.
- `T` is the symbol **table** character (`/` or `\`).
- `DDDMM.mmE/W` is longitude.
- `S` is the symbol **code** character.
- `Comment` is optional free text.

The client builds this string from your latitude/longitude and selected symbol.  Your default comment is appended automatically.

### AX.25 & KISS Encoding

AX.25 UI frames are constructed by concatenating:

1. **Destination and Source addresses** (each 7 bytes) encoded with callsign, SSID and HDLC control bits.
2. **Digipeater path** addresses.
3. **Control (0x03)** and **PID (0xF0)** fields.
4. **Information field** containing the APRS payload.

The resulting raw frame is then encapsulated into a **KISS frame**:

- Start with `FEND (0xC0)`, followed by a command byte (`0x00` for data).
- Escape any occurrence of `FEND (0xC0)` and `FESC (0xDB)` in the payload using `FESC TFEND (0xDB 0xDC)` and `FESC TFESC (0xDB 0xDD)` respectively.
- End with `FEND`.

The client implements this encoding internally and does not rely on external libraries.

---

## Configuration File & Persistence

The client saves your station settings in a JSON file named **`aprs_tui_config.json`**.  When you exit the program, it attempts to write this file to one of several candidate locations in the following order:

1. The directory where `aprs_tui.py` resides.
2. Your home directory as `.aprs_tui_config.json`.
3. The current working directory from which you launched the script.

On startup it looks for the configuration file in the same order and loads the first one it finds.  If no configuration exists, default values are used and you are prompted to enter your settings.  Should no candidate location be writable, the configuration is not saved; you will need to re‑enter parameters each time.

---

## Troubleshooting

- **“Unable to connect to TNC”** – Ensure that your TNC is running, that the KISS port is enabled (see `direwolf.conf`), and that you specified the correct host and port.  Some firewalls may block local TCP connections.
- **Configuration not saved** – Verify that at least one of the candidate locations (script directory, home, working directory) is writable by your user.  Running the script from a location where you lack write permissions will prevent the config file from being created.
- **Prompt disappears quickly** – The program temporarily disables non‑blocking input during prompts.  If you still cannot see the prompt, enlarge your terminal window or scroll up to make space.
- **Unicode decode errors** – APRS messages are displayed using ISO‑8859‑1 (`latin-1`) decoding.  Non‑ASCII bytes may be shown as replacement characters.  This is normal for binary payloads.

---

## Contributing

Contributions are welcome!  To submit a patch:

1. Fork the repository on GitHub.
2. Create a branch for your feature or fix.
3. Commit your changes with descriptive messages.
4. Open a pull request explaining your work.

Before submitting, please run `python3 -m py_compile aprs_tui.py` to ensure there are no syntax errors.  Enhancements may include APRS‑IS connectivity, periodic beaconing, message retries, UI improvements or additional protocol support (e.g. AGWPE).

---

*This guide was generated to accompany the PyttiAPRS TUI Client and summarises both user operations and internal protocol details.  It references the APRS specification for message and position formatsm.packet-radio.net/packet/aprs-wb2osz/Understanding-APRS-Packets.pdf#:~:text=2.5.1%20Simple%20Case%20,onlyhttps://raw.githubusercontent.com/python-aprs/aprs3/main/aprs/position.py#:~:text=lat%2C%20long%2C%20sym_table_id%2C%20symbol_code%2C%20ambiguity%3DNone%2C, and explains KISS framinghttps://thomask.sdf.org/blog/2018/12/15/sending-raw-ax25-python.html#:~:text=There%20are%20four%20main%20steps,involved for developers interested in extending the software.*
