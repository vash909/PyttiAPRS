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

    This decoder handles only UI frames (control=0x03, PID=0xF0).  It
    extracts destination, source and digipeater addresses.  Each
    digipeater in the returned path is suffixed with a `*` if the
    ``has‑been‑repeated" (H) bit was set in its SSID octet.  The H bit
    is bit 7 (0x80) of the SSID byte; the extension bit (E) at bit 0
    marks the last address in the list.  Callsigns and SSIDs are
    converted to strings (e.g. ``OH7RDA-7``).  The destination and
    source are never marked with ``*`` because repeaters only set
    the H bit on digipeater addresses.

    :param frame: Raw AX.25 frame without flags or FCS.
    :return: Tuple of (destination callsign, source callsign,
        list of digipeaters (with '*' indicating repeat), info bytes) or
        ``None`` if the frame is not a UI frame or is malformed.
    """
    # Minimum length: dest(7) + src(7) + ctrl(1) + pid(1)
    if len(frame) < 16:
        return None
    addresses = []  # will store tuples (call, ssid, h_bit, e_bit)
    idx = 0
    last_found = False
    # Extract address fields.  Stop when the E (extension) bit (bit 0)
    # is set, indicating the last address.  Each address is seven
    # bytes: 6 shifted characters + SSID byte.
    while not last_found and idx + 7 <= len(frame):
        addr_bytes = frame[idx:idx + 7]
        # Decode callsign by shifting right by one bit and stripping
        call = ''.join(chr((b >> 1) & 0x7F) for b in addr_bytes[:6]).strip()
        ssid = (addr_bytes[6] >> 1) & 0x0F
        h_bit = bool(addr_bytes[6] & 0x80)
        e_bit = bool(addr_bytes[6] & 0x01)
        addresses.append((call, ssid, h_bit, e_bit))
        last_found = e_bit
        idx += 7
    # Need at least destination and source
    if len(addresses) < 2:
        return None
    # Convert destination and source to strings
    dest_call, dest_ssid, _, _ = addresses[0]
    src_call, src_ssid, _, _ = addresses[1]
    dest = f"{dest_call}-{dest_ssid}" if dest_ssid else dest_call
    source = f"{src_call}-{src_ssid}" if src_ssid else src_call
    # Build path list with '*' for digipeaters whose H bit was set
    path: List[str] = []
    for call, ssid, h_bit, _ in addresses[2:]:
        callstr = f"{call}-{ssid}" if ssid else call
        if h_bit:
            callstr += '*'
        path.append(callstr)
    # Verify sufficient length for control and PID
    if idx + 2 > len(frame):
        return None
    control = frame[idx]
    pid = frame[idx + 1]
    # Only handle UI frames (0x03) with no Layer 3 (0xF0)
    if control != 0x03 or pid != 0xF0:
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

        # Track whether acknowledgements (message IDs) are appended to outgoing
        # messages.  APRS over satellites may not support ACKs, so this can
        # be toggled at runtime via the 'a' key.  Default is True (ACKs on).
        self.ack_enabled: bool = True
        # Remember the most recently sent message so that it can be
        # retransmitted (for example if a digipeater did not repeat it).
        # Stored as a tuple (destination, text, msg_id).  msg_id may be None
        # if acknowledgements are disabled when the message was sent.
        self.last_message: Optional[Tuple[str, str, Optional[int]]] = None
        # Remember the most recently sent raw data packet (a payload without
        # addressee formatting).  Stored as the raw text string.  When
        # repeating, this text is re‑encoded and re‑sent with the same path.
        self.last_raw: Optional[str] = None

        # Record the last callsign clicked in the heard list.  When set,
        # message composition prompts will default to this destination and
        # quick‑message commands will automatically target it unless the user
        # overrides the address.  This aids mouse‑based operation.
        self.selected_heard: Optional[str] = None

        # Keep track of the list of heard stations as rendered in the last
        # screen draw.  This list is sorted alphabetically to provide a
        # stable order between draws and mouse events.  It is updated in
        # `_draw()` and used in the mouse handler to map click positions
        # back to callsigns.  Without this mapping, converting the
        # unordered `self.heard` set to a list in both places could
        # yield different orders, causing clicks to select the wrong
        # callsign or none at all.
        self.current_heard_list: List[str] = []

        # Enable mouse support so that clicks within the heard list can
        # select a callsign for quick messaging.  All mouse events are
        # reported; actual handling occurs in the main loop.
        try:
            # Enable reporting of all mouse events.  Setting mouseinterval(0)
            # causes button press and release events to be reported without
            # needing a click & release combination.
            curses.mousemask(curses.ALL_MOUSE_EVENTS)
            curses.mouseinterval(0)
        except Exception:
            pass

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
            # Quit the application
            if c == ord('q'):
                break
            # Compose and send a message
            elif c == ord('m'):
                # Compose and send a message.  If a callsign has been
                # selected in the heard list via mouse click, use it as
                # the default destination so that the user can simply
                # press Enter to accept it.  Otherwise no default is
                # provided and the user must enter a destination.
                self._compose_message()
            # Send a position beacon
            elif c == ord('p'):
                self._send_position()
            # Edit station configuration
            elif c == ord('c'):
                self._edit_config()
            # Clear all logged packets
            elif c == ord('x'):
                self.clear_messages()
            # Clear the list of heard stations
            elif c == ord('h'):
                self.clear_heard()
            # Repeat the last sent message
            elif c == ord('r'):
                self.repeat_last_message()
            # Toggle acknowledgements on/off
            elif c == ord('a'):
                self.toggle_ack()
            # Compose and send an arbitrary raw APRS payload
            elif c == ord('d'):
                self.compose_raw_data()
            # Repeat the last raw APRS payload
            elif c == ord('t'):
                self.repeat_last_raw()
            # Quick message shortcuts: send QSL? 73 or QSL! 73.  These
            # commands allow rapid replies without manual typing.  The
            # destination is taken from the currently selected callsign
            # if one is selected; otherwise the user is prompted.
            elif c == ord('1'):
                self._send_quick_message("QSL? 73")
            elif c == ord('2'):
                self._send_quick_message("QSL! 73")

            # Handle mouse clicks.  When the user clicks within the
            # heard list, record the selected callsign so that
            # subsequent message commands can use it as the default
            # destination.  If the click occurs outside the list, clear
            # any previous selection.
            elif c == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, bstate = curses.getmouse()
                except Exception:
                    bstate = 0
                # Only handle button presses (not releases) and ensure
                # coordinates are valid relative to the current layout.
                if bstate & curses.BUTTON1_PRESSED:
                    # Compute bounds for heard list
                    height, width = self.stdscr.getmaxyx()
                    msgs_width = width - 20
                    # Heard list starts at row 3 and spans up to
                    # height-5 rows.  Columns start at msgs_width.
                    start_row = 3
                    end_row = start_row + (height - 5) - 1
                    if my >= start_row and my <= end_row and mx >= msgs_width:
                        # Determine which item was clicked.  Use the
                        # current_heard_list computed in _draw() to map
                        # row indices to callsigns, ensuring consistent
                        # ordering between display and selection.
                        index = my - start_row
                        if 0 <= index < len(self.current_heard_list):
                            self.selected_heard = self.current_heard_list[index]
                        else:
                            self.selected_heard = None
                    else:
                        # Click outside heard list clears selection
                        self.selected_heard = None
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
            f"SYM {self.cfg.symbol_table}{self.cfg.symbol_code} "
            f"ACK {'ON' if self.ack_enabled else 'OFF'}"
        )
        self.stdscr.addstr(0, 0, status[:width - 1])
        # Commands line.  Include commands for clearing messages and the heard list,
        # toggling acknowledgements, and resending the last message.
        cmd_line = (
            "m:msg  p:pos  c:cfg  x:clr msgs  h:clr heard  "
            "d:raw  t:rep raw  r:repeat  1:QSL?  2:QSL!  a:ack on/off  q:quit"
        )
        # Highlight the command bar to distinguish available keys.  Use
        # reverse video for visibility; if reverse video is not available
        # curses will fall back to a reasonable attribute.
        self.stdscr.addstr(1, 0, cmd_line[:width - 1], curses.A_REVERSE)
        # Determine areas
        # Reserve two lines at the bottom (one blank and one for prompts) to
        # ensure that input prompts do not overlap with the scrolling message
        # area even when the screen is full.  With a height of N, messages and
        # heard lists occupy up to rows 3..(N-3).
        msgs_height = height - 5
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
        # Draw heard stations.  Reserve the bottom line for prompts by limiting
        # the height of the list to match the messages area.  Without this
        # constraint the heard list would overwrite the prompt line when the
        # screen is full, causing the input prompt to appear mid‑screen.
        self.stdscr.addstr(2, msgs_width, "Heard:", curses.A_BOLD)
        # Convert the heard set into a sorted list to provide a stable
        # ordering for display and mouse selection.  Store it on
        # self.current_heard_list so the mouse handler can map row
        # indices to callsigns reliably.
        heard_list = sorted(self.heard)
        self.current_heard_list = heard_list
        # Use the same height as the messages area (height - 4) to avoid
        # drawing into the last line of the terminal reserved for user input.
        heard_height = height - 5
        for i in range(min(heard_height, len(heard_list))):
            call = heard_list[i]
            row = 3 + i
            # Highlight the selected callsign if it matches the clicked
            # item.  Use the same highlight attribute as used for our
            # own callsign to improve visibility.
            if self.selected_heard and call.upper() == self.selected_heard.upper():
                self.stdscr.addstr(row, msgs_width, call[:19], self._highlight_attr)
            else:
                self.stdscr.addstr(row, msgs_width, call[:19])

        # Draw a vertical separator between the message area and the heard list
        # for a cleaner layout.  Use ACS_VLINE if available; otherwise fall back
        # to the '|' character.  Only draw within the bounds of the messages
        # area to avoid overwriting the prompt on the last line.
        try:
            vch = curses.ACS_VLINE
        except Exception:
            vch = ord('|')
        # Draw starting from row 2 to row height-2 (messages area height), at the
        # last column of the messages pane.  This adds a clear divider.
        self.stdscr.vline(2, msgs_width - 1, vch, msgs_height + 1)
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
                if len(payload) >= 13 and payload[10:13] == 'ack':
                    # ack for our message ID; just display
                    self.messages.append((ts, src, dest, info, path))
                    continue
            # Save message; display the path exactly as provided by the TNC
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

    def _prompt_cancelable(self, prompt: str, default: str = '') -> Optional[str]:
        """Prompt for input with the ability to cancel.

        This method behaves similarly to `_prompt` but allows the user to
        press the **Escape** key to abort input entirely.  If cancelled,
        ``None`` is returned.  Backspace editing is supported.  A default
        value is returned if the user simply presses Enter without
        typing anything.

        :param prompt: Prompt text to display at the beginning of the line.
        :param default: Default value to return if the user submits an empty string.
        :return: The string entered by the user, the default if empty,
            or ``None`` if cancelled.
        """
        # Ensure we are in blocking mode during interactive input; the caller
        # should have already set nodelay(False).
        curses.echo()
        # Clear bottom line and write prompt
        bottom_y = curses.LINES - 1
        self.stdscr.addstr(bottom_y, 0, ' ' * (curses.COLS - 1))
        self.stdscr.addstr(bottom_y, 0, prompt)
        self.stdscr.refresh()
        # Build the input string character by character
        buffer: List[str] = []
        x_pos = len(prompt)
        while True:
            try:
                ch = self.stdscr.getch()
            except Exception:
                continue
            # Enter key (carriage return or newline) finalises input
            if ch in (10, 13):
                break
            # Escape key cancels input
            if ch == 27:  # ESC
                curses.noecho()
                return None
            # Backspace handling (support DEL and Backspace)
            if ch in (curses.KEY_BACKSPACE, 127, 8):
                if buffer:
                    buffer.pop()
                    x_pos -= 1
                    # Overwrite the last character with space and move cursor back
                    self.stdscr.addstr(bottom_y, len(prompt) + x_pos, ' ')
                    self.stdscr.move(bottom_y, len(prompt) + x_pos)
                    self.stdscr.refresh()
                continue
            # Ignore other control characters
            if ch < 32:
                continue
            # Add printable character
            buffer.append(chr(ch))
            self.stdscr.addch(bottom_y, len(prompt) + x_pos, ch)
            x_pos += 1
            self.stdscr.refresh()
        curses.noecho()
        # If no input provided and a default exists, return default
        if not buffer:
            return default if default else ''
        return ''.join(buffer)

    # Compose and send an APRS message
    def _compose_message(self) -> None:
        # Temporarily disable non‑blocking input while composing a message
        self.stdscr.nodelay(False)
        self.stdscr.timeout(-1)
        try:
            # Get destination callsign; allow cancellation with ESC.  If a
            # callsign has been selected via mouse, use it as the default
            # value so that pressing Enter accepts it.  Otherwise the
            # default is empty and the user must type a destination.
            default_dest = self.selected_heard or ''
            dest = self._prompt_cancelable("To station: ", default_dest)
            # None indicates cancellation.  If the user presses Enter
            # without entering anything and no default is set, dest will be
            # an empty string; treat this as a cancellation as well.
            if dest is None or dest == '':
                return
            # Convert destination to upper case for consistency
            dest = dest.strip().upper()
            # Get message body; allow cancellation with ESC
            text = self._prompt_cancelable("Message: ")
            if text is None:
                return
            # Determine whether to include an acknowledgement ID.  When
            # acknowledgements are disabled (for example, during satellite
            # operations), omit the message ID entirely by passing None to
            # build_aprs_message().  Otherwise obtain the next sequential ID.
            if self.ack_enabled:
                msg_id = self.cfg.next_msg_id()
            else:
                msg_id = None
            payload = build_aprs_message(dest, text, msg_id=msg_id)
            ax25 = encode_ax25_frame(
                self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
            )
            self.tnc.send_frame(ax25)
            # Log our own outgoing message to the UI
            ts = time.time()
            # Mark our path so that the last digipeater is displayed with '*'
            # Display the configured path as is without marking the last hop.
            path_disp = list(self.cfg.path)
            self.messages.append((ts, self.cfg.callsign, dest, payload, path_disp))
            # Store last message for possible retransmission.  msg_id may be None
            # when acknowledgements are disabled.
            self.last_message = (dest, text, msg_id)
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
        # Mark path for display
        # Display the configured path as is without marking the last hop
        path_disp = list(self.cfg.path)
        self.messages.append((ts, self.cfg.callsign, '', payload, path_disp))

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
                # Always store callsign in uppercase
                self.cfg.callsign = new_call.strip().upper()
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

    def clear_messages(self) -> None:
        """Clear all received and logged packets from the UI.

        This method empties the messages list, effectively removing all
        displayed packets from the main view.  It does not clear the
        underlying TNC message queue; new incoming packets will continue
        to appear as they are received."""
        self.messages.clear()

    def clear_heard(self) -> None:
        """Clear the list of heard stations.

        Removes all callsigns from the heard set.  This does not
        influence ongoing reception; stations will be added again when
        new packets arrive."""
        self.heard.clear()

    def _mark_path_repeated(self, path: List[str]) -> List[str]:
        """Return a copy of the path list with the last element marked as repeated.

        In APRS notation a digipeater that has already repeated a packet is
        indicated by a trailing asterisk (`*`) appended to its callsign.  Since
        the low‑level AX.25 decoder used here does not expose the H‑bit, this
        function appends a '*' to the last digipeater in the list as a simple
        approximation.  If the path is empty, an empty list is returned.

        :param path: Sequence of digipeaters extracted from the AX.25 header.
        :return: A new list where the last element, if any, is suffixed with '*'.
        """
        if not path:
            return []
        marked = path.copy()
        marked[-1] = f"{marked[-1]}*"
        return marked

    def toggle_ack(self) -> None:
        """Toggle the inclusion of message acknowledgements on outgoing messages.

        When acknowledgements are enabled, outgoing APRS messages include a
        sequential message ID with a leading '{', allowing the recipient to
        acknowledge receipt.  Disabling acknowledgements omits this ID,
        which can be desirable for satellite communications where ACKs
        are unsupported.  This method flips the state between ON and OFF.
        """
        self.ack_enabled = not self.ack_enabled

    def repeat_last_message(self) -> None:
        """Retransmit the most recently sent message.

        If the user suspects that the previous message was not relayed by
        a digipeater or satellite, this function resends it using the same
        destination, text and, if acknowledgements are enabled, the same
        message ID.  If no message has been sent yet, this method does
        nothing.  The retransmission is logged to the UI with the current
        timestamp.
        """
        if not self.last_message:
            return
        dest, text, msg_id = self.last_message
        # Build payload based on the current acknowledgement setting.  If
        # acknowledgements are disabled, omit the message ID by passing None.
        use_id = msg_id if self.ack_enabled else None
        payload = build_aprs_message(dest, text, msg_id=use_id)
        ax25 = encode_ax25_frame(
            self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
        )
        self.tnc.send_frame(ax25)
        ts = time.time()
        # Log retransmitted message in the UI
        # Use the configured path as is for display
        path_disp = list(self.cfg.path)
        self.messages.append((ts, self.cfg.callsign, dest, payload, path_disp))

    def compose_raw_data(self) -> None:
        """Prompt the user to enter a raw APRS payload and transmit it.

        Raw packets consist solely of user‑supplied text with no padded
        addressee or message ID.  They are sent using the configured
        TOCALL as the AX.25 destination and the currently configured
        digipeater path.  The raw payload is logged to the UI with an
        empty destination field so it displays as an unaddressed packet.
        """
        # Temporarily disable non‑blocking input while composing raw data
        self.stdscr.nodelay(False)
        self.stdscr.timeout(-1)
        try:
            text = self._prompt_cancelable("Raw data: ")
            # Cancelled or empty: return without sending
            if text is None or text == '':
                return
            # Encode the raw text as Latin‑1 to preserve bytes; APRS payloads
            # are typically ASCII but this allows extended characters.  Do not
            # append any message ID.
            try:
                payload = text.encode('latin1')
            except Exception:
                payload = text.encode('ascii', errors='replace')
            ax25 = encode_ax25_frame(
                self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
            )
            self.tnc.send_frame(ax25)
            ts = time.time()
            # Log the transmission and display the TOCALL as the destination.  Even
            # though the payload is unaddressed, including TOCALL in the UI
            # clarifies which software identifier was used.
            # Display the configured path as is
            path_disp = list(self.cfg.path)
            self.messages.append((ts, self.cfg.callsign, self.cfg.tocall, payload, path_disp))
            # Remember this raw payload for potential retransmission
            self.last_raw = text
        finally:
            # Restore non‑blocking mode
            self.stdscr.nodelay(True)
            self.stdscr.timeout(100)

    def repeat_last_raw(self) -> None:
        """Retransmit the most recently sent raw data packet.

        If a raw payload has been sent previously, this method re‑encodes
        it and sends it again using the current TOCALL and digipeater
        path.  The repeat is logged to the UI.  If no raw packet has
        been sent yet, this method does nothing.
        """
        if not self.last_raw:
            return
        text = self.last_raw
        try:
            payload = text.encode('latin1')
        except Exception:
            payload = text.encode('ascii', errors='replace')
        ax25 = encode_ax25_frame(
            self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
        )
        self.tnc.send_frame(ax25)
        ts = time.time()
        # Display the TOCALL as the destination in the UI for raw repeats
        # Display the configured path as is
        path_disp = list(self.cfg.path)
        self.messages.append((ts, self.cfg.callsign, self.cfg.tocall, payload, path_disp))

    def _send_quick_message(self, quick_text: str) -> None:
        """Send a predefined APRS message quickly.

        Quick messages are common phrases like "QSL? 73" or "QSL! 73".
        If the user has clicked on a callsign in the heard list, that
        callsign is used as the default destination.  Otherwise the
        user is prompted for a destination.  The message is sent with
        the current acknowledgement setting.

        :param quick_text: The message body to send.
        """
        # Temporarily disable non‑blocking input during prompting
        self.stdscr.nodelay(False)
        self.stdscr.timeout(-1)
        try:
            # If a callsign has been selected via the mouse, send the
            # quick message directly without prompting.  Otherwise prompt
            # for a destination.
            if self.selected_heard:
                dest = self.selected_heard.strip().upper()
            else:
                dest = self._prompt_cancelable("To station: ")
                if dest is None or dest == '':
                    return
                dest = dest.strip().upper()
            # Determine message ID if acknowledgements are enabled
            msg_id = self.cfg.next_msg_id() if self.ack_enabled else None
            payload = build_aprs_message(dest, quick_text, msg_id=msg_id)
            ax25 = encode_ax25_frame(
                self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
            )
            self.tnc.send_frame(ax25)
            ts = time.time()
            path_disp = list(self.cfg.path)
            self.messages.append((ts, self.cfg.callsign, dest, payload, path_disp))
            # Update last_message record for potential repeat
            self.last_message = (dest, quick_text, msg_id)
        finally:
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
        cfg.callsign = callsign.upper()
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