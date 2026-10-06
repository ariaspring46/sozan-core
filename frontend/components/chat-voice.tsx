"use client";

import { MutableRefObject, useEffect, useRef, useState } from "react";
import { SozanOrb } from "@/components/sozan-orb";

type AudioCtor = typeof AudioContext;

/** بلندی صدای میکروفون (۰ تا ۱) را در `level` می‌نویسد؛ تابع برگشتی آن را می‌بندد. اگر مرورگر نتواند، فقط هیچ کاری نمی‌کند. */
function meter(stream: MediaStream, level: MutableRefObject<number>) {
  const Ctor: AudioCtor | undefined = window.AudioContext || (window as unknown as { webkitAudioContext?: AudioCtor }).webkitAudioContext;
  if (!Ctor) return () => undefined;
  try {
    const audio = new Ctor();
    void audio.resume().catch(() => undefined);
    const analyser = audio.createAnalyser();
    analyser.fftSize = 512;
    audio.createMediaStreamSource(stream).connect(analyser);
    const data = new Uint8Array(analyser.fftSize);
    let frame = 0;
    const read = () => {
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (const value of data) {
        const x = (value - 128) / 128;
        sum += x * x;
      }
      level.current = Math.min(1, Math.sqrt(sum / data.length) * 4);
      frame = window.requestAnimationFrame(read);
    };
    read();
    return () => {
      window.cancelAnimationFrame(frame);
      level.current = 0;
      void audio.close().catch(() => undefined);
    };
  } catch {
    return () => undefined;
  }
}

/** ضبط پیام صوتی فروشنده؛ فایل ضبط‌شده به `onDone` می‌رسد و `level` گوی سوزان را با صدا تکان می‌دهد. */
export function useVoiceRecorder(onDone: (file: File) => void) {
  const [recording, setRecording] = useState(false);
  const [micError, setMicError] = useState("");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const level = useRef(0);
  const stopMeter = useRef<() => void>(() => undefined);
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    return () => {
      stopMeter.current();
      recorderRef.current?.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  async function toggle() {
    setMicError("");
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    if (typeof MediaRecorder === "undefined") {
      setMicError("ضبط صدا در این مرورگر نیست.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stopMeter.current();
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        const ext = blob.type.includes("ogg") ? "ogg" : "webm";
        doneRef.current(new File([blob], `voice.${ext}`, { type: blob.type || "audio/webm" }));
        setRecording(false);
        recorderRef.current = null;
      };
      recorderRef.current = recorder;
      recorder.start();
      stopMeter.current = meter(stream, level);
      setRecording(true);
    } catch {
      setMicError("میکروفون در دسترس نیست.");
    }
  }

  return { recording, micError, toggle, level };
}

/** هنگام ضبط: گوی سوزان با صدای فروشنده بزرگ و کوچک می‌شود و زمان ضبط دیده می‌شود. */
export function VoiceListening({ level }: { level: MutableRefObject<number> }) {
  const [secs, setSecs] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => setSecs(Math.floor((Date.now() - started) / 1000)), 500);
    return () => window.clearInterval(timer);
  }, []);
  const clock = `${Math.floor(secs / 60).toLocaleString("fa-IR")}:${(secs % 60).toLocaleString("fa-IR", { minimumIntegerDigits: 2 })}`;
  return (
    <div className="sozan-card sozan-rise flex items-center gap-3 rounded-[1.65rem] py-1.5 pe-4 ps-2" role="status">
      <SozanOrb size={68} level={level} busy />
      <div className="min-w-0 flex-1">
        <p className="text-[15px] font-medium text-ink">دارم گوش می‌دهم…</p>
        <p className="text-xs text-muted">حرفت تمام شد، دکمهٔ توقف را بزن.</p>
      </div>
      <span className="shrink-0 text-sm tabular-nums text-warm" dir="ltr">
        {clock}
      </span>
    </div>
  );
}
