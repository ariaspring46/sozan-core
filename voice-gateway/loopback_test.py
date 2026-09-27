"""Place a local SIP call and check that Sozan answers in Persian."""

from __future__ import annotations

import array
import os
import secrets
import socket
import subprocess
import sys
import time

from audio_codec import decode_to_pcm16, encode_pcm16, pcm16_to_wav, resample_pcm16, rtp_packet, rtp_parse
from sip import parse_message

SIP_PORT = int(os.environ.get("LOCAL_SIP_PORT", "5062"))
RTP_PORT = 41002
ASK = "فروشگاه من ساخته نمی‌شود. چه کار کنم؟"


def wait_sip(sock: socket.socket, seconds: float = 5) -> dict:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        msg = parse_message(data)
        if msg and msg["start"].startswith("SIP/2.0"):
            return msg
    raise TimeoutError("no sip response")


def sdp_port(msg: dict) -> int:
    for line in msg["body"].splitlines():
        if line.lower().startswith("m=audio "):
            return int(line.split()[1])
    raise RuntimeError("no audio port")


def synthesize() -> bytes:
    piper = os.path.expanduser("~/.final-27b/bin/piper")
    model = os.path.expanduser("~/.final-27b/models/tts/fa_IR-gyro-medium.onnx")
    espeak = os.path.expanduser("~/.final-27b/bin/espeak-ng-data")
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = os.path.dirname(piper)
    proc = subprocess.run(
        [piper, "--model", model, "--output_raw", "--espeak_data", espeak, "-q"],
        input=ASK.encode(),
        capture_output=True,
        env=env,
        check=True,
    )
    return resample_pcm16(proc.stdout, 22050, 8000)


def main() -> None:
    sip = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sip.bind(("127.0.0.1", 5099))
    sip.settimeout(0.4)
    rtp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rtp.bind(("127.0.0.1", RTP_PORT))
    rtp.settimeout(0.2)
    call_id = secrets.token_hex(6)
    branch = "z9hG4bK" + secrets.token_hex(4)
    body = (
        "v=0\r\n"
        "o=- 1 1 IN IP4 127.0.0.1\r\n"
        "s=test\r\n"
        "c=IN IP4 127.0.0.1\r\n"
        "t=0 0\r\n"
        f"m=audio {RTP_PORT} RTP/AVP 8\r\n"
        "a=rtpmap:8 PCMA/8000\r\n"
        "a=sendrecv\r\n"
        "a=ptime:20\r\n"
    )
    invite = (
        f"INVITE sip:673068@127.0.0.1 SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP 127.0.0.1:5099;branch={branch}\r\n"
        "Max-Forwards: 70\r\n"
        "From: <sip:caller@127.0.0.1>;tag=caller\r\n"
        "To: <sip:673068@phone.telefonchy.com>\r\n"
        f"Call-ID: {call_id}\r\n"
        "CSeq: 1 INVITE\r\n"
        "Contact: <sip:caller@127.0.0.1:5099>\r\n"
        "Content-Type: application/sdp\r\n"
        f"Content-Length: {len(body.encode())}\r\n"
        "\r\n"
        f"{body}"
    )
    sip.sendto(invite.encode(), ("127.0.0.1", SIP_PORT))
    ok = None
    for _ in range(8):
        msg = wait_sip(sip, 3)
        code = msg["start"].split()[1]
        if code == "200":
            ok = msg
            break
    if not ok:
        raise SystemExit("call was not answered")
    ack = (
        f"ACK sip:673068@127.0.0.1:{SIP_PORT} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP 127.0.0.1:5099;branch={branch}\r\n"
        "Max-Forwards: 70\r\n"
        "From: <sip:caller@127.0.0.1>;tag=caller\r\n"
        f"To: {ok['headers']['to'][0]}\r\n"
        f"Call-ID: {call_id}\r\n"
        "CSeq: 1 ACK\r\n"
        "Content-Length: 0\r\n\r\n"
    )
    sip.sendto(ack.encode(), ("127.0.0.1", SIP_PORT))
    remote_rtp = sdp_port(ok)
    # Greeting is about five seconds. Talk after it, so barge-in does not cut it.
    time.sleep(6.2)
    pcm = synthesize()
    frames = [pcm[i : i + 320] for i in range(0, len(pcm) - 319, 320)]
    seq = 1
    ts = 0
    ssrc = 42
    for frame in frames:
        payload = encode_pcm16(frame, "pcma")
        rtp.sendto(
            rtp_packet(seq, ts, ssrc, payload, marker=seq == 1, pt=8),
            ("127.0.0.1", remote_rtp),
        )
        seq += 1
        ts += 160
        time.sleep(0.02)
    # Trailing silence so VAD closes the utterance.
    silence = encode_pcm16(b"\x00" * 320, "pcma")
    for _ in range(40):
        rtp.sendto(rtp_packet(seq, ts, ssrc, silence, pt=8), ("127.0.0.1", remote_rtp))
        seq += 1
        ts += 160
        time.sleep(0.02)
    heard = bytearray()
    started_listen = time.monotonic()
    first_audio_s = 0.0
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            data, _addr = rtp.recvfrom(2048)
        except socket.timeout:
            continue
        parsed = rtp_parse(data)
        if not parsed:
            continue
        pt, _seq, payload = parsed
        if pt != 8:
            continue
        pcm = decode_to_pcm16(payload, "pcma")
        heard.extend(pcm)
        if first_audio_s == 0.0:
            chunk = array.array("h")
            chunk.frombytes(pcm)
            if any(abs(sample) > 400 for sample in chunk):
                first_audio_s = time.monotonic() - started_listen
        if len(heard) > 8000 * 2 * 20:
            break
    out = "/tmp/sozan-voice-loopback.wav"
    samples = array.array("h")
    samples.frombytes(bytes(heard))
    loud = sum(1 for s in samples if abs(s) > 400)
    quiet_runs = 0
    run = 0
    for sample in samples:
        if abs(sample) < 80:
            run += 1
            if run == 800:
                quiet_runs += 1
        else:
            run = 0
    with open(out, "wb") as fh:
        fh.write(pcm16_to_wav(bytes(heard), 8000))
    bye = (
        f"BYE sip:673068@127.0.0.1:{SIP_PORT} SIP/2.0\r\n"
        f"Via: SIP/2.0/UDP 127.0.0.1:5099;branch={branch}\r\n"
        "Max-Forwards: 70\r\n"
        "From: <sip:caller@127.0.0.1>;tag=caller\r\n"
        f"To: {ok['headers']['to'][0]}\r\n"
        f"Call-ID: {call_id}\r\n"
        "CSeq: 2 BYE\r\n"
        "Content-Length: 0\r\n\r\n"
    )
    sip.sendto(bye.encode(), ("127.0.0.1", SIP_PORT))
    print(
        f"reply_pcm_bytes={len(heard)} loud_samples={loud} first_audio_s={first_audio_s:.2f} "
        f"quiet_100ms_runs={quiet_runs} wav={out}"
    )
    if loud < 1000:
        raise SystemExit("reply audio was silent")


if __name__ == "__main__":
    sys.exit(main())
