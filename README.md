
Overview
--------
PyttiAPRS is a curses-based TUI client for APRS over a KISS TNC (e.g., Direwolf).
It can send/receive APRS UI frames, transmit uncompressed position beacons,
and display the AX.25 path with a simple, keyboard-driven interface.

What’s new today (2025-08-08)
-----------------------------
• Configurable quick messages: keys **1** and **2** send phrases read from the JSON
  config file (`quick_msg1`, `quick_msg2`). The command bar shows the configured text.
  
• RX/TX header parity: for transmitted packets, the field after `>` now shows the
  configured **TOCALL** (matching what you see for RX). The APRS message addressee
  stays inside the payload (`::ADDRESSEE:...`).
  
• Aligned `>` on the source: the source callsign field is padded so that the `>`
  character is vertically aligned across lines. No extra padding is applied to
  destination and digipeater callsigns; they are simply separated by spaces.
  
• File logging: every RX/TX packet is appended to a configurable log file
  (`log_file`), including timestamp, header, and payload.
  
• Dynamic command bar: shows the actual text of the configured quick replies.

• Mouse quick-select: click a callsign in the “Heard” pane to make it the default
  destination for messages/quick replies (existing feature, now documented).

Display examples
----------------
The `>` is column-aligned; the path is shown without extra padding beyond single spaces.

17:21:37 IU1BOT    > JN44QH IR1ZXE-11* WIDE2-1: …
17:23:18 IR1ZXE-11 > APMI04 WIDE1-1: …
17:25:56 IN3DNS-13 > T5SWU4 IR1ZXE-11* WIDE1* WIDE2-1: …

Note: in TX, the field after `>` is the TOCALL (software identifier). The APRS
message “addressee” remains inside the payload (`::ADDRESSEE:`).

Quick keys
----------
m  compose/send a message (prompts for destination and text; uses selected “Heard” station as default)
p  send position beacon
c  configure station (callsign, tocall, path, position, symbol, host/port, comment)
x  clear messages
h  clear “Heard” list
d  send raw APRS payload (no addressee or ID)
t  repeat last raw
r  repeat last message (reuses ID if ACK is enabled)
1  send `quick_msg1` from JSON (text is shown in command bar)
2  send `quick_msg2` from JSON (text is shown in command bar)
a  toggle ACK on/off
q  quit

Configuration file (JSON)
-------------------------
The app looks for `aprs_tui_config.json` in this order (first writable location wins):
1) script directory, 2) user home as `.aprs_tui_config.json`, 3) current working directory.
   IMPORTANT: REMEMBER TO PRESS "Q" INSTEAD OF CLOSING YOUR TERMINAL TO SAVE YOUR PREFERENCIES INTO THE CONFIG FILE!

Supported keys (new ones in **bold**):
- callsign: string (e.g., "IK2ABC-7")
- tocall: string (max 6, e.g., "APZ001")
- path: list of strings (e.g., ["RS0ISS","WIDE2-1"])
- latitude: float; longitude: float
- symbol_table: "/" or "\"
- symbol_code: single character (e.g., ">")
- host: string (default "localhost")
- port: int (default 8001)
- pos_comment: string
- **quick_msg1**: string (default "QSL? 73")
- **quick_msg2**: string (default "QSL! 73")
- **log_file**: string (default "aprs_tui.log")

Logging
-------
Each log entry contains local time, aligned header, and text. Generic format:
HH:MM:SS SRC> DEST DIGI1 DIGI2: payload

Technical notes
---------------
• APRS message payload uses `::ADDRESSEE:TEXT{ID}` (ADDRESSEE padded to 9 chars;
  ID optional when ACK is enabled).
  
• Position beacons: APRS uncompressed format with configurable symbol/table and comment.

• TX uses your TOCALL as the AX.25 destination; the APRS addressee remains in the payload.

Known limitations
-----------------
• Only AX.25 UI frames are encoded/decoded (control=0x03, PID=0xF0). No connected-mode sessions.

• No automatic retry for unacknowledged messages (use `r` to manually resend).

Operational tips
----------------
• For satellite operation you may prefer to disable ACKs (`a`).

• With quick replies, first click the target in the “Heard” list to send without typing.

• Keep the path minimal to reduce channel congestion.

Changelog (2025-08-08)
----------------------
- Added `quick_msg1` / `quick_msg2` in JSON + dynamic command bar.
- TX header shows TOCALL (parity with RX); message addressee remains in payload.
- `>` alignment on the source field; no extra padding on path.
- Configurable file logging (`log_file`).

