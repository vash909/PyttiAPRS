
# PyttiAPRS User Guide

## Overview

**PyttiAPRS** is a minimal, lightweight APRS client with a text‑based user interface (TUI). It allows you to send and receive AX.25 frames via a KISS‑compatible TNC such as *Direwolf*. All KISS framing/unframing and AX.25 encoding is implemented internally, so there are no external dependencieshttps://github.com/vash909/PyttiAPRS/#:~:text=,No%20external%20packages%20needed. The application provides a scrolling packet log, a side bar listing heard stations and shortcuts for quick replies.

## Key Features

- **Built‑in KISS I/O** – native KISS frame wrapping/unwrapping and AX.25 encode/decodehttps://github.com/vash909/PyttiAPRS/#:~:text=,No%20external%20packages%20needed.
- **APRS messages with acknowledgements** – composes APRS messages with proper 9‑character destination padding and an optional `{NNN` message ID for ACKshttps://github.com/vash909/PyttiAPRS/#:~:text=,ackNNN; received `ackNNN` frames are recognised.
- **Position beacons** – sends uncompressed position beacons with configurable latitude/longitude, symbol table (`/` or `\`) and symbol codehttps://github.com/vash909/PyttiAPRS/#:~:text=,plus%20an%20optional%20default%20comment.
- **TUI with mouse support** – the left pane shows a packet log and the right pane shows the “Heard” list; clicking a callsign sets it as the default destinationhttps://github.com/vash909/PyttiAPRS/#:~:text=,callsign%20to%20target%20it%20quickly.
- **Quick replies** – the `1` and `2` keys send predefined messages to the selected station; the labels shown in the command bar reflect the texts defined in the configuration filehttps://github.com/vash909/PyttiAPRS/#:~:text=,or%20prompted%29%20station.
- **Resend controls** – `r` repeats the last message, `t` repeats the last raw packethttps://github.com/vash909/PyttiAPRS/#:~:text=,repeats%20the%20last%20raw%20payload.
- **ACK toggle** – press `a` to toggle the inclusion of the message ID for ACKshttps://github.com/vash909/PyttiAPRS/#:~:text=,aren%E2%80%99t%20supported%20on%20a%20pass.
- **Config persistence** – on exit, your settings are saved to the first writable file among `./aprs_tui_config.json`, `~/.aprs_tui_config.json` and `./aprs_tui_config.json` in the current directoryhttps://github.com/vash909/PyttiAPRS/#:~:text=,the%20first%20writable%20path%20among; the saved fields include callsign, TOCALL, path, coordinates, symbol, host/port, default position comment, quick messages, ACK preference and log filehttps://github.com/vash909/PyttiAPRS/#:~:text=Persisted%20fields%20include%3A%20callsign%2C%20tocall%2C,comment%2C%20quick%E2%80%91messages%2C%20and%20log%20file.
- **File logging** – every sent or received packet is appended to `aprs_tui.log`https://github.com/vash909/PyttiAPRS/#:~:text=,%28configurable.
- **Custom quick messages** – the texts associated with the `1` and `2` keys are defined in `quick_msg1` and `quick_msg2` in your config file and are displayed in the command bar.

## Requirements

- Python ≥ 3.7https://github.com/vash909/PyttiAPRS/#:~:text=Requirements.
- A KISS‑compatible TNC reachable via TCP (Direwolf is recommended)https://github.com/vash909/PyttiAPRS/#:~:text=Requirements.
- A terminal with at least 80×24 charactershttps://github.com/vash909/PyttiAPRS/#:~:text=Requirements.

No third‑party Python libraries are requiredhttps://github.com/vash909/PyttiAPRS/#:~:text=Requirements.

## Installation

1. **Clone the repository**

   ```bash
   git clone https://github.com/vash909/PyttiAPRS.git
   cd PyttiAPRS
   ```

2. **(Optional) Verify the code compiles**

   The application is a single Python script and does not need compiling. To verify that the code is syntactically correct you can run:

   ```bash
   python3 -m py_compile PyttiAPRS.py
   ```

   This command should complete without errorshttps://github.com/vash909/PyttiAPRS/#:~:text=Contributing.

3. **Prepare your TNC**

   Start your KISS TNC (e.g. Direwolf) with the TCP interface enabled. Examples assume port `8001`https://github.com/vash909/PyttiAPRS/#:~:text=1,Run.

4. **Run the application**

   ```bash
   python3 PyttiAPRS.py
   ```

   At the first run you will be asked for the callsign, TOCALL (software identifier), digipeater path, latitude/longitude and their directions, symbol table, symbol code and an optional default position commenthttps://github.com/vash909/PyttiAPRS/#:~:text=3,Optional%20default%20position%20comment. These values can be edited later via the `c` key or by editing the JSON configuration file.

5. **Configuration persistence**

   When quitting the application with `q`, your settings are saved to the first writable pathhttps://github.com/vash909/PyttiAPRS/#:~:text=,the%20first%20writable%20path%20among. You can edit the JSON file manually to customise fields such as `quick_msg1`, `quick_msg2` and `ack_enabled`.

### Running from source and compiling

PyttiAPRS is pure Python; there are no binary releases. The only “compiler” is `python3 -m py_compile`, which generates `.pyc` files for faster startup but is not essential.

## Usage

### Starting the interface

1. Ensure your TNC (Direwolf or another) is running on the configured port.
2. Run `python3 PyttiAPRS.py`.
3. If this is the first run, enter the station parameters when prompted. Subsequent runs will automatically load the values from the JSON file.

### Screen layout

- **Status bar (first line)** – shows the callsign, TOCALL, path, coordinates, symbol and ACK state.
- **Command bar (second line)** – lists the single‑key commands. The labels for `1` and `2` reflect the configured quick messages; `a` toggles the ACK state.
- **Packet log (left column)** – displays sent and received packets. Your callsign is highlighted in any packet where it appears, making replies easy to spot.
- **Heard list (right column)** – lists the unique callsigns heard. Clicking a callsign with the mouse selects it as the default destination for the next message.

Input prompts always appear at the bottom of the screen, below the log, even when the log fills the window.

### Key commands

| Key | Action |
|---|---|
| `m` | Compose and send an APRS message. The default destination is the selected station; if ACKs are enabled an ID is added. |
| `p` | Send a position beacon using the stored parameters and comment. |
| `c` | Edit the configuration (callsign, TOCALL, path, coordinates, symbol, comment). |
| `d` | Send a raw APRS packet with no addressee or ID. |
| `t` | Repeat the last raw packet. |
| `r` | Repeat the last message, preserving the destination and, if ACKs are enabled, the same ID. |
| `1` / `2` | Send the quick messages defined in `quick_msg1` / `quick_msg2`. |
| `x` | Clear the message log in the UI. |
| `h` | Clear the “Heard” list. |
| `a` | Toggle ACK on/off. When disabled, messages omit `{NNN`. |
| `q` | Quit the application, saving the configuration. |

### Mouse interaction

Click a callsign in the Heard list to select it as the default destinationhttps://github.com/vash909/PyttiAPRS/#:~:text=Mouse%3A%20click%20a%20callsign%20in,selected%20in%20the%20heard%20list. After selection, pressing `m`, `1` or `2` will automatically target the chosen callsign (press `Enter` to confirm).

### Editing the configuration

Press `c` to edit the configuration while running. You can change:

- Callsign
- TOCALL (software identifier)
- Digipeater path (comma or space separated list)
- Latitude and longitude with directions (N/S, E/W)
- Symbol table and symbol code
- Default position comment

The JSON file also stores:

- `quick_msg1` and `quick_msg2` – the texts associated with the `1` and `2` keys.
- `ack_enabled` – whether ACKs are on by default.
- `log_file` – path/name of the log file.

To permanently modify the quick messages or ACK behaviour, edit these entries in the JSON file and restart the program by pressing "q".

### Sending messages

When pressing `m` you are prompted first for the destination callsign (pre‑filled with the selected callsign) and then for the message text. The application pads the destination to 9 characters and, if ACKs are enabled, appends an identifier `{NNN`https://github.com/vash909/PyttiAPRS/#:~:text=,ackNNN.

### Position beacons

Press `p` to send a position beacon. This uses the stored coordinates, symbol table and symbol code, and the default commenthttps://github.com/vash909/PyttiAPRS/#:~:text=,plus%20an%20optional%20default%20comment.

### Raw packets

The `d` key allows you to enter and send a raw APRS payload. The text is encoded in Latin‑1 and sent as‑is with TOCALL as the AX.25 destination; no ID or padding is added.

### Logging

Each sent or received packet is logged to `aprs_tui.log`. Every log line contains a timestamp and a compact header `SRC> DEST PATH: text`https://github.com/vash909/PyttiAPRS/#:~:text=,DEST%20PATH...%3A%20text. The log file path and name are configurable.

### Tips

- For satellite operation it’s often best to disable ACKs (`a`) so messages don’t include the IDhttps://github.com/vash909/PyttiAPRS/#:~:text=,so%20messages%20don%E2%80%99t%20carry%20IDs.
- Use the Heard list and mouse to reply quickly without typing callsignshttps://github.com/vash909/PyttiAPRS/#:~:text=,quick%20replies%20without%20retyping%20callsigns.
- Keep your terminal at least 80×24 for optimal layouthttps://github.com/vash909/PyttiAPRS/#:~:text=,your%20terminal%20window%20to%20save.
- Always exit with `q` to ensure the configuration and log are savedhttps://github.com/vash909/PyttiAPRS/#:~:text=,to%20save%20changes%20and%20log.
- Incoming packets that contain your callsign highlight it to help you spot replies.

### Troubleshooting

- **Cannot connect to the TNC** – make sure the TNC is running and that the host/port match those configuredhttps://github.com/vash909/PyttiAPRS/#:~:text=Troubleshooting.
- **Configuration not saved** – ensure you are running the script in a writable location, as it saves to the first available pathhttps://github.com/vash909/PyttiAPRS/#:~:text=,the%20first%20writable%20path%20among.
- **Strange characters** – payloads are decoded using Latin‑1; binary or non‑ASCII data may appear with substitution charactershttps://github.com/vash909/PyttiAPRS/#:~:text=,may%20be%20rendered%20with%20substitutions.

### Limitations and scope

- Only unconnected AX.25 UI frames are decoded; connected‑mode frames are ignoredhttps://github.com/vash909/PyttiAPRS/#:~:text=,Connected%E2%80%91mode%20frames%20are%20ignored.
- ACKs are recognised but there is no automatic retry of un‑ACKed messageshttps://github.com/vash909/PyttiAPRS/#:~:text=,un%E2%80%91ACKed%20messages%20is%20not%20implemented.
- The program has been tested primarily with KISS interfaces over TCP (e.g. Direwolf)https://github.com/vash909/PyttiAPRS/#:~:text=,Direwolf.

## Contributing

Pull requests are welcomehttps://github.com/vash909/PyttiAPRS/#:~:text=Contributing:

1. Fork the repository and create a dedicated branch for your changes.
2. Keep your changes focused and well commented.
3. Verify the syntax with `python3 -m py_compile PyttiAPRS.py`https://github.com/vash909/PyttiAPRS/#:~:text=Contributing.
4. Open a pull request describing the changes and, if the UI is affected, include screenshots.
5. Respect the existing coding style and add docstrings/comments as needed.

## License and author

This project is released under the **Apache 2.0** licensehttps://github.com/vash909/PyttiAPRS/#:~:text=,net.
Original author: Lorenzo Gianlorenzi (IU1BOT) — `iu1bot@xzgroup.net`https://github.com/vash909/PyttiAPRS/#:~:text=,net.

---

This guide provides everything you need to install, configure, use and contribute to PyttiAPRS. For more technical details see the comments inside `PyttiAPRS.py` or the project’s official README.
