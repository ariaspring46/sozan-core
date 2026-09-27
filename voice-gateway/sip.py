"""Minimal SIP user agent: digest REGISTER and one answered call."""

from __future__ import annotations

import hashlib
import logging
import os
import random
import re
import secrets
import socket
import struct
import time
from dataclasses import dataclass, field

log = logging.getLogger("sozan.voice.sip")

_AUTH_RE = re.compile(r"(\w+)=(\"[^\"]*\"|[^,\s]+)")


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def digest_response(
    *,
    username: str,
    password: str,
    realm: str,
    nonce: str,
    method: str,
    uri: str,
    qop: str = "",
    nc: str = "00000001",
    cnonce: str = "",
) -> str:
    ha1 = md5_hex(f"{username}:{realm}:{password}")
    ha2 = md5_hex(f"{method}:{uri}")
    if qop:
        return md5_hex(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}")
    return md5_hex(f"{ha1}:{nonce}:{ha2}")


def parse_auth_challenge(header: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, raw in _AUTH_RE.findall(header):
        out[key.lower()] = raw.strip().strip('"')
    return out


def parse_message(data: bytes) -> dict | None:
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        return None
    head, _, body = text.partition("\r\n\r\n")
    if "\r\n" not in head and "\n" in head:
        head = head.replace("\n", "\r\n")
        body = body
    lines = head.split("\r\n")
    if not lines or not lines[0]:
        return None
    headers: dict[str, list[str]] = {}
    order: list[tuple[str, str]] = []
    for line in lines[1:]:
        if not line or ":" not in line:
            continue
        name, value = line.split(":", 1)
        key = name.strip().lower()
        val = value.strip()
        headers.setdefault(key, []).append(val)
        order.append((key, val))
    return {"start": lines[0].strip(), "headers": headers, "order": order, "body": body}


def header(msg: dict, name: str, default: str = "") -> str:
    vals = msg["headers"].get(name.lower())
    return vals[0] if vals else default


def _private_ip(ip: str) -> bool:
    parts = ip.split(".")
    if len(parts) != 4 or not all(part.isdigit() for part in parts):
        return True
    a, b = int(parts[0]), int(parts[1])
    if a in {0, 10, 127} or a >= 224:
        return True
    if a == 192 and b == 168:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 100 and 64 <= b <= 127:
        return True
    return False


def stun_mapped(sock: socket.socket, host: str = "stun.l.google.com", port: int = 19302) -> tuple[str, int] | None:
    """Public mapping of this UDP socket. None when STUN is blocked."""
    req = struct.pack("!HHI", 0x0001, 0, 0x2112A442) + os.urandom(12)
    previous = sock.gettimeout()
    sock.settimeout(2)
    try:
        sock.sendto(req, (socket.gethostbyname(host), port))
        data, _addr = sock.recvfrom(2048)
    except OSError:
        return None
    finally:
        sock.settimeout(previous)
    if len(data) < 20 or data[4:8] != b"\x21\x12\xa4\x42":
        return None
    msg_len = struct.unpack("!H", data[2:4])[0]
    pos = 20
    end = min(len(data), 20 + msg_len)
    while pos + 4 <= end:
        atype, alen = struct.unpack("!HH", data[pos : pos + 4])
        val = data[pos + 4 : pos + 4 + alen]
        if atype in {0x0001, 0x0020} and len(val) >= 8 and val[1] == 0x01:
            mapped_port = struct.unpack("!H", val[2:4])[0]
            mapped_ip = struct.unpack("!I", val[4:8])[0]
            if atype == 0x0020:
                mapped_port ^= 0x2112
                mapped_ip ^= 0x2112A442
            ip = socket.inet_ntoa(struct.pack("!I", mapped_ip))
            if not _private_ip(ip):
                return ip, mapped_port
        pos += 4 + ((alen + 3) & ~3)
    return None


def public_ipv4() -> str:
    override = os.environ.get("SIP_PUBLIC_IP", "").strip()
    if override and not _private_ip(override):
        return override
    import urllib.request

    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open("https://api.ipify.org", timeout=5) as res:
            ip = res.read().decode().strip()
    except Exception:
        return ""
    return "" if _private_ip(ip) else ip


_DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


RING_TIMEOUT_S = 45.0


def normalize_dial(number: str) -> str:
    raw = number.translate(_DIGIT_MAP)
    digits = "".join(ch for ch in raw if ch.isdigit())
    if digits.startswith("0098"):
        digits = digits[4:]
    if digits.startswith("98") and len(digits) >= 12:
        digits = "0" + digits[2:]
    if len(digits) == 10 and digits.startswith("9"):
        digits = "0" + digits
    return digits


def local_ip_toward(host: str, port: int = 5060) -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((host, port))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


@dataclass
class Call:
    call_id: str
    remote_from: str
    remote_tag: str
    local_tag: str
    remote_target: str
    remote_uri: str
    remote_addr: tuple[str, int]
    rtp_dest: tuple[str, int] | None = None
    rtp_payload: str = "pcma"
    rtp_pt: int = 8
    acked: bool = False
    invite_cseq: str = "1"


@dataclass
class SipUA:
    domain: str
    user: str
    password: str
    server_port: int = 5060
    local_port: int = 5062
    rtp_port: int = 40000
    register: bool = True
    allowed_peers: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("0.0.0.0", self.local_port))
        self.sock.settimeout(0.4)
        self.server_ip = socket.gethostbyname(self.domain)
        self.allowed_peers.add(self.server_ip)
        self.allowed_peers.add("127.0.0.1")
        self.local_ip = local_ip_toward(self.server_ip, self.server_port)
        self.advertise_ip = self.local_ip
        self.advertise_port = self.local_port
        self._learn_public()
        self._next_keepalive = 0.0
        self.reg_call_id = secrets.token_hex(8)
        self.reg_tag = secrets.token_hex(4)
        self.cseq = 0
        self.running = True
        self.registered = False
        self.call: Call | None = None
        self.on_call = None
        self.on_hangup = None
        self.on_dial_fail = None
        self._next_register = 0.0
        self._register_gap = 30.0
        self._pending_ok: tuple[bytes, tuple[str, int], float] | None = None
        self._ok_tries = 0
        self._auth: dict[str, str] | None = None
        self._auth_nc = 0
        self._dial: dict | None = None
        log.info(
            "sip bind %s:%s toward %s (%s) contact %s:%s",
            self.local_ip,
            self.local_port,
            self.domain,
            self.server_ip,
            self.advertise_ip,
            self.advertise_port,
        )

    def _learn_public(self) -> None:
        # STUN's port is the mapping toward Google, not toward the PBX.
        # Advertise the house public address and the local port; the PBX
        # reply's public rport replaces it when the server reports one.
        ip = public_ipv4()
        if ip:
            self.advertise_ip = ip
            self.advertise_port = self.local_port
            return
        mapped = stun_mapped(self.sock)
        if mapped:
            self.advertise_ip, self.advertise_port = mapped

    def _note_public_via(self, via: str) -> None:
        received = _param(via, "received")
        rport = _param(via, "rport")
        if not received or _private_ip(received):
            return
        port = int(rport) if rport.isdigit() else self.advertise_port
        if (received, port) == (self.advertise_ip, self.advertise_port):
            return
        log.info("sip via public %s:%s", received, port)
        self.advertise_ip = received
        self.advertise_port = port
        self._next_register = min(self._next_register, time.monotonic() + 0.4)

    def stop(self) -> None:
        self.running = False
        if self.register and self.password:
            try:
                self._send_register(expires=0)
            except OSError:
                pass
        try:
            self.sock.close()
        except OSError:
            pass

    def loop(self) -> None:
        if self.register and self.password:
            self._next_register = 0.0
        while self.running:
            now = time.monotonic()
            if self.register and self.password and now >= self._next_register:
                self._send_register(expires=300)
                self._next_register = now + self._register_gap
            if self.register and now >= self._next_keepalive:
                try:
                    self.sock.sendto(b"\r\n\r\n", (self.server_ip, self.server_port))
                except OSError:
                    pass
                self._next_keepalive = now + 25
            dial = self._dial
            if dial and dial.get("progress") and now >= float(dial.get("ring_until") or 0):
                log.warning("sip ring timeout %s", dial.get("number"))
                self._cancel_dial()
            elif dial and not dial.get("progress") and now >= float(dial.get("next") or 0):
                tries = int(dial.get("tries") or 1) + 1
                dial["tries"] = tries
                dial["next"] = now + 1.0
                if tries > 6:
                    log.warning("sip dial timeout %s", dial.get("number"))
                    self._cancel_dial()
                else:
                    packet = dial.get("packet")
                    if isinstance(packet, bytes):
                        self._send(packet, (self.server_ip, self.server_port))
            if self._pending_ok and now >= self._pending_ok[2]:
                packet, addr, _when = self._pending_ok
                self._ok_tries += 1
                if self._ok_tries > 6:
                    self._pending_ok = None
                else:
                    self._send(packet, addr)
                    self._pending_ok = (packet, addr, now + min(4.0, 0.5 * self._ok_tries))
            try:
                data, addr = self.sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data or data.strip(b"\r\n") == b"":
                continue
            msg = parse_message(data)
            if not msg:
                continue
            start = msg["start"]
            if start.startswith("SIP/2.0"):
                self._on_response(msg, addr)
            else:
                self._on_request(msg, addr)

    def _uri(self) -> str:
        return f"sip:{self.user}@{self.domain}"

    def _dialog_contact(self, addr: tuple[str, int]) -> str:
        if addr[0] == "127.0.0.1":
            return f"<sip:{self.user}@127.0.0.1:{self.local_port}>"
        return f"<sip:{self.user}@{self.advertise_ip}:{self.advertise_port}>"

    def _contact(self, expires: int = 300) -> str:
        return f"<sip:{self.user}@{self.advertise_ip}:{self.advertise_port}>;expires={expires}"

    def _next_cseq(self) -> int:
        self.cseq += 1
        return self.cseq

    def _send(self, payload: bytes, addr: tuple[str, int]) -> None:
        self.sock.sendto(payload, addr)

    def _send_register(self, expires: int) -> None:
        cseq = self._next_cseq()
        branch = "z9hG4bK" + secrets.token_hex(6)
        uri = f"sip:{self.domain}"
        lines = [
            f"REGISTER {uri} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};rport;branch={branch}",
            "Max-Forwards: 70",
            f"From: <{self._uri()}>;tag={self.reg_tag}",
            f"To: <{self._uri()}>",
            f"Call-ID: {self.reg_call_id}",
            f"CSeq: {cseq} REGISTER",
            f"Contact: {self._contact(expires)}",
            f"Expires: {expires}",
            "Allow: INVITE, ACK, BYE, CANCEL, OPTIONS, INFO",
            "User-Agent: SozanVoice/1.0",
        ]
        if self._auth and expires > 0:
            lines.append(self._authorization("REGISTER", uri))
        lines.append("Content-Length: 0")
        lines.append("")
        lines.append("")
        self._send("\r\n".join(lines).encode("utf-8"), (self.server_ip, self.server_port))

    def _authorization(self, method: str, uri: str, proxy: bool = False) -> str:
        auth = self._auth or {}
        self._auth_nc += 1
        nc = f"{self._auth_nc:08x}"
        cnonce = secrets.token_hex(4)
        qop = auth.get("qop", "").split(",")[0].strip()
        if qop not in {"auth", ""}:
            qop = "auth" if "auth" in auth.get("qop", "") else ""
        response = digest_response(
            username=self.user,
            password=self.password,
            realm=auth.get("realm", self.domain),
            nonce=auth.get("nonce", ""),
            method=method,
            uri=uri,
            qop=qop,
            nc=nc,
            cnonce=cnonce,
        )
        parts = [
            f'Digest username="{self.user}"',
            f'realm="{auth.get("realm", self.domain)}"',
            f'nonce="{auth.get("nonce", "")}"',
            f'uri="{uri}"',
            f'response="{response}"',
            "algorithm=MD5",
        ]
        if qop:
            parts.append(f"qop={qop}")
            parts.append(f"nc={nc}")
            parts.append(f'cnonce="{cnonce}"')
        if auth.get("opaque"):
            parts.append(f'opaque="{auth["opaque"]}"')
        name = "Proxy-Authorization" if proxy else "Authorization"
        return name + ": " + ", ".join(parts)

    def _cancel_dial(self) -> None:
        dial = self._dial
        if not dial:
            return
        number = str(dial.get("number") or "")
        target = str(dial.get("target") or f"sip:{number}@{self.domain}")
        branch = str(dial.get("branch") or ("z9hG4bK" + secrets.token_hex(6)))
        lines = [
            f"CANCEL {target} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};rport;branch={branch}",
            "Max-Forwards: 70",
            f"From: <{self._uri()}>;tag={dial.get('local_tag', '')}",
            f"To: <{target}>",
            f"Call-ID: {dial.get('call_id')}",
            f"CSeq: {dial.get('cseq')} CANCEL",
            "User-Agent: SozanVoice/1.0",
            "Content-Length: 0",
            "",
            "",
        ]
        self._send("\r\n".join(lines).encode(), (self.server_ip, self.server_port))
        self._dial = None
        fail = self.on_dial_fail
        if fail:
            fail(number)

    def dial(self, number: str) -> str:
        target = normalize_dial(number)
        if not target:
            return ""
        if self.call or self._dial:
            log.warning("sip dial busy")
            return ""
        alts = [target]
        if target.startswith("0") and len(target) >= 10:
            alts.append("98" + target[1:])
        self._invite(alts[0], alts=alts)
        return target

    def _invite(self, number: str, *, alts: list[str] | None = None, proxy: bool = False) -> None:
        previous = self._dial or {}
        call_id = str(previous.get("call_id") or secrets.token_hex(8))
        local_tag = str(previous.get("local_tag") or secrets.token_hex(4))
        cseq = self._next_cseq()
        branch = "z9hG4bK" + secrets.token_hex(6)
        target = f"sip:{number}@{self.domain}"
        sdp = self._offer_sdp()
        lines = [
            f"INVITE {target} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};rport;branch={branch}",
            "Max-Forwards: 70",
            f"From: <{self._uri()}>;tag={local_tag}",
            f"To: <{target}>",
            f"Call-ID: {call_id}",
            f"CSeq: {cseq} INVITE",
            f"Contact: <sip:{self.user}@{self.advertise_ip}:{self.advertise_port}>",
            "Allow: INVITE, ACK, BYE, CANCEL, OPTIONS",
            "User-Agent: SozanVoice/1.0",
            "Content-Type: application/sdp",
        ]
        if proxy or (self._auth and previous.get("auth")):
            lines.append(self._authorization("INVITE", target, proxy=proxy or previous.get("proxy") is True))
        lines.append(f"Content-Length: {len(sdp.encode())}")
        lines.append("")
        lines.append("")
        packet = "\r\n".join(lines).encode() + sdp.encode()
        self._dial = {
            "number": number,
            "alts": alts or previous.get("alts") or [number],
            "call_id": call_id,
            "local_tag": local_tag,
            "cseq": str(cseq),
            "target": target,
            "branch": branch,
            "packet": packet,
            "tries": 1,
            "next": time.monotonic() + 1.0,
            "progress": False,
            "auth": bool(self._auth and (proxy or previous.get("auth"))),
            "proxy": proxy or previous.get("proxy") is True,
        }
        log.info("sip dial %s", number)
        self._send(packet, (self.server_ip, self.server_port))

    def _offer_sdp(self) -> str:
        ip = self.advertise_ip
        return "\r\n".join(
            [
                "v=0",
                f"o=sozan {random.randint(1, 99999)} 1 IN IP4 {ip}",
                "s=Sozan",
                f"c=IN IP4 {ip}",
                "t=0 0",
                f"m=audio {self.rtp_port} RTP/AVP 8 101",
                "a=rtpmap:8 PCMA/8000",
                "a=rtpmap:101 telephone-event/8000",
                "a=fmtp:101 0-16",
                "a=ptime:20",
                "a=sendrecv",
                "",
            ]
        )

    def _ack_invite(self, msg: dict, *, success: bool) -> None:
        dial = self._dial or {}
        to_h = header(msg, "to")
        contact = _angle(header(msg, "contact")) or str(dial.get("target") or self._uri())
        branch = str(dial.get("branch") or "")
        if success:
            branch = "z9hG4bK" + secrets.token_hex(6)
        cseq_no = str(dial.get("cseq") or "1")
        lines = [
            f"ACK {contact} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};rport;branch={branch}",
            "Max-Forwards: 70",
            f"From: <{self._uri()}>;tag={dial.get('local_tag', '')}",
            f"To: {to_h}",
            f"Call-ID: {header(msg, 'call-id')}",
            f"CSeq: {cseq_no} ACK",
            "User-Agent: SozanVoice/1.0",
            "Content-Length: 0",
            "",
            "",
        ]
        self._send("\r\n".join(lines).encode(), (self.server_ip, self.server_port))

    def _on_outbound(self, msg: dict, code: int) -> None:
        dial = self._dial
        cseq_no = header(msg, "cseq").split()[0] if header(msg, "cseq") else ""
        if not dial or header(msg, "call-id") != dial.get("call_id") or cseq_no != str(dial.get("cseq")):
            return
        dial["progress"] = True
        if code in {100, 180, 183}:
            log.info("sip dial %s", msg["start"])
            if not dial.get("ring_until"):
                dial["ring_until"] = time.monotonic() + RING_TIMEOUT_S
            rtp = _sdp_audio(msg.get("body") or "")
            if rtp and self.call:
                self.call.rtp_dest = (rtp[0], rtp[1])
            return
        if code in {401, 407} and not dial.get("auth"):
            challenge = header(msg, "proxy-authenticate") or header(msg, "www-authenticate")
            self._auth = parse_auth_challenge(challenge)
            dial["auth"] = True
            dial["proxy"] = code == 407 or bool(header(msg, "proxy-authenticate"))
            self._ack_invite(msg, success=False)
            self._invite(str(dial["number"]), alts=list(dial.get("alts") or []), proxy=bool(dial["proxy"]))
            return
        if code == 200:
            self._ack_invite(msg, success=True)
            to_h = header(msg, "to")
            contact = _angle(header(msg, "contact")) or str(dial["target"])
            call = Call(
                call_id=str(dial["call_id"]),
                remote_from=to_h,
                remote_tag=_param(to_h, "tag"),
                local_tag=str(dial["local_tag"]),
                remote_target=contact,
                remote_uri=_angle(to_h) or str(dial["target"]),
                remote_addr=(self.server_ip, self.server_port),
                invite_cseq=str(dial["cseq"]),
                acked=True,
            )
            rtp = _sdp_audio(msg.get("body") or "")
            if rtp:
                call.rtp_dest = (rtp[0], rtp[1])
                call.rtp_payload = rtp[2]
                call.rtp_pt = rtp[3]
            self.call = call
            self._dial = None
            log.info("sip dial answered rtp=%s", call.rtp_dest)
            if self.on_call:
                self.on_call(call)
            return
        self._ack_invite(msg, success=False)
        alts = list(dial.get("alts") or [])
        number = str(dial["number"])
        if number in alts:
            alts = alts[alts.index(number) + 1 :]
        self._dial = None
        log.warning("sip dial failed %s", msg["start"])
        if code in {404, 484, 488} and alts:
            self._invite(alts[0], alts=alts)
            return
        fail = self.on_dial_fail
        if fail:
            fail(number)

    def _on_response(self, msg: dict, addr: tuple[str, int]) -> None:
        start = msg["start"]
        parts = start.split(" ", 2)
        code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        cseq = header(msg, "cseq")
        method = cseq.split()[-1].upper() if cseq else ""
        via = header(msg, "via")
        self._note_public_via(via)
        if method == "REGISTER":
            if code == 200:
                fresh = not self.registered
                self.registered = True
                self._register_gap = 120.0
                self._next_register = time.monotonic() + self._register_gap
                if fresh:
                    log.info("sip registered as %s via %s:%s", self.user, self.advertise_ip, self.advertise_port)
            elif code in {401, 407}:
                challenge = header(msg, "www-authenticate") or header(msg, "proxy-authenticate")
                self._auth = parse_auth_challenge(challenge)
                self.registered = False
                self._register_gap = 2.0
                self._next_register = time.monotonic() + 0.2
                log.info("sip auth challenge realm=%s", self._auth.get("realm", ""))
            else:
                self.registered = False
                self._register_gap = 20.0
                self._next_register = time.monotonic() + self._register_gap
                log.warning("sip register failed %s", start)
            return
        if method == "INVITE":
            self._on_outbound(msg, code)
            return
        if code >= 300 and self.call and method in {"INVITE", "BYE"}:
            log.warning("sip %s failed %s", method, start)

    def _peer_allowed(self, addr: tuple[str, int]) -> bool:
        return addr[0] in self.allowed_peers or addr[0].startswith("192.168.") or addr[0].startswith("10.")

    def _on_request(self, msg: dict, addr: tuple[str, int]) -> None:
        start = msg["start"]
        method = start.split(" ", 1)[0].upper()
        log.info("sip %s from %s:%s", method, addr[0], addr[1])
        if method == "OPTIONS":
            self._reply(msg, addr, 200, "OK")
            return
        if not self._peer_allowed(addr):
            log.warning("sip rejected %s from %s", method, addr[0])
            self._reply(msg, addr, 403, "Forbidden")
            return
        if method == "INVITE":
            self._on_invite(msg, addr)
        elif method == "ACK":
            if self.call and header(msg, "call-id") == self.call.call_id:
                self.call.acked = True
                self._pending_ok = None
        elif method == "BYE":
            self._reply(msg, addr, 200, "OK")
            if self.call and header(msg, "call-id") == self.call.call_id:
                call = self.call
                self.call = None
                self._pending_ok = None
                if self.on_hangup:
                    self.on_hangup(call)
        elif method == "CANCEL":
            self._reply(msg, addr, 200, "OK")
            if self.call and header(msg, "call-id") == self.call.call_id:
                self._reply_saved_invite(487, "Request Terminated")
                call = self.call
                self.call = None
                if self.on_hangup:
                    self.on_hangup(call)
        elif method == "INFO":
            self._reply(msg, addr, 200, "OK")
        else:
            self._reply(msg, addr, 405, "Method Not Allowed")

    def _on_invite(self, msg: dict, addr: tuple[str, int]) -> None:
        call_id = header(msg, "call-id")
        if self.call and self.call.call_id == call_id:
            self._answer(msg, addr, self.call)
            return
        if self.call:
            self._reply(msg, addr, 486, "Busy Here")
            return
        from_h = header(msg, "from")
        tag = _param(from_h, "tag") or secrets.token_hex(3)
        local_tag = secrets.token_hex(4)
        target = header(msg, "contact") or from_h
        target = target.strip().lstrip("<").split(">")[0].strip()
        remote_uri = _angle(from_h) or target or self._uri()
        cseq = header(msg, "cseq").split()[0] if header(msg, "cseq") else "1"
        call = Call(
            call_id=call_id or secrets.token_hex(6),
            remote_from=from_h,
            remote_tag=tag,
            local_tag=local_tag,
            remote_target=target or remote_uri,
            remote_uri=remote_uri,
            remote_addr=addr,
            invite_cseq=cseq,
        )
        rtp = _sdp_audio(msg.get("body") or "")
        if rtp:
            call.rtp_dest = (rtp[0], rtp[1])
            call.rtp_payload = rtp[2]
            call.rtp_pt = rtp[3]
        self.call = call
        self._last_invite = msg
        self._reply(msg, addr, 100, "Trying")
        self._answer(msg, addr, call)
        log.info("sip invite from %s rtp=%s %s", addr[0], call.rtp_dest, call.rtp_payload)
        if self.on_call:
            self.on_call(call)

    def _answer(self, msg: dict, addr: tuple[str, int], call: Call) -> None:
        sdp_ip = "127.0.0.1" if addr[0] == "127.0.0.1" else self.advertise_ip
        kind = call.rtp_payload
        pt = call.rtp_pt
        codec = "PCMA" if kind == "pcma" else "PCMU"
        sdp = "\r\n".join(
            [
                "v=0",
                f"o=sozan {random.randint(1, 99999)} 1 IN IP4 {sdp_ip}",
                "s=Sozan",
                f"c=IN IP4 {sdp_ip}",
                "t=0 0",
                f"m=audio {self.rtp_port} RTP/AVP {pt} 101",
                f"a=rtpmap:{pt} {codec}/8000",
                "a=rtpmap:101 telephone-event/8000",
                "a=fmtp:101 0-16",
                "a=ptime:20",
                "a=sendrecv",
                "",
            ]
        )
        self._reply(msg, addr, 200, "OK", body=sdp, content_type="application/sdp", extra_to_tag=call.local_tag)
        packet = self._last_reply
        self._ok_tries = 1
        self._pending_ok = (packet, addr, time.monotonic() + 0.5)

    def _reply_saved_invite(self, code: int, reason: str) -> None:
        if not getattr(self, "_last_invite", None) or not self.call:
            return
        self._reply(self._last_invite, self.call.remote_addr, code, reason, extra_to_tag=self.call.local_tag)

    def _reply(
        self,
        msg: dict,
        addr: tuple[str, int],
        code: int,
        reason: str,
        *,
        body: str = "",
        content_type: str = "",
        extra_to_tag: str = "",
    ) -> None:
        vias = msg["headers"].get("via", [])
        from_h = header(msg, "from")
        to_h = header(msg, "to")
        if extra_to_tag and "tag=" not in to_h.lower():
            to_h = f"{to_h};tag={extra_to_tag}"
        lines = [f"SIP/2.0 {code} {reason}"]
        for via in vias:
            lines.append(f"Via: {via}")
        lines.extend(
            [
                f"From: {from_h}",
                f"To: {to_h}",
                f"Call-ID: {header(msg, 'call-id')}",
                f"CSeq: {header(msg, 'cseq')}",
                f"Contact: {self._dialog_contact(addr)}",
                "User-Agent: SozanVoice/1.0",
            ]
        )
        if content_type:
            lines.append(f"Content-Type: {content_type}")
        encoded = body.encode("utf-8")
        lines.append(f"Content-Length: {len(encoded)}")
        lines.append("")
        lines.append("")
        packet = "\r\n".join(lines).encode("utf-8") + encoded
        self._last_reply = packet
        self._send(packet, addr)

    def hangup(self) -> None:
        call = self.call
        if not call:
            return
        self.call = None
        self._pending_ok = None
        cseq = self._next_cseq()
        branch = "z9hG4bK" + secrets.token_hex(6)
        target = call.remote_target or self._uri()
        if not target.lower().startswith("sip:"):
            target = self._uri()
        lines = [
            f"BYE {target} SIP/2.0",
            f"Via: SIP/2.0/UDP {self.local_ip}:{self.local_port};rport;branch={branch}",
            "Max-Forwards: 70",
            f"From: <{self._uri()}>;tag={call.local_tag}",
            f"To: <{call.remote_uri}>;tag={call.remote_tag}",
            f"Call-ID: {call.call_id}",
            f"CSeq: {cseq} BYE",
            "User-Agent: SozanVoice/1.0",
            "Content-Length: 0",
            "",
            "",
        ]
        try:
            self._send("\r\n".join(lines).encode("utf-8"), call.remote_addr)
        except OSError:
            pass


def _angle(header_value: str) -> str:
    match = re.search(r"<([^>]+)>", header_value)
    return match.group(1).strip() if match else ""


def _param(header_value: str, name: str) -> str:
    match = re.search(rf"(?:^|;)\s*{re.escape(name)}\s*=\s*([^;>\s]+)", header_value, re.I)
    if not match:
        return ""
    return match.group(1).strip().strip('"')


def _sdp_audio(body: str) -> tuple[str, int, str, int] | None:
    ip = ""
    for line in body.splitlines():
        line = line.strip()
        if line.lower().startswith("c=in ip4 "):
            ip = line.split()[-1]
    port = 0
    pt = 8
    kind = "pcma"
    for line in body.splitlines():
        line = line.strip()
        if line.lower().startswith("m=audio "):
            bits = line.split()
            if len(bits) >= 4 and bits[1].isdigit():
                port = int(bits[1])
                payloads = [p for p in bits[3:] if p.isdigit()]
                if "8" in payloads:
                    pt, kind = 8, "pcma"
                elif "0" in payloads:
                    pt, kind = 0, "pcmu"
                elif payloads:
                    pt = int(payloads[0])
                    kind = "pcma" if pt == 8 else "pcmu"
            break
    if not ip or not port:
        return None
    return ip, port, kind, pt


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
