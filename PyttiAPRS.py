#!/usr/bin/env python3
"""
aprs_tui.py
==============

This script implements a simple terminal user interface (TUI) for making
APRS AX.25 contacts via a KISS‑compatible TNC such as Direwolf.  The
application connects to a KISS TCP port, encodes APRS position and
message frames and displays incoming packets in a scrolling window.

Features
--------

* **KISS connectivity:**  Connects to a KISS TNC running on the local
  machine (host/port configurable).  The program performs basic KISS
  framing and unframing without relying on external libraries.
* **AX.25 encoding/decoding:**  Minimal routines for encoding and
  decoding AX.25 UI frames are included.  Only unconnected (UI) frames
  are supported; connected AX.25 sessions are beyond the scope of this
  application.
* **APRS message support:**  Messages can be composed and sent to
  another station.  The addressee field is padded to nine characters as
  required by the APRS standard【287604055694888†L1110-L1154】.  An optional
  message ID is appended automatically to each outgoing message to
  facilitate acknowledgements.  Received message acknowledgements are
  recognised and printed in the log.
* **APRS position support:**  A position beacon (uncompressed format)
  can be transmitted on demand.  Latitude/longitude, symbol table
  selector and symbol code can be configured.
* **Heard stations:**  A side panel lists unique callsigns heard since
  startup.
* **Configurable station parameters:**  Callsign (including SSID), the
  software identifier (destination callsign), digipeater path, KISS
  host/port and position parameters can be edited from within the
  application.

This program is intentionally self‑contained and does not require
external dependencies such as the ``kiss3`` or ``ax253`` packages.  It
is not intended to be a drop‑in replacement for sophisticated APRS
clients such as UISS but provides the core features required for
satellite APRS messaging via a local TNC.

Usage
-----

Run the script from a terminal capable of 80×24 characters or larger:

```
$ python3 aprs_tui.py
```

When started for the first time the program will prompt for basic
station settings: your callsign (with optional SSID), a software
identifier (“tocall”), digipeater path and position.  These values
persist only for the current session.  The bottom line shows a list
of single‑character commands:

```
m → compose and send an APRS message
p → send a position beacon
c → change station settings
q → quit the program
```

The main window displays received packets with timestamps.  A side bar
shows a list of unique stations heard.  The user interface is built
using the standard ``curses`` module and avoids external libraries.

Limitations
-----------

* Only unconnected UI frames are decoded.  Frames containing
  connected‑mode supervisory or information packets will be ignored.
* The AX.25 encoding implemented here uses the commonly used scheme
  where bits 5 and 6 of the SSID byte are set to 1 and bit 0
  indicates end of address field.  This matches the typical encoding
  used by software TNCs such as Direwolf and by the example code
  available online【677775699448989†L41-L46】.  It differs from the
  implementation found in the ``ax253`` library (which uses bit 7
  instead of bit 0 for the HDLC flag) but works correctly with
  Direwolf's KISS implementation.
* Message acknowledgements are recognised but the program does not
  automatically retry unacknowledged messages.

Author: Lorenzo Gianlorenzi IU1BOT - iu1bot@xzgroup.net
License: This code is provided under the Apache 2.0 licence.  Portions
of the APRS message formatting are based on the published APRS
specification【287604055694888†L1110-L1154】 and are in the public domain.
"""

import curses
import os
import socket
import threading
import time
import queue
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import json

# Potential locations for the configuration file.  The program will
# search for a saved configuration in these locations in order and will
# attempt to save to the first location that permits writing.  This
# increases the likelihood that settings persist across sessions.
CONFIG_PATH_CANDIDATES = [
    # Directory where this script resides
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aprs_tui_config.json'),
    # User's home directory
    os.path.join(os.path.expanduser('~'), '.aprs_tui_config.json'),
    # Current working directory
    os.path.join(os.getcwd(), 'aprs_tui_config.json'),
]

def load_saved_config() -> Optional[dict]:
    """Load previously saved configuration from one of the candidate paths.

    Returns a dictionary with configuration values or ``None`` if none of
    the candidate files exist or if parsing fails.
    """
    for path in CONFIG_PATH_CANDIDATES:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data
        except FileNotFoundError:
            continue
        except Exception:
            # ignore malformed config and keep searching
            continue
    return None

def get_writable_config_path() -> Optional[str]:
    """Return the first candidate path that can be opened for writing.

    If no path can be written to, returns ``None``.  The function attempts
    to open each candidate file in write mode, closing it immediately on
    success.  Directories are not created automatically; all candidate
    directories should already exist.
    """
    for path in CONFIG_PATH_CANDIDATES:
        try:
            # Attempt to open the file for writing without truncating
            # using 'a' mode (append) to avoid overwriting existing data
            with open(path, 'a', encoding='utf-8'):
                return path
        except Exception:
            continue
    return None

def save_config(cfg: 'StationConfig') -> None:
    """Write the current station configuration to the first writable path.

    Only a subset of fields are persisted (callsign, tocall, path,
    latitude, longitude, symbol table and code, default position comment,
    host and port).  The message ID counter is not saved because it
    should reset with each run.
    """
    data = {
        'callsign': cfg.callsign,
        'tocall': cfg.tocall,
        'path': cfg.path,
        'latitude': cfg.latitude,
        'longitude': cfg.longitude,
        'symbol_table': cfg.symbol_table,
        'symbol_code': cfg.symbol_code,
        'host': cfg.host,
        'port': cfg.port,
        'pos_comment': cfg.pos_comment,
    }
    path = get_writable_config_path()
    if path is None:
        return
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f)
    except Exception:
        pass


###############################################################################
#                             AX.25/KISS routines                             #
###############################################################################

def encode_ax25_address(call: str, ssid: int = 0, last: bool = False) -> bytes:
    """Encode a callsign and SSID into a 7‑byte AX.25 address field.

    The callsign is padded to six characters, converted to uppercase and
    each character is shifted left by one bit.  The SSID field is
    constructed by shifting the SSID into bits 1–4 of the final byte and
    setting bits 5 and 6 to 1 as required by the AX.25 standard.  Bit 0
    of the final byte is set to 1 for the last address in the header and
    left at 0 otherwise【287604055694888†L1110-L1154】.

    :param call: Callsign (without SSID suffix).  Will be truncated or
        padded to six characters.
    :param ssid: SSID number (0–15).
    :param last: Whether this address is the last in the address list.
    :return: Seven bytes representing the AX.25 address.
    """
    call = (call.upper()[:6]).ljust(6)
    encoded = bytearray()
    for ch in call:
        encoded.append((ord(ch) << 1) & 0xFE)
    # Construct SSID/control byte
    ssid_byte = ((ssid & 0x0F) << 1) | 0x60  # place SSID in bits 1–4, set bits 5–6
    if last:
        ssid_byte |= 0x01  # set bit0 if this is the last address
    encoded.append(ssid_byte)
    return bytes(encoded)


def decode_ax25_address(addr: bytes) -> Tuple[str, int, bool]:
    """Decode a 7‑byte AX.25 address into callsign, SSID and last flag.

    The inverse of :func:`encode_ax25_address`.  Callsign characters are
    obtained by shifting each byte right by one bit.  The SSID is read
    from bits 1–4 of the final byte and the last flag from bit 0.【287604055694888†L1110-L1154】

    :param addr: Seven bytes representing an AX.25 address field.
    :return: (callsign, ssid, last)
    """
    if len(addr) != 7:
        raise ValueError("AX.25 address must be 7 bytes long")
    call = ''.join(chr((b >> 1) & 0x7F) for b in addr[:6]).strip()
    ssid = (addr[6] >> 1) & 0x0F
    last = bool(addr[6] & 0x01)
    return call, ssid, last


def encode_ax25_frame(dest: str, source: str, path: List[str], info: bytes) -> bytes:
    """Assemble an AX.25 UI frame from destination, source and path.

    All addresses must include the SSID suffix separated by a dash (e.g.
    ``N0CALL-9``).  The destination field typically contains the so‑called
    ``tocall`` identifying the sending software.  The path is a list of
    digipeaters to include between source and destination (e.g.
    ["ARISS","RELAY"], etc).  This function encodes the addresses
    sequentially and appends the standard UI control (0x03) and PID
    (0xF0) fields before the information payload.

    :param dest: Destination callsign with optional SSID (e.g. ``APZ001``).
    :param source: Source callsign with optional SSID (e.g. ``IK2ABC-7``).
    :param path: Sequence of digipeater callsigns with optional SSIDs.
    :param info: Information field (payload) as bytes.
    :return: Raw AX.25 frame (without flags or FCS) ready for KISS encoding.
    """
    # Helper to split callsign and SSID
    def split_call(c: str) -> Tuple[str, int]:
        if '-' in c:
            cs, ss = c.split('-', 1)
            try:
                return cs, int(ss)
            except ValueError:
                return cs, 0
        return c, 0

    # Encode addresses
    addresses = []
    # Destination (not last unless no other addresses)
    dest_call, dest_ssid = split_call(dest)
    addresses.append(encode_ax25_address(dest_call, dest_ssid, last=False))
    # Source (last if there is no path)
    src_call, src_ssid = split_call(source)
    last_flag = len(path) == 0
    addresses.append(encode_ax25_address(src_call, src_ssid, last=last_flag))
    # Path (all but last flagged false, last flagged true)
    if path:
        for i, dig in enumerate(path):
            dig_call, dig_ssid = split_call(dig)
            is_last = i == (len(path) - 1)
            addresses.append(encode_ax25_address(dig_call, dig_ssid, last=is_last))

    frame = b''.join(addresses)
    # Append UI control field (0x03) and no‑layer3 PID (0xF0) then info
    frame += b'\x03\xF0' + info
    return frame


def decode_ax25_frame(frame: bytes) -> Optional[Tuple[str, str, List[str], bytes]]:
    """Decode a raw AX.25 frame into (dest, source, path list, info).

    This function understands only UI frames with a control byte of
    0x03 and a PID of 0xF0.  If the frame does not match this pattern
    ``None`` is returned.  Addresses are decoded until the last flag is
    encountered as described in :func:`encode_ax25_address`.

    :param frame: Raw AX.25 frame without flags or FCS.
    :return: Tuple of (destination callsign, source callsign,
        path list, info bytes) or ``None`` if unsupported.
    """
    # Minimum length: dest(7) + src(7) + ctrl(1) + pid(1)
    if len(frame) < 16:
        return None
    # Iterate through address fields
    addresses = []
    idx = 0
    last_found = False
    while not last_found and idx + 7 <= len(frame):
        addr_bytes = frame[idx:idx + 7]
        call, ssid, last = decode_ax25_address(addr_bytes)
        addresses.append(f"{call}-{ssid}" if ssid else call)
        last_found = last
        idx += 7
    # At least two addresses (dest + source)
    if len(addresses) < 2:
        return None
    dest, source = addresses[0], addresses[1]
    path = addresses[2:]
    # Extract control and PID
    if idx + 2 > len(frame):
        return None
    control = frame[idx]
    pid = frame[idx + 1]
    if control != 0x03 or pid != 0xF0:
        # Only UI frames with no L3
        return None
    info = frame[idx + 2:]
    return dest, source, path, info


def kiss_encode(ax25_frame: bytes) -> bytes:
    """Encode a raw AX.25 frame into a KISS frame.

    A KISS data frame is constructed by wrapping the payload with FEND
    (0xC0) bytes and prefixing it with a data frame type (0x00).  Any
    occurrence of FEND (0xC0) or FESC (0xDB) in the payload is
    escaped according to the KISS protocol【677775699448989†L41-L46】.

    :param ax25_frame: Raw AX.25 frame (without flags or FCS).
    :return: KISS‑encoded bytes ready to be sent on the wire.
    """
    FEND = 0xC0
    FESC = 0xDB
    TFEND = 0xDC
    TFESC = 0xDD
    out = bytearray()
    out.append(FEND)
    out.append(0x00)  # data frame type
    for b in ax25_frame:
        if b == FEND:
            out.extend([FESC, TFEND])
        elif b == FESC:
            out.extend([FESC, TFESC])
        else:
            out.append(b)
    out.append(FEND)
    return bytes(out)


def kiss_unframe(stream: bytes) -> Tuple[List[bytes], bytes]:
    """Extract one or more KISS frames from a stream of bytes.

    This helper scans ``stream`` for 0xC0 delimiters and returns a list
    of decoded AX.25 frames (with escape sequences removed) as well as
    any trailing bytes that constitute an incomplete frame.  Only data
    frames (type 0x00) are returned; other command frames are ignored.

    :param stream: Byte stream containing zero or more KISS frames.
    :return: (list of AX.25 frames, remainder)
    """
    FEND = 0xC0
    FESC = 0xDB
    TFEND = 0xDC
    TFESC = 0xDD
    frames = []
    current = None
    i = 0
    while i < len(stream):
        b = stream[i]
        if b == FEND:
            if current is not None:
                # End of current frame
                if len(current) >= 1:
                    cmd = current[0]
                    data = current[1:]
                    if cmd == 0x00:
                        frames.append(bytes(data))
                current = None
            else:
                # Start of new frame
                current = bytearray()
            i += 1
            continue
        if current is None:
            # Data outside of a frame – ignore
            i += 1
            continue
        # Handle escape sequences
        if b == FESC:
            if i + 1 < len(stream):
                next_b = stream[i + 1]
                if next_b == TFEND:
                    current.append(FEND)
                elif next_b == TFESC:
                    current.append(FESC)
                else:
                    # Invalid escape; skip
                    pass
                i += 2
                continue
        current.append(b)
        i += 1
    remainder = bytes(current) if current else b''
    return frames, remainder


###############################################################################
#                            APRS payload routines                            #
###############################################################################

def build_aprs_message(addressee: str, text: str, msg_id: Optional[int] = None) -> bytes:
    """Construct an APRS message payload.

    The addressee must be padded to exactly nine characters as required
    by the APRS specification【287604055694888†L1110-L1154】.  The message text should
    not exceed 67 characters; if it does, it will be truncated.  When
    ``msg_id`` is provided it is appended with a leading ``{`` so that
    the receiving station can acknowledge the message.

    :param addressee: Destination callsign of the message.
    :param text: Message body (will be truncated to 67 characters).
    :param msg_id: Optional message identifier number.
    :return: Bytes of the information field ready to be inserted into
        the AX.25 frame.
    """
    addressee = addressee.upper()[:9].ljust(9)
    text = text[:67]
    info = f':{addressee}:{text}'
    if msg_id is not None:
        # Append message ID with {, zero‑pad to 3 digits as per example
        info += '{%03d' % (msg_id % 1000)
    return info.encode('ascii')


def build_aprs_position(
    latitude: float,
    longitude: float,
    symbol_table: str = '/',
    symbol_code: str = '>',
    comment: str = ''
) -> bytes:
    """Construct an uncompressed APRS position payload.

    The uncompressed position format uses a leading ``!`` character,
    followed by latitude and longitude in degrees/minutes and two
    symbols identifying the station【916318889271047†L48-L61】.  An optional
    free‑form comment may follow the symbol code and will appear in
    APRS clients as text.  The latitude is formatted as DDMM.mmN/S and
    longitude as DDDMM.mmE/W.  The symbol table and symbol code
    determine the map symbol shown by APRS clients.  See the APRS
    specification for valid values.

    :param latitude: Latitude in decimal degrees (positive north,
        negative south).
    :param longitude: Longitude in decimal degrees (positive east,
        negative west).
    :param symbol_table: Symbol table identifier (``'/'`` or ``'\'``).
    :param symbol_code: Symbol code (e.g. ``'>'`` for a car, ``'^'`` for
        a house).
    :param comment: Optional comment text to append after the symbol.
    :return: Bytes of the information field ready to be inserted into
        the AX.25 frame.
    """
    # Convert latitude to degrees/minutes
    lat_abs = abs(latitude)
    lat_deg = int(lat_abs)
    lat_min = (lat_abs - lat_deg) * 60
    lat_dir = 'N' if latitude >= 0 else 'S'
    # Convert longitude to degrees/minutes
    lon_abs = abs(longitude)
    lon_deg = int(lon_abs)
    lon_min = (lon_abs - lon_deg) * 60
    lon_dir = 'E' if longitude >= 0 else 'W'
    lat_str = f"{lat_deg:02d}{lat_min:05.2f}{lat_dir}"
    lon_str = f"{lon_deg:03d}{lon_min:05.2f}{lon_dir}"
    # Assemble position string
    base = f'!{lat_str}{symbol_table}{lon_str}{symbol_code}'
    # Append optional comment if provided
    if comment:
        base += comment
    return base.encode('ascii')


###############################################################################
#                            TNC Connection Handler                            #
###############################################################################

class TNCConnection:
    """Manage the TCP connection to a KISS TNC and handle I/O.

    A separate thread is spawned to read data from the socket.  Received
    AX.25 frames are placed onto a queue for consumption by the user
    interface.  The public ``send_frame`` method KISS‑encodes and sends
    raw AX.25 frames to the TNC.
    """

    def __init__(self, host: str, port: int, message_queue: queue.Queue):
        self.host = host
        self.port = port
        self.msg_queue = message_queue
        self.sock: Optional[socket.socket] = None
        self.reader_thread: Optional[threading.Thread] = None
        self.running = False
        self.buffer = b''

    def connect(self) -> bool:
        """Open a TCP connection to the TNC.  Returns True on success."""
        try:
            self.sock = socket.create_connection((self.host, self.port), timeout=5)
            self.running = True
            self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self.reader_thread.start()
            return True
        except Exception as exc:
            self.sock = None
            self.running = False
            return False

    def close(self) -> None:
        """Close the TCP connection and stop the reader thread."""
        self.running = False
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            self.sock.close()
            self.sock = None
        # Wait for the reader thread to finish
        if self.reader_thread and self.reader_thread.is_alive():
            self.reader_thread.join(timeout=1)

    def send_frame(self, frame: bytes) -> None:
        """KISS‑encode and send a raw AX.25 frame to the TNC."""
        if not self.sock:
            return
        kiss_data = kiss_encode(frame)
        try:
            self.sock.sendall(kiss_data)
        except Exception:
            # ignore errors; the UI will show connection loss
            pass

    def _read_loop(self) -> None:
        """Continuously read from the socket and decode KISS frames."""
        while self.running and self.sock:
            try:
                data = self.sock.recv(4096)
                if not data:
                    # connection closed
                    self.running = False
                    break
                self.buffer += data
                frames, remainder = kiss_unframe(self.buffer)
                self.buffer = remainder
                for ax25 in frames:
                    decoded = decode_ax25_frame(ax25)
                    if decoded:
                        dest, source, path, info = decoded
                        # Put tuple on queue
                        self.msg_queue.put((dest, source, path, info, time.time()))
            except socket.timeout:
                continue
            except Exception:
                # Unexpected error; stop reading
                self.running = False
                break


###############################################################################
#                                User Interface                               #
###############################################################################

@dataclass
class StationConfig:
    """Configuration parameters for the station."""
    callsign: str  # e.g. "IK2ABC-7"
    tocall: str    # software identifier, e.g. "APZ001"
    path: List[str] = field(default_factory=lambda: [])
    latitude: float = 0.0
    longitude: float = 0.0
    symbol_table: str = '/'
    symbol_code: str = '>'
    host: str = 'localhost'
    port: int = 8001
    msg_id_counter: int = 1
    pos_comment: str = ''  # default comment for position beacons

    def next_msg_id(self) -> int:
        mid = self.msg_id_counter
        self.msg_id_counter += 1
        # Wrap around after 999 to keep ID within three digits
        if self.msg_id_counter > 999:
            self.msg_id_counter = 1
        return mid


class APRSTUI:
    """Curses based APRS client."""

    def __init__(self, stdscr: curses.window, cfg: StationConfig, tnc: TNCConnection):
        self.stdscr = stdscr
        self.cfg = cfg
        self.tnc = tnc
        # Received messages: list of (timestamp, source, dest, info_bytes, path)
        # The path is a list of digipeaters through which the packet travelled.
        self.messages: List[Tuple[float, str, str, bytes, List[str]]] = []
        self.heard: set = set()
        self.msg_queue: queue.Queue = tnc.msg_queue
        # Setup curses
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.timeout(100)
        # Enable colour if supported; colour 1 used to highlight our callsign
        try:
            curses.start_color()
            curses.init_pair(1, curses.COLOR_YELLOW, -1)
            self._highlight_attr = curses.color_pair(1) | curses.A_BOLD
        except Exception:
            # Fallback attribute if colours are unavailable
            self._highlight_attr = curses.A_REVERSE

    def run(self) -> None:
        """Main UI loop."""
        while True:
            # Process any incoming frames
            self._process_incoming()
            self._draw()
            try:
                c = self.stdscr.getch()
            except Exception:
                c = -1
            if c == ord('q'):
                break
            elif c == ord('m'):
                self._compose_message()
            elif c == ord('p'):
                self._send_position()
            elif c == ord('c'):
                self._edit_config()
            # small sleep to reduce CPU
            time.sleep(0.05)

    # UI helper to draw the interface
    def _draw(self) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        # Header line with station info
        status = (
            f"CALL {self.cfg.callsign} TOCALL {self.cfg.tocall} PATH "
            f"{'-'.join(self.cfg.path) if self.cfg.path else 'NONE'} "
            f"LAT {self.cfg.latitude:.4f} LON {self.cfg.longitude:.4f} "
            f"SYM {self.cfg.symbol_table}{self.cfg.symbol_code}"
        )
        self.stdscr.addstr(0, 0, status[:width - 1])
        # Commands line
        cmd_line = "m:msg  p:pos  c:cfg  q:quit"
        self.stdscr.addstr(1, 0, cmd_line[:width - 1], curses.A_DIM)
        # Determine areas
        msgs_height = height - 4
        msgs_width = width - 20
        # Draw messages box
        self.stdscr.addstr(2, 0, "Received packets:", curses.A_BOLD)
        # Show last messages
        displayed = self.messages[-msgs_height:]
        for i, msg in enumerate(displayed):
            ts, src, dest, info, path = msg
            timestr = time.strftime("%H:%M:%S", time.localtime(ts))
            # Decode info as latin1 to preserve arbitrary bytes
            try:
                text = info.decode('latin1')
            except Exception:
                text = str(info)
            # Build path string if present
            path_str = ''
            if path:
                path_str = ' via ' + ','.join(path)
            # Construct display line; omit dest if empty (beacon)
            if dest:
                line = f"{timestr} {src}> {dest}{path_str}: {text}"
            else:
                line = f"{timestr} {src}{path_str}: {text}"
            # Truncate line to available width
            truncated = line[: msgs_width - 1]
            # Highlight our callsign if present
            cs = self.cfg.callsign.upper()
            idx = truncated.upper().find(cs) if cs else -1
            row_pos = 3 + i
            if idx >= 0:
                # Write text before the callsign
                if idx > 0:
                    self.stdscr.addstr(row_pos, 0, truncated[:idx])
                # Write the callsign highlighted
                cs_end = idx + len(cs)
                if cs_end > len(truncated):
                    cs_end = len(truncated)
                highlight_text = truncated[idx:cs_end]
                self.stdscr.addstr(row_pos, idx, highlight_text, self._highlight_attr)
                # Write the remainder
                if cs_end < len(truncated):
                    self.stdscr.addstr(row_pos, cs_end, truncated[cs_end:])
            else:
                self.stdscr.addstr(row_pos, 0, truncated)
        # Draw heard stations
        self.stdscr.addstr(2, msgs_width, "Heard:", curses.A_BOLD)
        heard_list = list(self.heard)
        heard_height = height - 3
        for i in range(min(heard_height, len(heard_list))):
            self.stdscr.addstr(3 + i, msgs_width, heard_list[i][:19])
        self.stdscr.refresh()

    # Handle incoming frames from the TNC
    def _process_incoming(self) -> None:
        while not self.msg_queue.empty():
            dest, src, path, info, ts = self.msg_queue.get()
            # Add to heard list
            self.heard.add(src)
            # Recognise acknowledgements: info starts with ':' and contains ack
            if info and info.startswith(b':'):
                try:
                    payload = info.decode('latin1')
                except Exception:
                    payload = ''
                # Format ::CALLSIGN:ackNNN
                if payload[10:13] == 'ack':
                    # ack for our message ID; just display
                    self.messages.append((ts, src, dest, info, path))
                    continue
            # Save message
            self.messages.append((ts, src, dest, info, path))

    # Prompt user for a string input
    def _prompt(self, prompt: str, default: str = '') -> Optional[str]:
        curses.echo()
        self.stdscr.addstr(curses.LINES - 1, 0, ' ' * (curses.COLS - 1))
        self.stdscr.addstr(curses.LINES - 1, 0, prompt)
        self.stdscr.refresh()
        try:
            input_str = self.stdscr.getstr(curses.LINES - 1, len(prompt), 60)
            if not input_str and default:
                return default
            return input_str.decode('utf-8')
        finally:
            curses.noecho()

    # Compose and send an APRS message
    def _compose_message(self) -> None:
        # Temporarily disable non‑blocking input while composing a message
        self.stdscr.nodelay(False)
        self.stdscr.timeout(-1)
        try:
            # Get destination callsign
            dest = self._prompt("To station: ")
            if not dest:
                return
            text = self._prompt("Message: ")
            if text is None:
                return
            msg_id = self.cfg.next_msg_id()
            payload = build_aprs_message(dest, text, msg_id=msg_id)
            ax25 = encode_ax25_frame(
                self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
            )
            self.tnc.send_frame(ax25)
            # Log our own outgoing message to the UI
            ts = time.time()
            self.messages.append(
                (ts, self.cfg.callsign, dest, payload, list(self.cfg.path))
            )
        finally:
            # Restore non‑blocking mode
            self.stdscr.nodelay(True)
            self.stdscr.timeout(100)

    # Send a position beacon
    def _send_position(self) -> None:
        # Use the stored position comment directly; do not prompt each time.
        comment = self.cfg.pos_comment
        payload = build_aprs_position(
            self.cfg.latitude,
            self.cfg.longitude,
            self.cfg.symbol_table,
            self.cfg.symbol_code,
            comment,
        )
        ax25 = encode_ax25_frame(
            self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
        )
        self.tnc.send_frame(ax25)
        ts = time.time()
        self.messages.append(
            (ts, self.cfg.callsign, '', payload, list(self.cfg.path))
        )

    # Edit configuration interactively
    def _edit_config(self) -> None:
        # Temporarily disable non‑blocking input to allow the user time to type
        self.stdscr.nodelay(False)
        self.stdscr.timeout(-1)
        try:
            new_call = self._prompt(
                f"Callsign (current {self.cfg.callsign}): ", self.cfg.callsign
            )
            if new_call:
                self.cfg.callsign = new_call.strip()
            new_tocall = self._prompt(
                f"Tocall (software id) (current {self.cfg.tocall}): ", self.cfg.tocall
            )
            if new_tocall:
                self.cfg.tocall = new_tocall.strip().upper()[:6]
            path_str = self._prompt(
                f"Digipeater path comma separated (current {'-'.join(self.cfg.path)}): ",
                '-'.join(self.cfg.path)
            )
            if path_str is not None:
                # Split by comma or whitespace but keep hyphens within SSID
                self.cfg.path = [
                    p.strip().upper()
                    for p in path_str.replace(',', ' ').split()
                    if p.strip()
                ]
            # Latitude magnitude and direction
            lat_val_str = self._prompt(
                f"Latitude degrees (decimal) (current {abs(self.cfg.latitude)}): ",
                str(abs(self.cfg.latitude))
            )
            lat_dir = self._prompt(
                f"Latitude direction (N/S) (current {'N' if self.cfg.latitude >= 0 else 'S'}): ",
                'N' if self.cfg.latitude >= 0 else 'S'
            )
            try:
                lat_val = float(lat_val_str)
            except Exception:
                lat_val = abs(self.cfg.latitude)
            lat_dir = (lat_dir or ('N' if self.cfg.latitude >= 0 else 'S')).upper()
            if lat_dir not in ['N', 'S']:
                lat_dir = 'N'
            self.cfg.latitude = lat_val if lat_dir == 'N' else -lat_val
            # Longitude magnitude and direction
            lon_val_str = self._prompt(
                f"Longitude degrees (decimal) (current {abs(self.cfg.longitude)}): ",
                str(abs(self.cfg.longitude))
            )
            lon_dir = self._prompt(
                f"Longitude direction (E/W) (current {'E' if self.cfg.longitude >= 0 else 'W'}): ",
                'E' if self.cfg.longitude >= 0 else 'W'
            )
            try:
                lon_val = float(lon_val_str)
            except Exception:
                lon_val = abs(self.cfg.longitude)
            lon_dir = (lon_dir or ('E' if self.cfg.longitude >= 0 else 'W')).upper()
            if lon_dir not in ['E', 'W']:
                lon_dir = 'E'
            self.cfg.longitude = lon_val if lon_dir == 'E' else -lon_val
            # Symbol table (two choices) and code
            sym_table = self._prompt(
                f"Symbol table (/ or \\) (current {self.cfg.symbol_table}): ",
                self.cfg.symbol_table
            )
            if sym_table in ['/', '\\']:
                self.cfg.symbol_table = sym_table
            sym_code = self._prompt(
                f"Symbol code (current {self.cfg.symbol_code}): ", self.cfg.symbol_code
            )
            if sym_code:
                self.cfg.symbol_code = sym_code[0]
            # Default position comment
            pos_comm = self._prompt(
                f"Default position comment (current {self.cfg.pos_comment}): ",
                self.cfg.pos_comment
            )
            if pos_comm is not None:
                self.cfg.pos_comment = pos_comm
        finally:
            # Restore non‑blocking mode
            self.stdscr.nodelay(True)
            self.stdscr.timeout(100)


def main(stdscr: curses.window) -> None:
    # Try to load previously saved configuration
    saved = load_saved_config()
    if saved:
        # Populate StationConfig from saved data
        cfg = StationConfig(
            callsign=saved.get('callsign', ''),
            tocall=saved.get('tocall', 'APZ001'),
            path=saved.get('path', []),
            latitude=saved.get('latitude', 0.0),
            longitude=saved.get('longitude', 0.0),
            symbol_table=saved.get('symbol_table', '/'),
            symbol_code=saved.get('symbol_code', '>'),
            host=saved.get('host', 'localhost'),
            port=saved.get('port', 8001),
            pos_comment=saved.get('pos_comment', ''),
        )
    else:
        # Interactive setup if no saved configuration
        cfg = StationConfig(
            callsign='',
            tocall='APZ001',
            path=[],
            latitude=0.0,
            longitude=0.0,
            symbol_table='/',
            symbol_code='>',
            host='localhost',
            port=8001,
        )
        # Use curses prompts to obtain callsign and position
        curses.echo()
        stdscr.addstr(0, 0, "Enter your callsign (e.g. IK2ABC-7): ")
        stdscr.refresh()
        callsign = stdscr.getstr().decode('utf-8').strip()
        cfg.callsign = callsign
        curses.noecho()
        # Optionally ask tocall
        curses.echo()
        stdscr.addstr(1, 0, "Software id (tocall, default APZ001): ")
        stdscr.refresh()
        tcall_input = stdscr.getstr().decode('utf-8').strip().upper()
        if tcall_input:
            cfg.tocall = tcall_input[:6]
        curses.noecho()
        # Ask digipeater path
        curses.echo()
        stdscr.addstr(
            2,
            0,
            "Digipeater path (comma or dash separated, leave blank for none): ",
        )
        stdscr.refresh()
        path_input = stdscr.getstr().decode('utf-8').strip()
        if path_input:
            # Split by comma or whitespace but not by hyphen (hyphen is part of SSID)
            cfg.path = [
                p.strip().upper()
                for p in path_input.replace(',', ' ').split()
                if p.strip()
            ]
        curses.noecho()
        # Ask latitude (magnitude) and direction
        row = 3
        curses.echo()
        stdscr.addstr(row, 0, "Latitude degrees (decimal): ")
        stdscr.clrtoeol()
        stdscr.refresh()
        lat_val_str = stdscr.getstr().decode('utf-8').strip()
        try:
            lat_val = float(lat_val_str)
        except Exception:
            lat_val = 0.0
        curses.noecho()
        curses.echo()
        row += 1
        stdscr.addstr(row, 0, "Latitude direction (N/S) [N]: ")
        stdscr.clrtoeol()
        stdscr.refresh()
        lat_dir = stdscr.getstr().decode('utf-8').strip().upper()
        curses.noecho()
        if lat_dir not in ['N', 'S']:
            lat_dir = 'N'
        cfg.latitude = lat_val if lat_dir == 'N' else -lat_val
        # Ask longitude (magnitude) and direction
        curses.echo()
        row += 1
        stdscr.addstr(row, 0, "Longitude degrees (decimal): ")
        stdscr.clrtoeol()
        stdscr.refresh()
        lon_val_str = stdscr.getstr().decode('utf-8').strip()
        try:
            lon_val = float(lon_val_str)
        except Exception:
            lon_val = 0.0
        curses.noecho()
        curses.echo()
        row += 1
        stdscr.addstr(row, 0, "Longitude direction (E/W) [E]: ")
        stdscr.clrtoeol()
        stdscr.refresh()
        lon_dir = stdscr.getstr().decode('utf-8').strip().upper()
        curses.noecho()
        if lon_dir not in ['E', 'W']:
            lon_dir = 'E'
        cfg.longitude = lon_val if lon_dir == 'E' else -lon_val
        # Ask symbol table and code for initial position symbol
        curses.echo()
        row += 1
        stdscr.addstr(row, 0, "Symbol table (/ or \\) (default /): ")
        stdscr.clrtoeol()
        stdscr.refresh()
        sym_table_input = stdscr.getstr().decode('utf-8').strip()
        curses.noecho()
        if sym_table_input in ['/', '\\']:
            cfg.symbol_table = sym_table_input
        else:
            cfg.symbol_table = '/'
        # Symbol code
        curses.echo()
        row += 1
        stdscr.addstr(row, 0, "Symbol code (default >): ")
        stdscr.clrtoeol()
        stdscr.refresh()
        sym_code_input = stdscr.getstr().decode('utf-8').strip()
        curses.noecho()
        if sym_code_input:
            cfg.symbol_code = sym_code_input[0]
        # Ask default position comment
        curses.echo()
        row += 1
        stdscr.addstr(row, 0, "Default position comment (optional): ")
        stdscr.clrtoeol()
        stdscr.refresh()
        comment_input = stdscr.getstr().decode('utf-8').strip()
        curses.noecho()
        cfg.pos_comment = comment_input
    # Clear screen before starting UI
    stdscr.erase()
    stdscr.refresh()
    # Create message queue and TNC connection
    msg_queue = queue.Queue()
    tnc = TNCConnection(cfg.host, cfg.port, msg_queue)
    connected = tnc.connect()
    if not connected:
        stdscr.addstr(0, 0, f"Unable to connect to TNC on {cfg.host}:{cfg.port}")
        stdscr.refresh()
        time.sleep(3)
        return
    # Run UI
    ui = APRSTUI(stdscr, cfg, tnc)
    try:
        ui.run()
    finally:
        tnc.close()
        # Save configuration on exit
        save_config(cfg)


if __name__ == '__main__':
    # Initialise curses wrapper
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass