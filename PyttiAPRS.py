#!/usr/bin/env python3
# PyttiAPRS V0.4 - 03/07/2026 by Lorenzo "Vash" IU1BOT
#    ____        __  __  _ ___    ____  ____  _____
#   / __ \__  __/ /_/ /_(_)   |  / __ \/ __ \/ ___/
#  / /_/ / / / / __/ __/ / /| | / /_/ / /_/ /\__ \ 
# / ____/ /_/ / /_/ /_/ / ___ |/ ____/ _, _/___/ / 
#/_/    \__, /\__/\__/_/_/  |_/_/   /_/ |_|/____/  
#      /____/  
                                                                                                                                                                                                           
import curses
import os
import socket
import threading
import time
import queue
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union
import json
import re
import math


# Default APRS application identity.  APZ identifiers are reserved for
# development.  Operators may change the TOCALL in the configuration, for
# example when testing an allocated identifier or a compatible destination.
APP_TOCALL = 'APZ001'

# Protocol defaults and limits.  No digipeater path is assumed: satellite
# aliases and terrestrial WIDEn-N paths evolve and remain user-configurable.
DEFAULT_PATH: List[str] = []
MAX_DIGIPEATERS = 8
MAX_APRS_INFO_BYTES = 256
MAX_MESSAGE_TEXT_CHARS = 67
MAX_POSITION_COMMENT_CHARS = 43
MESSAGE_RETRY_INTERVAL = 60.0
MAX_MESSAGE_ATTEMPTS = 2

_AX25_ADDRESS_RE = re.compile(r'^[A-Z0-9]{1,6}(?:-(?:[1-9]|1[0-5]))?$')
_MESSAGE_ID_RE = re.compile(
    r'^(?=.{1,5}$)[A-Za-z0-9]+(?:}[A-Za-z0-9]*)?$'
)


def _encode_utf8_limited(text: str, max_bytes: int) -> bytes:
    """Encode UTF-8 without splitting a multi-byte character at the limit."""
    encoded = text.encode('utf-8')
    if len(encoded) <= max_bytes:
        return encoded
    encoded = encoded[:max_bytes]
    while encoded:
        try:
            encoded.decode('utf-8')
            return encoded
        except UnicodeDecodeError:
            encoded = encoded[:-1]
    return b''


def decode_aprs_text(data: bytes) -> str:
    """Decode modern APRS free text, retaining legacy bytes as a fallback."""
    try:
        return data.decode('utf-8')
    except UnicodeDecodeError:
        return data.decode('latin1')


def normalize_ax25_address(value: str, field_name: str = 'AX.25 address') -> str:
    """Return a validated upper-case AX.25 callsign/alias with optional SSID."""
    if not isinstance(value, str):
        raise TypeError(f'{field_name} must be text')
    normalized = value.strip().upper()
    if not _AX25_ADDRESS_RE.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must be 1-6 upper-case letters/digits with optional SSID 1-15"
        )
    return normalized


def normalize_path(path: List[str]) -> List[str]:
    """Validate an outgoing AX.25 digipeater path."""
    if not isinstance(path, list):
        raise TypeError('Digipeater path must be a list')
    if len(path) > MAX_DIGIPEATERS:
        raise ValueError(f'AX.25 permits at most {MAX_DIGIPEATERS} digipeaters')
    return [normalize_ax25_address(item, 'Digipeater') for item in path]

###############################################################################
#                           Mic‑E decoding routine                             #
###############################################################################

def decode_mic_e(dest: str, info: bytes) -> Optional[str]:
    """Decode a Mic-E report to an equivalent readable position string.

    The conversion is for display only; the original packet remains the
    authoritative representation.  Position ambiguity is retained rather
    than replaced with zeroes.
    """
    if not info or info[0] not in (0x27, 0x60) or len(info) < 9:
        return None

    destcall = dest.split('-', 1)[0].upper()
    if len(destcall) != 6:
        return None

    lat_digits: List[str] = []
    ns_indicator = 'S'
    lon_offset = 0
    we_indicator = 'E'
    for idx, ch in enumerate(destcall):
        if '0' <= ch <= '9':
            digit, high = ch, False
        elif 'A' <= ch <= 'J':
            digit, high = chr(ord(ch) - 17), True
        elif ch == 'K':
            digit, high = ' ', True
        elif ch == 'L':
            digit, high = ' ', False
        elif 'P' <= ch <= 'Y':
            digit, high = chr(ord(ch) - 32), True
        elif ch == 'Z':
            digit, high = ' ', True
        else:
            return None

        # A-K encode Mic-E message bits and are not valid in bytes 4-6.
        if idx >= 3 and ('A' <= ch <= 'K'):
            return None
        lat_digits.append(digit)
        if idx == 3:
            ns_indicator = 'N' if high else 'S'
        elif idx == 4:
            lon_offset = 100 if high else 0
        elif idx == 5:
            we_indicator = 'W' if high else 'E'

    ambiguity = 0
    for digit in reversed(lat_digits):
        if digit == ' ':
            ambiguity += 1
        else:
            break
    if any(digit == ' ' for digit in lat_digits[:6 - ambiguity]):
        return None
    if ambiguity > 4:
        return None

    dplus, mplus, hplus, spplus, dcplus, seplus = info[1:7]
    if not (38 <= dplus <= 127):
        return None
    if any(value < 28 or value > 127 for value in (mplus, hplus, spplus, dcplus, seplus)):
        return None

    lon_deg = dplus - 28 + lon_offset
    if 180 <= lon_deg <= 189:
        lon_deg -= 80
    elif 190 <= lon_deg <= 199:
        lon_deg -= 190
    if not 0 <= lon_deg <= 179:
        return None

    lon_min = mplus - 28
    if lon_min >= 60:
        lon_min -= 60
    lon_hun = hplus - 28
    if lon_hun >= 100:
        lon_hun -= 100
    if not (0 <= lon_min <= 59 and 0 <= lon_hun <= 99):
        return None

    speed_knots = (spplus - 28) * 10 + (dcplus - 28) // 10
    course_deg = ((dcplus - 28) % 10) * 100 + (seplus - 28)
    if speed_knots >= 800:
        speed_knots -= 800
    if course_deg >= 400:
        course_deg -= 400
    if not (0 <= speed_knots <= 999 and 0 <= course_deg <= 360):
        return None

    symbol_code = chr(info[7])
    symbol_table = chr(info[8])
    if not (33 <= info[7] <= 126 and 33 <= info[8] <= 126):
        return None

    lat_field = (
        ''.join(lat_digits[:2]) + ''.join(lat_digits[2:4]) + '.'
        + ''.join(lat_digits[4:6]) + ns_indicator
    )
    lon_minute_digits = list(f'{lon_min:02d}{lon_hun:02d}')
    for index in range(4 - ambiguity, 4):
        if index >= 0:
            lon_minute_digits[index] = ' '
    lon_field = (
        f'{lon_deg:03d}' + ''.join(lon_minute_digits[:2]) + '.'
        + ''.join(lon_minute_digits[2:]) + we_indicator
    )

    comment = decode_aprs_text(info[9:]) if len(info) > 9 else ''
    messaging_capable = bool(comment[:1] in ('`', '>', ']'))
    dti = '=' if messaging_capable else '!'
    extension = f'{course_deg:03d}/{speed_knots:03d}'
    return f'{dti}{lat_field}{symbol_table}{lon_field}{symbol_code}{extension}{comment}'

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

    Only a subset of fields are persisted (callsign, TOCALL, path,
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
        'quick_msg1': cfg.quick_msg1,
        'quick_msg2': cfg.quick_msg2,
        'log_file': cfg.log_file,
        # Persist the acknowledgement flag so that the user's preference is
        # retained across sessions.  One-shot mode is the default and is
        # useful on short or otherwise constrained links.
        'ack_enabled': cfg.ack_enabled,
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

def encode_ax25_address(
    call: str,
    ssid: int = 0,
    last: bool = False,
    command_or_repeated: bool = False,
) -> bytes:
    """Encode a callsign and SSID into a 7‑byte AX.25 address field.

    The callsign is padded to six characters, converted to uppercase and
    each character is shifted left by one bit.  The SSID field is
    constructed by shifting the SSID into bits 1–4 of the final byte and
    setting bits 5 and 6 to 1 as required by the AX.25 standard.  Bit 0
    of the final byte is set to 1 for the last address in the header and
    left at 0 otherwise.

    :param call: Callsign (without SSID suffix).  It is padded to six
        characters after validation.
    :param ssid: SSID number (0–15).
    :param last: Whether this address is the last in the address list.
    :param command_or_repeated: Set the C bit for destination/source fields,
        or the H bit for a digipeater address.
    :return: Seven bytes representing the AX.25 address.
    """
    call = call.strip().upper()
    if not re.fullmatch(r'[A-Z0-9]{1,6}', call):
        raise ValueError('AX.25 callsign must contain 1-6 upper-case letters/digits')
    if not 0 <= ssid <= 15:
        raise ValueError('AX.25 SSID must be between 0 and 15')
    call = call.ljust(6)
    encoded = bytearray()
    for ch in call:
        encoded.append((ord(ch) << 1) & 0xFE)
    # Construct SSID/control byte
    ssid_byte = (ssid << 1) | 0x60
    if command_or_repeated:
        ssid_byte |= 0x80
    if last:
        ssid_byte |= 0x01  # set bit0 if this is the last address
    encoded.append(ssid_byte)
    return bytes(encoded)


def decode_ax25_address(addr: bytes) -> Tuple[str, int, bool]:
    """Decode a 7‑byte AX.25 address into callsign, SSID and last flag.

    The inverse of :func:`encode_ax25_address`.  Callsign characters are
    obtained by shifting each byte right by one bit.  The SSID is read
    from bits 1–4 of the final byte and the last flag from bit 0.

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
    digipeaters to include between source and destination (for example
    ``["RS0ISS"]`` or ``["WIDE1-1", "WIDE2-2"]``).  No alias receives
    special treatment.  This function encodes the addresses sequentially
    and appends the standard UI control (0x03) and PID (0xF0) fields before
    the information payload.

    :param dest: Destination callsign with optional SSID (e.g. ``APZ001``).
    :param source: Source callsign with optional SSID (e.g. ``IK2ABC-7``).
    :param path: Sequence of digipeater callsigns with optional SSIDs.
    :param info: Information field (payload) as bytes.
    :return: Raw AX.25 frame (without flags or FCS) ready for KISS encoding.
    """
    if not isinstance(info, bytes):
        raise TypeError('AX.25 information field must be bytes')
    if not 1 <= len(info) <= MAX_APRS_INFO_BYTES:
        raise ValueError(
            f'APRS information field must be 1-{MAX_APRS_INFO_BYTES} bytes'
        )
    dest = normalize_ax25_address(dest, 'Destination')
    source = normalize_ax25_address(source, 'Source')
    path = normalize_path(path)

    # Helper to split callsign and SSID
    def split_call(c: str) -> Tuple[str, int]:
        if '-' in c:
            cs, ss = c.split('-', 1)
            return cs, int(ss)
        return c, 0

    # Encode addresses
    addresses = []
    # Destination (not last unless no other addresses)
    dest_call, dest_ssid = split_call(dest)
    addresses.append(encode_ax25_address(
        dest_call, dest_ssid, last=False, command_or_repeated=True
    ))
    # Source (last if there is no path)
    src_call, src_ssid = split_call(source)
    last_flag = len(path) == 0
    addresses.append(encode_ax25_address(
        src_call, src_ssid, last=last_flag, command_or_repeated=False
    ))
    # Path (all but last flagged false, last flagged true)
    if path:
        for i, dig in enumerate(path):
            dig_call, dig_ssid = split_call(dig)
            is_last = i == (len(path) - 1)
            addresses.append(encode_ax25_address(
                dig_call, dig_ssid, last=is_last, command_or_repeated=False
            ))

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
    while not last_found and idx + 7 <= len(frame) and len(addresses) < 10:
        addr_bytes = frame[idx:idx + 7]
        if any(byte & 0x01 for byte in addr_bytes[:6]):
            return None
        # Decode callsign by shifting right by one bit and stripping
        call = ''.join(chr((b >> 1) & 0x7F) for b in addr_bytes[:6]).strip()
        if not re.fullmatch(r'[A-Z0-9]{1,6}', call):
            return None
        ssid = (addr_bytes[6] >> 1) & 0x0F
        h_bit = bool(addr_bytes[6] & 0x80)
        e_bit = bool(addr_bytes[6] & 0x01)
        addresses.append((call, ssid, h_bit, e_bit))
        last_found = e_bit
        idx += 7
    # Need destination, source, an E bit, and no more than 8 digipeaters.
    if len(addresses) < 2 or not last_found:
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
    if not 1 <= len(info) <= MAX_APRS_INFO_BYTES:
        return None
    return dest, source, path, info


def kiss_encode(ax25_frame: bytes) -> bytes:
    """Encode a raw AX.25 frame into a KISS frame.

    A KISS data frame is constructed by wrapping the payload with FEND
    (0xC0) bytes and prefixing it with a data frame type (0x00).  Any
    occurrence of FEND (0xC0) or FESC (0xDB) in the payload is
    escaped according to the KISS protocol.

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
    any trailing bytes that constitute an incomplete frame.  Data frames
    from every KISS port are returned; non-data commands are ignored.

    :param stream: Byte stream containing zero or more KISS frames.
    :return: (list of AX.25 frames, remainder)
    """
    FEND = 0xC0
    FESC = 0xDB
    TFEND = 0xDC
    TFESC = 0xDD
    frames: List[bytes] = []
    start = stream.find(bytes([FEND]))
    if start < 0:
        return frames, b''

    while True:
        end = stream.find(bytes([FEND]), start + 1)
        if end < 0:
            # Keep the opening delimiter so a frame split across TCP reads can
            # be parsed when the next chunk arrives.
            return frames, stream[start:]

        encoded = stream[start + 1:end]
        start = end
        if not encoded:
            continue

        decoded = bytearray()
        valid = True
        i = 0
        while i < len(encoded):
            byte = encoded[i]
            if byte != FESC:
                decoded.append(byte)
                i += 1
                continue
            if i + 1 >= len(encoded):
                valid = False
                break
            escaped = encoded[i + 1]
            if escaped == TFEND:
                decoded.append(FEND)
            elif escaped == TFESC:
                decoded.append(FESC)
            else:
                valid = False
                break
            i += 2

        if valid and decoded:
            command = decoded[0]
            # The low nibble is the KISS command; accept data frames from any
            # KISS port rather than only port zero.
            if command & 0x0F == 0:
                frames.append(bytes(decoded[1:]))


###############################################################################
#                            APRS payload routines                            #
###############################################################################

@dataclass(frozen=True)
class ParsedAPRSMessage:
    addressee: str
    text: str
    msg_id: Optional[str]
    response: Optional[str] = None


def _format_message_id(msg_id: Union[int, str]) -> str:
    if isinstance(msg_id, int):
        formatted = f'{msg_id % 1000:03d}'
    else:
        formatted = str(msg_id)
    if not _MESSAGE_ID_RE.fullmatch(formatted):
        raise ValueError(
            'APRS message ID must be 1-5 characters: alphanumerics with an '
            'optional reply-ack separator'
        )
    return formatted


def build_aprs_message(
    addressee: str,
    text: str,
    msg_id: Optional[Union[int, str]] = None,
) -> bytes:
    """Construct an APRS message payload.

    The addressee is padded to exactly nine characters.  Message text may
    not exceed 67 characters; longer input is truncated.  When
    ``msg_id`` is provided it is appended with a leading ``{`` so that
    the receiving station can acknowledge the message.

    :param addressee: Destination callsign of the message.
    :param text: Message body (will be truncated to 67 characters).
    :param msg_id: Optional message identifier number.
    :return: Bytes of the information field ready to be inserted into
        the AX.25 frame.
    """
    if not isinstance(addressee, str) or not isinstance(text, str):
        raise TypeError('APRS message addressee and text must be strings')
    addressee = addressee.strip().upper()
    if not re.fullmatch(r'[A-Z0-9-]{1,9}', addressee):
        raise ValueError('APRS message addressee must be 1-9 letters, digits, or hyphens')
    if '{' in text:
        raise ValueError("APRS message text cannot contain '{'")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError('APRS message text cannot contain control characters')

    header = f':{addressee.ljust(9)}:'.encode('ascii')
    suffix = b''
    if msg_id is not None:
        suffix = b'{' + _format_message_id(msg_id).encode('ascii')
    # APRS limits message text to 67 characters.  UTF-8 can use multiple
    # octets per character, so also respect the 256-octet AX.25 information
    # field without splitting a code point.
    text = text[:MAX_MESSAGE_TEXT_CHARS]
    available = MAX_APRS_INFO_BYTES - len(header) - len(suffix)
    text_bytes = _encode_utf8_limited(text, available)
    return header + text_bytes + suffix


def build_aprs_ack(addressee: str, msg_id: str, rejected: bool = False) -> bytes:
    """Build an APRS acknowledgement or rejection message."""
    response = ('rej' if rejected else 'ack') + _format_message_id(msg_id)
    return build_aprs_message(addressee, response)


def parse_aprs_message(info: bytes) -> Optional[ParsedAPRSMessage]:
    """Parse APRS messages, including ack/rej and reply-ack identifiers."""
    if len(info) < 11 or info[:1] != b':' or info[10:11] != b':':
        return None
    try:
        addressee = info[1:10].decode('ascii').rstrip()
    except UnicodeDecodeError:
        return None
    body = decode_aprs_text(info[11:])

    for response in ('ack', 'rej'):
        if body.startswith(response):
            candidate = body[len(response):]
            if _MESSAGE_ID_RE.fullmatch(candidate):
                return ParsedAPRSMessage(
                    addressee=addressee,
                    text='',
                    msg_id=candidate,
                    response=response,
                )

    msg_id: Optional[str] = None
    text = body
    if '{' in body:
        text, candidate = body.split('{', 1)
        if not _MESSAGE_ID_RE.fullmatch(candidate):
            return None
        msg_id = candidate
    return ParsedAPRSMessage(addressee, text, msg_id)


def build_aprs_position(
    latitude: float,
    longitude: float,
    symbol_table: str = '/',
    symbol_code: str = '>',
    comment: str = '',
    messaging_capable: bool = True,
) -> bytes:
    """Construct an uncompressed APRS position payload.

    The uncompressed position format uses ``=`` for a messaging-capable
    station by default, followed by latitude and longitude in degrees/minutes
    and two symbol characters.  An optional free-form comment may follow the
    symbol code.  Latitude is formatted as DDMM.mmN/S and longitude as
    DDDMM.mmE/W.

    :param latitude: Latitude in decimal degrees (positive north,
        negative south).
    :param longitude: Longitude in decimal degrees (positive east,
        negative west).
    :param symbol_table: Primary/alternate table identifier or overlay.
    :param symbol_code: Symbol code (e.g. ``'>'`` for a car, ``'^'`` for
        a house).
    :param comment: Optional comment text to append after the symbol.
    :param messaging_capable: Use ``=`` when true, otherwise ``!``.
    :return: Bytes of the information field ready to be inserted into
        the AX.25 frame.
    """
    if not isinstance(comment, str):
        raise TypeError('Position comment must be text')
    if not (math.isfinite(latitude) and math.isfinite(longitude)):
        raise ValueError('Position coordinates must be finite')
    if not -90 <= latitude <= 90:
        raise ValueError('Latitude must be between -90 and 90 degrees')
    if not -180 <= longitude <= 180:
        raise ValueError('Longitude must be between -180 and 180 degrees')
    if len(symbol_table) != 1 or symbol_table not in '/\\0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ':
        raise ValueError('Invalid APRS symbol table/overlay')
    if len(symbol_code) != 1 or not 33 <= ord(symbol_code) <= 126:
        raise ValueError('APRS symbol code must be one printable ASCII character')
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in comment):
        raise ValueError('Position comment cannot contain control characters')

    def coordinate_parts(value: float, max_degrees: int) -> Tuple[int, int, int]:
        total_hundredths = int(math.floor(abs(value) * 6000 + 0.5))
        degrees, minute_hundredths = divmod(total_hundredths, 6000)
        minutes, hundredths = divmod(minute_hundredths, 100)
        if degrees > max_degrees or (degrees == max_degrees and minutes):
            raise ValueError('Rounded coordinate is outside the valid APRS range')
        return degrees, minutes, hundredths

    lat_deg, lat_min, lat_hun = coordinate_parts(latitude, 90)
    lon_deg, lon_min, lon_hun = coordinate_parts(longitude, 180)
    lat_dir = 'S' if math.copysign(1.0, latitude) < 0 else 'N'
    lon_dir = 'W' if math.copysign(1.0, longitude) < 0 else 'E'
    lat_str = f'{lat_deg:02d}{lat_min:02d}.{lat_hun:02d}{lat_dir}'
    lon_str = f'{lon_deg:03d}{lon_min:02d}.{lon_hun:02d}{lon_dir}'
    dti = '=' if messaging_capable else '!'
    base = f'{dti}{lat_str}{symbol_table}{lon_str}{symbol_code}'.encode('ascii')
    return base + comment[:MAX_POSITION_COMMENT_CHARS].encode('utf-8')


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
    tocall: str = APP_TOCALL
    path: List[str] = field(default_factory=list)
    latitude: float = 0.0
    longitude: float = 0.0
    symbol_table: str = '/'
    symbol_code: str = '>'
    host: str = 'localhost'
    port: int = 8001
    msg_id_counter: int = 1
    pos_comment: str = ''  # default comment for position beacons
    quick_msg1: str = 'QSL? 73'
    quick_msg2: str = 'QSL! 73'
    log_file: str = 'aprs_tui.log'
    # Whether acknowledgements are appended to outgoing messages by default.
    # When set to False, the application will omit the message ID when
    # composing messages.  The value may be toggled at runtime via the
    # 'a' command and is persisted in the configuration file.
    ack_enabled: bool = False

    def next_msg_id(self) -> int:
        mid = self.msg_id_counter
        self.msg_id_counter += 1
        # Wrap around after 999 to keep ID within three digits
        if self.msg_id_counter > 999:
            self.msg_id_counter = 1
        return mid


@dataclass
class PendingMessage:
    destination: str
    text: str
    msg_id: str
    payload: bytes
    last_sent: float
    attempts: int = 1


class APRSTUI:
    """Curses based APRS client."""

    def __init__(self, stdscr: curses.window, cfg: StationConfig, tnc: TNCConnection):
        self.stdscr = stdscr
        self.cfg = cfg
        self.tnc = tnc
        # Logged packets: list of (timestamp, source, dest, info_bytes, path, is_tx)
        # The path is a list of digipeaters through which the packet travelled.
        # is_tx marks packets transmitted by this station so the UI can colour
        # them differently from received ones.
        self.messages: List[Tuple[float, str, str, bytes, List[str], bool]] = []
        self.heard: set = set()
        self.heard_times: dict = {}
        self.msg_queue: queue.Queue = tnc.msg_queue
        # Setup curses
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.timeout(100)
        # Enable colour if supported.  Each pair is assigned a specific role
        # so that the layout stays visually organised: colour 1 highlights
        # our own callsign wherever it appears, and the others tint fixed
        # regions of the screen (status bar, command bar, section titles,
        # packet headers/bodies and the heard list) to help the eye jump
        # straight to the right area.
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_YELLOW, -1)
            curses.init_pair(2, curses.COLOR_CYAN, -1)
            curses.init_pair(3, curses.COLOR_WHITE, curses.COLOR_BLUE)
            curses.init_pair(4, curses.COLOR_GREEN, -1)
            curses.init_pair(5, curses.COLOR_WHITE, -1)
            curses.init_pair(6, curses.COLOR_CYAN, -1)
            curses.init_pair(7, curses.COLOR_BLUE, -1)
            curses.init_pair(8, curses.COLOR_RED, -1)
            curses.init_pair(9, curses.COLOR_GREEN, -1)
            self._highlight_attr = curses.color_pair(1) | curses.A_BOLD
            self._status_attr = curses.color_pair(2) | curses.A_BOLD
            self._status_value_attr = curses.color_pair(5)
            self._cmdbar_attr = curses.color_pair(3) | curses.A_BOLD
            self._title_attr = curses.color_pair(4) | curses.A_BOLD
            self._heard_attr = curses.color_pair(6)
            self._tx_attr = curses.color_pair(8)
            self._rx_attr = curses.color_pair(9)
        except Exception:
            # Fallback attributes if colours are unavailable
            self._highlight_attr = curses.A_REVERSE
            self._status_attr = curses.A_BOLD
            self._status_value_attr = curses.A_NORMAL
            self._cmdbar_attr = curses.A_REVERSE
            self._title_attr = curses.A_BOLD
            self._heard_attr = curses.A_NORMAL
            self._tx_attr = curses.A_BOLD
            self._rx_attr = curses.A_NORMAL

        # One-shot messages omit IDs by default.  When enabled, IDs request an
        # end-to-end acknowledgement from the addressed station; digipeaters,
        # whether terrestrial or in space, only relay the UI frame.
        self.ack_enabled: bool = getattr(cfg, 'ack_enabled', False)
        # Remember the most recently sent message so that it can be
        # retransmitted (for example if a digipeater did not repeat it).
        # Stored as a tuple (destination, text, msg_id).  msg_id may be None
        # if acknowledgements are disabled when the message was sent.
        self.last_message: Optional[Tuple[str, str, Optional[str]]] = None
        self.pending_messages: Dict[str, PendingMessage] = {}
        self.sent_ack_times: Dict[Tuple[str, str], float] = {}
        self.last_delivery_status: str = 'ONE-SHOT'
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
            self._retry_pending_messages()
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
                self._send_quick_message(self.cfg.quick_msg1)
            elif c == ord('2'):
                self._send_quick_message(self.cfg.quick_msg2)

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

    def _log_message(self, ts: float, src: str, dest: str, info: bytes, path: list) -> None:
        """Append a single-line log entry to cfg.log_file, if set."""
        if not getattr(self.cfg, 'log_file', ''):
            return
        try:
            timestr = time.strftime('%H:%M:%S', time.localtime(ts))
            try:
                text = decode_aprs_text(bytes(info)) if isinstance(info, (bytes, bytearray)) else str(info)
            except Exception:
                text = str(info)
            # Sanitize the decoded text to avoid embedded nulls or other
            # control characters being written to the log.  Replace any
            # null bytes with a space and drop other control codes below
            # 0x20 (except for whitespace).  See similar sanitisation in
            # the _draw method for rationale.
            if isinstance(text, str):
                sanitized_chars = []
                for ch in text:
                    if ch == '\x00':
                        sanitized_chars.append(' ')
                    elif ord(ch) < 32 and ch not in ('\t', '\n', '\r'):
                        continue
                    else:
                        sanitized_chars.append(ch)
                text = ''.join(sanitized_chars)
            # Build a compact header: SRC> DEST PATH: text
            parts = []
            if dest:
                parts.append(dest)
            if path:
                parts.extend(path)
            header = f"{src}> {' '.join(parts)}" if parts else f"{src}>"
            line = f"{timestr} {header}: {text}\n"
            with open(self.cfg.log_file, 'a', encoding='utf-8') as lf:
                lf.write(line)
        except Exception:
            # Logging failures should never crash the UI
            pass

    @staticmethod
    def _find_exact_callsign(text_upper: str, cs: str) -> int:
        """Find `cs` in `text_upper` as a whole token, not a substring.

        A plain substring search matches e.g. "IU1BOT-1" inside
        "IU1BOT-13", wrongly highlighting other stations' calls that
        merely share a prefix. Require non-alphanumeric (or string
        boundary) characters immediately before and after the match.
        """
        start = 0
        while True:
            idx = text_upper.find(cs, start)
            if idx < 0:
                return -1
            end = idx + len(cs)
            before_ok = idx == 0 or not text_upper[idx - 1].isalnum()
            after_ok = end == len(text_upper) or not text_upper[end].isalnum()
            if before_ok and after_ok:
                return idx
            start = idx + 1

    # UI helper to draw the interface
    def _draw(self) -> None:
        self.stdscr.erase()
        height, width = self.stdscr.getmaxyx()
        # Header line with station info.  Labels are drawn in cyan followed
        # by a colon, values in plain white, so units and values remain
        # visually distinct.
        status_fields = [
            ("CALL", self.cfg.callsign),
            ("TOCALL", self.cfg.tocall),
            ("PATH", ','.join(self.cfg.path) if self.cfg.path else 'NONE'),
            ("LAT", f"{self.cfg.latitude:.4f}"),
            ("LON", f"{self.cfg.longitude:.4f}"),
            ("SYM", f"{self.cfg.symbol_table}{self.cfg.symbol_code}"),
            ("ACK", 'ON' if self.ack_enabled else 'OFF'),
            ("MSG", self.last_delivery_status),
        ]
        x = 0
        max_x = width - 1
        for label, value in status_fields:
            for text, attr in ((f"{label}: ", self._status_attr),
                               (f"{value}  ", self._status_value_attr)):
                if x >= max_x:
                    break
                seg = text[:max_x - x]
                self.stdscr.addstr(0, x, seg, attr)
                x += len(seg)
        # Commands line.  Include commands for clearing messages and the heard list,
        # toggling acknowledgements, and resending the last message.
        # Build the command bar dynamically so that the quick message labels
        # reflect the user‑configured phrases for keys '1' and '2'.  When
        # quick_msg1 or quick_msg2 contain long strings, the command bar
        # will be truncated to fit within the terminal width.
        cmd_line = (
            f"m:msg  p:pos  c:cfg  x:clr msgs  h:clr heard  "
            f"d:raw  t:rep raw  r:repeat  "
            f"1:{self.cfg.quick_msg1}  2:{self.cfg.quick_msg2}  "
            f"a:ack on/off  q:quit"
        )
        # Highlight the command bar to distinguish available keys.  Use
        # reverse video for visibility; if reverse video is not available
        # curses will fall back to a reasonable attribute.
        self.stdscr.addstr(1, 0, cmd_line[:width - 1], self._cmdbar_attr)
        # Determine areas
        # Reserve two lines at the bottom (one blank and one for prompts) to
        # ensure that input prompts do not overlap with the scrolling message
        # area even when the screen is full.  With a height of N, messages and
        # heard lists occupy up to rows 3..(N-3).
        msgs_height = height - 5
        msgs_width = width - 20
        # Show last messages (transmitted packets in red, received in green)
        packets_fit = max(1, msgs_height // 3)
        displayed = self.messages[-packets_fit:]
        for i, msg in enumerate(displayed):
            ts, src, dest, info, path, is_tx = msg
            pkt_header_attr = (self._tx_attr if is_tx else self._rx_attr) | curses.A_BOLD
            pkt_body_attr = self._tx_attr if is_tx else self._rx_attr
            timestr = time.strftime("%H:%M:%S", time.localtime(ts))
            # APRS free text is UTF-8; retain a Latin-1 fallback for legacy
            # or binary-bearing packet types.
            try:
                text = decode_aprs_text(info)
            except Exception:
                text = str(info)
            # Sanitize the decoded text before displaying it.  Some
            # received packets may include embedded null bytes (\x00)
            # or other control characters that cannot be printed by
            # curses.  Replace NULs with a space and drop other
            # non‑whitespace control characters below 0x20.
            if isinstance(text, str):
                sanitized_chars = []
                for ch in text:
                    if ch == '\x00':
                        sanitized_chars.append(' ')
                    elif ord(ch) < 32 and ch not in ('\t', '\n', '\r'):
                        # skip other control characters
                        continue
                    else:
                        sanitized_chars.append(ch)
                text = ''.join(sanitized_chars)
            
# Build path string if present
            path_str = ''
            if path:
                path_str = ' ' + ' '.join(path)
            # Two-line layout
            base = src.split('-')[0] if '-' in src else src
            ssid = src.split('-')[1] if '-' in src else ''
            base_padded = base.ljust(6)
            suffix = f'-{ssid}' if ssid else ''
            suffix_padded = suffix.ljust(4)
            src_display = base_padded + suffix_padded
            # Destination + digis (space separated)
            dest_cols = []
            if dest:
                dest_cols.append(dest)
            if path:
                dest_cols.extend(path)
            dest_display = ' '.join(dest_cols)
            header = f"{timestr} {src_display}> {dest_display}".rstrip()
            header_tr = header[: msgs_width - 1]
            indent = len(timestr) + 1 + len(src_display) + 2
            body = ' ' * indent + f": {text}"
            body_tr = body[: msgs_width - 1]
            # Row base for this packet (3 rows per packet: header, body, blank)
            row_pos = 3 + i * 3
            # Highlight our callsign on header
            cs = self.cfg.callsign.upper()
            idx = self._find_exact_callsign(header_tr.upper(), cs) if cs else -1
            if idx >= 0:
                if idx > 0:
                    self.stdscr.addstr(row_pos, 0, header_tr[:idx], pkt_header_attr)
                cs_end = min(idx + len(cs), len(header_tr))
                self.stdscr.addstr(row_pos, idx, header_tr[idx:cs_end], self._highlight_attr)
                if cs_end < len(header_tr):
                    self.stdscr.addstr(row_pos, cs_end, header_tr[cs_end:], pkt_header_attr)
            else:
                self.stdscr.addstr(row_pos, 0, header_tr, pkt_header_attr)
            # Body and blank separator
            # Highlight our callsign if it appears anywhere in the body.  This
            # allows quick identification of replies addressed to us.  Search
            # case‑insensitively and only highlight the first occurrence to
            # simplify rendering.
            cs = self.cfg.callsign.upper() if self.cfg.callsign else ''
            if cs:
                body_upper = body_tr.upper()
                idx_body = self._find_exact_callsign(body_upper, cs)
            else:
                idx_body = -1
            if idx_body >= 0:
                # Print portion before our callsign
                if idx_body > 0:
                    self.stdscr.addstr(row_pos + 1, 0, body_tr[:idx_body], pkt_body_attr)
                # Highlight the callsign
                cs_end = min(idx_body + len(cs), len(body_tr))
                self.stdscr.addstr(row_pos + 1, idx_body, body_tr[idx_body:cs_end], self._highlight_attr)
                # Print remainder after the callsign, if any
                if cs_end < len(body_tr):
                    self.stdscr.addstr(row_pos + 1, cs_end, body_tr[cs_end:], pkt_body_attr)
            else:
                self.stdscr.addstr(row_pos + 1, 0, body_tr, pkt_body_attr)
            # row_pos + 2 left intentionally blank
        # Draw heard stations.  Reserve the bottom line for prompts by limiting
        # the height of the list to match the messages area.  Without this
        # constraint the heard list would overwrite the prompt line when the
        # screen is full, causing the input prompt to appear mid‑screen.
        self.stdscr.addstr(2, msgs_width, "Heard:", self._title_attr)
        # Convert the heard set into a sorted list to provide a stable
        # ordering for display and mouse selection.  Store it on
        # self.current_heard_list so the mouse handler can map row
        # indices to callsigns reliably.
        heard_list = sorted(self.heard, key=lambda c: self.heard_times.get(c, 0), reverse=True)
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
                self.stdscr.addstr(row, msgs_width, call[:19], self._heard_attr)

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
            # Add/update heard list
            self.heard.add(src)
            try:
                self.heard_times[src] = float(ts)
            except Exception:
                self.heard_times[src] = time.time()
            parsed_message = parse_aprs_message(info)
            if parsed_message is not None:
                addressed_to_us = (
                    parsed_message.addressee.upper() == self.cfg.callsign.upper()
                )
                if parsed_message.response and addressed_to_us and parsed_message.msg_id:
                    response_id = parsed_message.msg_id.split('}', 1)[0]
                    pending = self._pop_pending_from(response_id, src)
                    if pending is None:
                        pending = self._pop_pending_from(parsed_message.msg_id, src)
                    if pending is not None:
                        if parsed_message.response == 'ack':
                            self.last_delivery_status = f'ACK {response_id}'
                        else:
                            self.last_delivery_status = f'REJ {response_id}'
                elif addressed_to_us and parsed_message.msg_id:
                    _, separator, reply_ack_id = parsed_message.msg_id.partition('}')
                    if separator and reply_ack_id:
                        pending = self._pop_pending_from(reply_ack_id, src)
                        if pending is not None:
                            self.last_delivery_status = f'ACK {reply_ack_id}'
                    # Multiple ACKs for the same message must be at least 30
                    # seconds apart.  This also prevents replying twice when
                    # both direct and digipeated copies are heard.
                    ack_key = (src.upper(), parsed_message.msg_id)
                    last_ack = self.sent_ack_times.get(ack_key)
                    ack_now = time.time()
                    if last_ack is None or ack_now - last_ack >= 30.0:
                        try:
                            ack_payload = build_aprs_ack(src, parsed_message.msg_id)
                            ax25 = encode_ax25_frame(
                                self.cfg.tocall,
                                self.cfg.callsign,
                                self.cfg.path,
                                ack_payload,
                            )
                            self.tnc.send_frame(ax25)
                            ack_ts = time.time()
                            path_disp = list(self.cfg.path)
                            self.messages.append((
                                ack_ts,
                                self.cfg.callsign,
                                src,
                                ack_payload,
                                path_disp,
                                True,
                            ))
                            self._log_message(
                                ack_ts, self.cfg.callsign, src, ack_payload, path_disp
                            )
                            self.sent_ack_times[ack_key] = ack_ts
                        except (TypeError, ValueError):
                            self.last_delivery_status = 'ACK ERROR'

            # Attempt to decode Mic‑E packets.  This is done after
            # acknowledgement handling so that Mic‑E position reports are
            # converted to a human‑readable uncompressed form.  If the
            # decoder returns a string, replace the info bytes with the
            # decoded payload.  Use a try/except to avoid failing on
            # unexpected data.
            try:
                decoded = decode_mic_e(dest, info)
            except Exception:
                decoded = None
            if decoded is not None:
                # Keep the downstream representation as bytes without losing
                # UTF-8 characters from the Mic-E status/comment field.
                info = decoded.encode('utf-8')

            # Save message; display the path exactly as provided by the TNC
            self.messages.append((ts, src, dest, info, path, False))
            self._log_message(ts, src, dest, info, path)

    def _pop_pending_from(
        self, msg_id: str, source: str
    ) -> Optional[PendingMessage]:
        """Remove a pending message only when the ACK came from its addressee."""
        pending = self.pending_messages.get(msg_id)
        if pending is None:
            return None
        if pending.destination.upper() != source.upper():
            return None
        return self.pending_messages.pop(msg_id)

    def _track_pending_message(
        self,
        destination: str,
        text: str,
        msg_id: Optional[str],
        payload: bytes,
        sent_at: float,
    ) -> None:
        if msg_id is None:
            self.last_delivery_status = 'ONE-SHOT'
            return
        self.pending_messages[msg_id] = PendingMessage(
            destination=destination,
            text=text,
            msg_id=msg_id,
            payload=payload,
            last_sent=sent_at,
        )
        self.last_delivery_status = f'WAIT {msg_id}'

    def _retry_pending_messages(self) -> None:
        """Perform one conservative retry for an ACK-requesting message."""
        if not self.ack_enabled:
            return
        now = time.time()
        for msg_id, pending in list(self.pending_messages.items()):
            if now - pending.last_sent < MESSAGE_RETRY_INTERVAL:
                continue
            if pending.attempts >= MAX_MESSAGE_ATTEMPTS:
                del self.pending_messages[msg_id]
                self.last_delivery_status = f'NO ACK {msg_id}'
                continue
            try:
                ax25 = encode_ax25_frame(
                    self.cfg.tocall,
                    self.cfg.callsign,
                    self.cfg.path,
                    pending.payload,
                )
            except (TypeError, ValueError):
                del self.pending_messages[msg_id]
                self.last_delivery_status = f'ERROR {msg_id}'
                continue
            self.tnc.send_frame(ax25)
            pending.attempts += 1
            pending.last_sent = now
            path_disp = list(self.cfg.path)
            self.messages.append((
                now,
                self.cfg.callsign,
                pending.destination,
                pending.payload,
                path_disp,
                True,
            ))
            self._log_message(
                now,
                self.cfg.callsign,
                pending.destination,
                pending.payload,
                path_disp,
            )
            self.last_delivery_status = f'RETRY {msg_id}'

    # Prompt user for a string input
    def _prompt(self, prompt: str, default: str = '') -> Optional[str]:
        curses.echo()
        # Determine the bottom line and available width dynamically to
        # ensure prompts always appear at the very bottom of the screen
        # regardless of terminal resize.  curses.LINES and curses.COLS are
        # static values captured at program start, so use getmaxyx() on
        # the current window for up-to-date dimensions.
        height, width = self.stdscr.getmaxyx()
        bottom_y = height - 1
        # Clear the entire bottom line before writing the prompt
        self.stdscr.addstr(bottom_y, 0, ' ' * (width - 1))
        self.stdscr.addstr(bottom_y, 0, prompt)
        self.stdscr.refresh()
        try:
            # Read input starting after the prompt; limit maximum length to 60
            input_str = self.stdscr.getstr(bottom_y, len(prompt), 60)
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
        # should have already set nodelay(False).  Echo is disabled because
        # this method redraws the editable line itself.
        curses.noecho()
        buffer: List[str] = []

        def _fit_prompt(text: str, usable_width: int) -> str:
            if usable_width <= 0:
                return ''
            # Leave at least one column for input; for longer prompts, keep a
            # small edit area visible even when the terminal is narrow.
            if len(text) < usable_width:
                return text
            min_input_width = min(20, max(1, usable_width // 3))
            prompt_width = max(0, usable_width - min_input_width)
            if prompt_width <= 0:
                return ''
            if prompt_width <= 3:
                return text[:prompt_width]
            return text[:prompt_width - 3] + '...'

        def _redraw_prompt() -> None:
            # Re-read dimensions on every draw so terminal resizes during
            # input cannot leave the cursor outside the screen.
            height, width = self.stdscr.getmaxyx()
            bottom_y = max(0, height - 1)
            usable_width = max(0, width - 1)
            prompt_text = _fit_prompt(prompt, usable_width)
            input_width = max(1, usable_width - len(prompt_text))
            input_text = ''.join(buffer)
            visible_input = input_text[-input_width:]
            line = (prompt_text + visible_input)[:usable_width]

            self.stdscr.move(bottom_y, 0)
            self.stdscr.clrtoeol()
            if line:
                self.stdscr.addstr(bottom_y, 0, line)
            if width > 0:
                cursor_x = min(len(prompt_text) + len(visible_input), max(0, usable_width - 1))
                self.stdscr.move(bottom_y, cursor_x)
            self.stdscr.refresh()

        try:
            _redraw_prompt()
            while True:
                try:
                    ch = self.stdscr.get_wch()
                except Exception:
                    continue
                if isinstance(ch, int) and ch == curses.KEY_RESIZE:
                    _redraw_prompt()
                    continue
                # Enter key (carriage return or newline) finalises input
                if ch in ('\n', '\r', 10, 13):
                    break
                # Escape key cancels input
                if ch in ('\x1b', 27):
                    return None
                # Backspace handling (support DEL and Backspace)
                if ch in ('\x7f', '\b', curses.KEY_BACKSPACE, 127, 8):
                    if buffer:
                        buffer.pop()
                        _redraw_prompt()
                    continue
                # Ignore control characters and curses special-key values.
                if isinstance(ch, int):
                    continue
                if ord(ch) < 32 or ord(ch) == 127:
                    continue
                buffer.append(ch)
                _redraw_prompt()
        finally:
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
            # Determine whether to include an acknowledgement ID.  One-shot
            # mode omits the ID; confirmed mode uses a limited retry policy.
            if self.ack_enabled:
                msg_id = _format_message_id(self.cfg.next_msg_id())
            else:
                msg_id = None
            try:
                payload = build_aprs_message(dest, text, msg_id=msg_id)
                ax25 = encode_ax25_frame(
                    self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
                )
            except (TypeError, ValueError):
                self.last_delivery_status = 'INVALID MSG'
                return
            self.tnc.send_frame(ax25)
            # Log our own outgoing message to the UI
            ts = time.time()
            # Mark our path so that the last digipeater is displayed with '*'
            # Display the configured path as is without marking the last hop.
            path_disp = list(self.cfg.path)
            self.messages.append((ts, self.cfg.callsign, dest, payload, path_disp, True))
            self._log_message(ts, self.cfg.callsign, dest, payload, path_disp)
            # Store last message for possible retransmission.  msg_id may be None
            # when acknowledgements are disabled.
            self.last_message = (dest, text, msg_id)
            self._track_pending_message(dest, text, msg_id, payload, ts)
        finally:
            # Restore non‑blocking mode
            self.stdscr.nodelay(True)
            self.stdscr.timeout(100)

    # Send a position beacon
    def _send_position(self) -> None:
        # Use the stored position comment directly; do not prompt each time.
        comment = self.cfg.pos_comment
        try:
            payload = build_aprs_position(
                self.cfg.latitude,
                self.cfg.longitude,
                self.cfg.symbol_table,
                self.cfg.symbol_code,
                comment,
                messaging_capable=True,
            )
            ax25 = encode_ax25_frame(
                self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
            )
        except (TypeError, ValueError):
            self.last_delivery_status = 'INVALID POS'
            return
        self.tnc.send_frame(ax25)
        ts = time.time()
        # Mark path for display
        # Display the configured path as is without marking the last hop
        path_disp = list(self.cfg.path)
        self.messages.append((ts, self.cfg.callsign, self.cfg.tocall, payload, path_disp, True))
        self._log_message(ts, self.cfg.callsign, self.cfg.tocall, payload, path_disp)

    # Edit configuration interactively
    def _edit_config(self) -> None:
        # Temporarily disable non‑blocking input to allow the user time to type
        self.stdscr.nodelay(False)
        self.stdscr.timeout(-1)
        try:
            # Use cancelable prompts for each field so that pressing ESC aborts
            # the entire configuration edit.  Collect values locally and
            # commit them only if all prompts succeed.
            # Callsign
            new_call = self._prompt_cancelable(
                f"Callsign (current {self.cfg.callsign}): ", self.cfg.callsign
            )
            if new_call is None:
                return
            # AX.25 destination / APRS software identifier
            new_tocall = self._prompt_cancelable(
                f"TOCALL (current {self.cfg.tocall}): ", self.cfg.tocall
            )
            if new_tocall is None:
                return
            # Digipeater path
            path_str = self._prompt_cancelable(
                f"Digipeater path comma separated (current {','.join(self.cfg.path)}): ",
                ','.join(self.cfg.path)
            )
            if path_str is None:
                return
            # Latitude magnitude and direction
            lat_val_str = self._prompt_cancelable(
                f"Latitude degrees (decimal) (current {abs(self.cfg.latitude)}): ",
                str(abs(self.cfg.latitude))
            )
            if lat_val_str is None:
                return
            lat_dir = self._prompt_cancelable(
                f"Latitude direction (N/S) (current {'N' if self.cfg.latitude >= 0 else 'S'}): ",
                'N' if self.cfg.latitude >= 0 else 'S'
            )
            if lat_dir is None:
                return
            # Longitude magnitude and direction
            lon_val_str = self._prompt_cancelable(
                f"Longitude degrees (decimal) (current {abs(self.cfg.longitude)}): ",
                str(abs(self.cfg.longitude))
            )
            if lon_val_str is None:
                return
            lon_dir = self._prompt_cancelable(
                f"Longitude direction (E/W) (current {'E' if self.cfg.longitude >= 0 else 'W'}): ",
                'E' if self.cfg.longitude >= 0 else 'W'
            )
            if lon_dir is None:
                return
            # Symbol table and code
            sym_table = self._prompt_cancelable(
                f"Symbol table (/ or \\) (current {self.cfg.symbol_table}): ",
                self.cfg.symbol_table
            )
            if sym_table is None:
                return
            sym_code = self._prompt_cancelable(
                f"Symbol code (current {self.cfg.symbol_code}): ", self.cfg.symbol_code
            )
            if sym_code is None:
                return
            # Default position comment
            pos_comm = self._prompt_cancelable(
                f"Default position comment (current {self.cfg.pos_comment}): ",
                self.cfg.pos_comment
            )
            if pos_comm is None:
                return
            # Ask for KISS host and port so that the user can modify the
            # connection details of the TNC.  These values are optional;
            # pressing Enter without typing retains the current value.
            new_host = self._prompt_cancelable(
                f"KISS host (current {self.cfg.host}): ", self.cfg.host
            )
            if new_host is None:
                return
            new_port_str = self._prompt_cancelable(
                f"KISS port (current {self.cfg.port}): ", str(self.cfg.port)
            )
            if new_port_str is None:
                return
            # Validate all values before changing the active configuration.
            try:
                valid_call = normalize_ax25_address(new_call, 'Callsign')
                valid_tocall = normalize_ax25_address(new_tocall, 'TOCALL')
                valid_path = normalize_path([
                    p.strip().upper()
                    for p in path_str.replace(',', ' ').split()
                    if p.strip()
                ])
                lat_mag = abs(float(lat_val_str))
                lon_mag = abs(float(lon_val_str))
                lat_dir_value = lat_dir.strip().upper()
                lon_dir_value = lon_dir.strip().upper()
                if lat_dir_value not in ('N', 'S'):
                    raise ValueError('Latitude direction must be N or S')
                if lon_dir_value not in ('E', 'W'):
                    raise ValueError('Longitude direction must be E or W')
                valid_lat = lat_mag if lat_dir_value == 'N' else -lat_mag
                valid_lon = lon_mag if lon_dir_value == 'E' else -lon_mag
                valid_symbol_table = sym_table.strip().upper()
                valid_symbol_code = sym_code[0] if sym_code else ''
                valid_comment = pos_comm[:MAX_POSITION_COMMENT_CHARS]
                valid_host = new_host.strip()
                valid_port = int(new_port_str)
                if not valid_host:
                    raise ValueError('KISS host cannot be empty')
                if not 1 <= valid_port <= 65535:
                    raise ValueError('KISS port must be between 1 and 65535')
                # Reuse the packet builder as the canonical coordinate/symbol
                # validation path.
                build_aprs_position(
                    valid_lat,
                    valid_lon,
                    valid_symbol_table,
                    valid_symbol_code,
                    valid_comment,
                )
            except (TypeError, ValueError):
                self.last_delivery_status = 'INVALID CFG'
                return

            self.cfg.callsign = valid_call
            self.cfg.tocall = valid_tocall
            self.cfg.path = valid_path
            self.cfg.latitude = valid_lat
            self.cfg.longitude = valid_lon
            self.cfg.symbol_table = valid_symbol_table
            self.cfg.symbol_code = valid_symbol_code
            self.cfg.pos_comment = valid_comment
            self.cfg.host = valid_host
            self.cfg.port = valid_port
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

    def toggle_ack(self) -> None:
        """Toggle one-shot versus end-to-end acknowledged messages."""
        # Flip the acknowledgement flag and propagate the change back to the
        # configuration so that it can be persisted when saving.  Without
        # updating cfg.ack_enabled, the toggled state would be lost on the
        # next run.
        self.ack_enabled = not self.ack_enabled
        if not self.ack_enabled:
            self.pending_messages.clear()
            self.last_delivery_status = 'ONE-SHOT'
        if hasattr(self.cfg, 'ack_enabled'):
            self.cfg.ack_enabled = self.ack_enabled

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
        try:
            payload = build_aprs_message(dest, text, msg_id=use_id)
            ax25 = encode_ax25_frame(
                self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
            )
        except (TypeError, ValueError):
            self.last_delivery_status = 'INVALID MSG'
            return
        self.tnc.send_frame(ax25)
        ts = time.time()
        # Log retransmitted message in the UI
        # Use the configured path as is for display
        path_disp = list(self.cfg.path)
        self.messages.append((ts, self.cfg.callsign, dest, payload, path_disp, True))
        self._log_message(ts, self.cfg.callsign, dest, payload, path_disp)
        self._track_pending_message(dest, text, use_id, payload, ts)

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
            if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
                self.last_delivery_status = 'INVALID RAW'
                return
            payload = text.encode('utf-8')
            try:
                ax25 = encode_ax25_frame(
                    self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
                )
            except (TypeError, ValueError):
                self.last_delivery_status = 'INVALID RAW'
                return
            self.tnc.send_frame(ax25)
            ts = time.time()
            # Log the transmission and display the TOCALL as the destination.  Even
            # though the payload is unaddressed, including TOCALL in the UI
            # clarifies which software identifier was used.
            # Display the configured path as is
            path_disp = list(self.cfg.path)
            self.messages.append((ts, self.cfg.callsign, self.cfg.tocall, payload, path_disp, True))
            self._log_message(ts, self.cfg.callsign, self.cfg.tocall, payload, path_disp)
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
        payload = text.encode('utf-8')
        try:
            ax25 = encode_ax25_frame(
                self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
            )
        except (TypeError, ValueError):
            self.last_delivery_status = 'INVALID RAW'
            return
        self.tnc.send_frame(ax25)
        ts = time.time()
        # Display the TOCALL as the destination in the UI for raw repeats
        # Display the configured path as is
        path_disp = list(self.cfg.path)
        self.messages.append((ts, self.cfg.callsign, self.cfg.tocall, payload, path_disp, True))
        self._log_message(ts, self.cfg.callsign, self.cfg.tocall, payload, path_disp)

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
            msg_id = (
                _format_message_id(self.cfg.next_msg_id())
                if self.ack_enabled else None
            )
            try:
                payload = build_aprs_message(dest, quick_text, msg_id=msg_id)
                ax25 = encode_ax25_frame(
                    self.cfg.tocall, self.cfg.callsign, self.cfg.path, payload
                )
            except (TypeError, ValueError):
                self.last_delivery_status = 'INVALID MSG'
                return
            self.tnc.send_frame(ax25)
            ts = time.time()
            path_disp = list(self.cfg.path)
            self.messages.append((ts, self.cfg.callsign, dest, payload, path_disp, True))
            self._log_message(ts, self.cfg.callsign, dest, payload, path_disp)
            # Update last_message record for potential repeat
            self.last_message = (dest, quick_text, msg_id)
            self._track_pending_message(dest, quick_text, msg_id, payload, ts)
        finally:
            self.stdscr.nodelay(True)
            self.stdscr.timeout(100)


def main(stdscr: curses.window) -> None:
    # Try to load previously saved configuration
    saved = load_saved_config()
    if saved:
        # Populate StationConfig from saved data
        raw_path = saved.get('path', DEFAULT_PATH)
        if isinstance(raw_path, str):
            raw_path = [raw_path]
        elif not isinstance(raw_path, list):
            raw_path = []
        normalized_path = [
            p.strip().upper()
            for item in raw_path
            for p in str(item).replace(',', ' ').split()
            if p.strip()
        ]
        cfg = StationConfig(
            callsign=saved.get('callsign', ''),
            tocall=saved.get('tocall', APP_TOCALL),
            path=normalized_path,
            latitude=saved.get('latitude', 0.0),
            longitude=saved.get('longitude', 0.0),
            symbol_table=saved.get('symbol_table', '/'),
            symbol_code=saved.get('symbol_code', '>'),
            host=saved.get('host', 'localhost'),
            port=saved.get('port', 8001),
            pos_comment=saved.get('pos_comment', ''),
            quick_msg1=saved.get('quick_msg1', 'QSL? 73'),
            quick_msg2=saved.get('quick_msg2', 'QSL! 73'),
            log_file=saved.get('log_file', 'aprs_tui.log'),
            ack_enabled=saved.get('ack_enabled', False),
        )
    else:
        # Interactive setup if no saved configuration
        cfg = StationConfig(
            callsign='',
            tocall=APP_TOCALL,
            path=list(DEFAULT_PATH),
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
        # Ask for the AX.25 destination / APRS TOCALL
        curses.echo()
        stdscr.addstr(1, 0, f"TOCALL (default {APP_TOCALL}): ")
        stdscr.refresh()
        tocall_input = stdscr.getstr().decode('utf-8').strip()
        if tocall_input:
            cfg.tocall = tocall_input.upper()
        curses.noecho()
        # Ask digipeater path
        curses.echo()
        stdscr.addstr(
            2,
            0,
            "Digipeater path (comma/space separated; blank for none): ",
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
        lat_mag = abs(lat_val)
        cfg.latitude = lat_mag if lat_dir == 'N' else -lat_mag
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
        lon_mag = abs(lon_val)
        cfg.longitude = lon_mag if lon_dir == 'E' else -lon_mag
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

        # Ask the user for the KISS TNC host.  This allows connecting to
        # a remote TNC (e.g. a modem on the local network).  Leave blank
        # to retain the default value of 'localhost'.
        curses.echo()
        row += 1
        stdscr.addstr(row, 0, "KISS host (IP or hostname) (default localhost): ")
        stdscr.clrtoeol()
        stdscr.refresh()
        host_input = stdscr.getstr().decode('utf-8').strip()
        curses.noecho()
        if host_input:
            cfg.host = host_input
        # Ask the user for the KISS port.  Leave blank to retain the
        # default value of 8001.  If a non‑integer is entered, ignore it.
        curses.echo()
        row += 1
        stdscr.addstr(row, 0, "KISS port (default 8001): ")
        stdscr.clrtoeol()
        stdscr.refresh()
        port_input = stdscr.getstr().decode('utf-8').strip()
        curses.noecho()
        if port_input:
            try:
                cfg.port = int(port_input)
            except Exception:
                # Ignore invalid port numbers and keep the default
                pass
    # Validate saved or interactively entered settings before opening the TNC.
    try:
        cfg.callsign = normalize_ax25_address(cfg.callsign, 'Callsign')
        cfg.tocall = normalize_ax25_address(cfg.tocall, 'TOCALL')
        cfg.path = normalize_path(cfg.path)
        cfg.latitude = float(cfg.latitude)
        cfg.longitude = float(cfg.longitude)
        cfg.port = int(cfg.port)
        if not 1 <= cfg.port <= 65535:
            raise ValueError('KISS port outside valid range')
        cfg.pos_comment = str(cfg.pos_comment)[:MAX_POSITION_COMMENT_CHARS]
        build_aprs_position(
            cfg.latitude,
            cfg.longitude,
            cfg.symbol_table,
            cfg.symbol_code,
            cfg.pos_comment,
        )
    except (TypeError, ValueError):
        stdscr.erase()
        stdscr.addstr(
            0,
            0,
            'Invalid station configuration; check callsign, TOCALL, path and position.',
        )
        stdscr.refresh()
        time.sleep(3)
        return

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
