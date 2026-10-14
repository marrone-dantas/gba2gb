"""Phase 4.3: GBA sound -> DMG APU (runtime/gb_audio_shims.asm, docs/audio.md).

* Register mapping: the GBA reference (Unicorn) logs every sound/DMA/timer register
  write of sound_demo; tools/audio/psg_map.py turns it into the expected DMG register
  writes; PyBoy (DMG) must make exactly these writes (per register, in order).
* DirectSound: the SFX stream (timer interrupt, 4-bit chunks) is checked against the
  offline conversion; its CPU cost is measured.
* Audio: PyBoy's sound buffer is written to a WAV and compared with a real GBA
  recording of the same ROM made with mGBA (tools/gba_capture, `audio` command) when
  that binary is available; spectrogram PNG side by side."""
import json
import os
import shutil
import subprocess
import wave
import numpy as np
import pytest
from PIL import Image, ImageDraw
from pyboy import PyBoy
from scipy.signal import spectrogram, resample_poly
from tools.audio.dsound_convert import to_chunks
from tools.audio.psg_map import PSGMap
from tools.hal.demos import build_demo, elf, ROOT
from tools.hal.gba_ref import GBARef
from tools.hal.gb_run import read_sym

N = 330
IMG = os.path.join(ROOT, "docs", "img")
AUD = os.path.join(ROOT, "docs", "audio")
MGBA = os.environ.get("MGBA_CAPTURE", "/workspace/private/mgba_capture")


def write_wav(path, x, sr):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(np.clip(x, -32768, 32767).astype("<i2").tobytes())


def spec(x, sr, fmax=8000):
    f, t, s = spectrogram(x, sr, nperseg=1024, noverlap=768)
    k = f <= fmax
    return f[k], t, 10 * np.log10(s[k] + 1e-10)


def spec_img(S, title, h=180):
    S = np.clip((S - (S.max() - 70)) / 70, 0, 1)[::-1]
    im = Image.fromarray((255 * S).astype(np.uint8)).resize((S.shape[1] * 2, h))
    out = Image.new("L", (im.width, h + 14), 0)
    out.paste(im, (0, 14))
    ImageDraw.Draw(out).text((2, 1), title, fill=255)
    return out


@pytest.fixture(scope="module")
def run():
    rom, prog = build_demo("sound_demo")
    ref = GBARef(elf("sound_demo"))
    ref.run([0] * (N + 1), N)
    pb = PyBoy(rom, window="null", cgb=False, sound_emulated=True)
    pb.set_emulation_speed(0)
    sym = read_sym(rom[:-4] + ".sym")
    log, cyc, t0 = [], [], {}
    b, a = sym["SndOut"]
    pb.hook_register(b, a, lambda c: log.append((pb.register_file.C, pb.register_file.A)), None)
    pb.hook_register(0, 0x50, lambda c: t0.__setitem__("t", pb._cycles()), None)
    chunks = []

    b, a = sym["SfxTimerISR.ret"]
    pb.hook_register(b, a, lambda c: cyc.append(pb._cycles() - t0.pop("t", pb._cycles())), None)
    b, a = sym["SfxChunk.loaded"]
    pb.hook_register(b, a, lambda c: chunks.append(bytes(pb.memory[0xFF30 + i] for i in range(16))), None)
    wcyc, w0 = [], {}
    b, a = sym["HAL_SND_WR"]
    pb.hook_register(b, a, lambda c: w0.__setitem__("t", pb._cycles()), None)
    b, a = sym["HAL_SND_WR.end"]
    pb.hook_register(b, a, lambda c: wcyc.append(pb._cycles() - w0.pop("t", pb._cycles())), None)
    buf = []
    frames = 0
    while (pb.memory[sym["wVsync"][1]] | pb.memory[sym["wVsync"][1] + 1] << 8) < N and frames < 3 * N:
        pb.tick(1, False, True)
        if pb.memory[sym["wVsync"][1]] | pb.memory[sym["wVsync"][1] + 1]:   # skip the boot ROM chime
            buf.append(pb.sound.ndarray.copy())
        frames += 1
    gb = np.concatenate(buf)[:, 0].astype(np.float64)
    out = {"rom": rom, "prog": prog, "ref": ref, "log": log, "isr": [c // 4 for c in cyc], "wr": [c // 4 for c in wcyc],
           "gb": gb, "chunks": chunks, "sr": pb.sound.sample_rate, "sym": sym, "pb": pb}
    yield out
    pb.stop()


def test_register_mapping(run):
    m = PSGMap()
    for _, a, sz, v in run["ref"].writes:
        m.write(a, sz, v)
    m.sfx_end()
    exp, got = {}, {}
    for r, v in m.out:
        exp.setdefault(r, []).append(v)
    for r, v in run["log"]:
        got.setdefault(r, []).append(v)
    assert set(exp) == set(got)
    for r in exp:
        # the GB may still be inside its last frame: compare the common prefix
        n = min(len(exp[r]), len(got[r]))
        assert n >= len(exp[r]) - 2 and exp[r][:n] == got[r][:n], (hex(r), exp[r][:8], got[r][:8])
    # NR50 honours the PSG ratio: 0xFF77 with SOUNDCNT_H = 0 (25 %) -> 1|1<<4, then 100 % -> 0x77
    assert exp[0x24][:2] == [0x11, 0x77]


def test_dsound_stream_and_cost(run):
    rep = run["prog"].hal_info["audio"]["sfx"]
    assert len(rep) == 1 and rep[0]["symbol"] == "sfx_zap" and rep[0]["fs_in"] == 8192.0
    q = rep[0]["_q"]
    packed = bytes((q[0::2] << 4 | q[1::2]).astype(np.uint8))
    want = [packed[16 * i:16 * i + 16] for i in range(rep[0]["chunks"])]
    got = run["chunks"]
    assert got[:len(want)] == want                               # first play, chunk by chunk
    isr = run["isr"]
    assert len(isr) >= 2 * rep[0]["chunks"] - 4                  # two SFX plays
    peak, typ = max(isr), int(np.median(isr))
    cpu = typ * 256 / (4194304 / 4)
    os.makedirs(os.path.join(ROOT, "build", "reports"), exist_ok=True)
    r = {"timer_isr_mcycles": [min(isr), typ, peak], "chunks_per_s": 256, "cpu_share_during_sfx": round(cpu, 4),
         "cpu_share_peak_isr": round(peak * 256 / (4194304 / 4), 4),
         "snd_wr_mcycles": [min(run["wr"]), max(run["wr"])], "sfx": [{k: v for k, v in x.items() if k != "_q"} for x in rep]}
    json.dump(r, open(os.path.join(ROOT, "build", "reports", "audio.json"), "w"), indent=1)
    print(r)
    assert cpu < 0.05


def test_audio_vs_gba(run):
    os.makedirs(AUD, exist_ok=True)
    sr, gb = run["sr"], run["gb"]
    on = np.flatnonzero(np.abs(gb) > 0)
    assert len(on), "PyBoy produced no sound"
    gb = gb[on[0]:]
    gb = gb / (np.abs(gb).max() + 1e-9) * 20000
    write_wav(os.path.join(AUD, "sound_demo_gb_dmg.wav"), gb, sr)
    f1, t1, S1 = spec(gb, sr)
    imgs = [spec_img(S1, "GB DMG (PyBoy, transpiled)")]
    res = {}
    if os.path.exists(MGBA):
        d = os.path.join(ROOT, "build", "audio_ref")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "s.txt"), "w") as fh:
            fh.write(f"audio ref.raw\nrun {N}\n")
        subprocess.run([MGBA, elf("sound_demo")[:-4] + ".gba", os.path.join(d, "s.txt"), d], check=True)
        ga = np.fromfile(os.path.join(d, "ref.raw"), np.int16).reshape(-1, 2)[:, 0].astype(np.float64)
        ga = ga[np.flatnonzero(np.abs(ga) > 64)[0]:]
        ga = resample_poly(ga, 375, 256)                             # 32768 -> 48000 Hz
        ga = ga / (np.abs(ga).max() + 1e-9) * 20000
        write_wav(os.path.join(AUD, "sound_demo_gba_mgba.wav"), ga, sr)
        f2, t2, S2 = spec(ga, sr)
        n = min(S1.shape[1], S2.shape[1])
        a, b = S1[:, :n], S2[:, :n]
        res["spec_corr"] = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
        pa, pb_ = f1[a.argmax(0)], f2[b.argmax(0)]
        loud = (b.max(0) > b.max() - 40)
        res["peak_freq_agree"] = float(np.mean(np.abs(pa[loud] - pb_[loud]) <= np.maximum(0.03 * pb_[loud], 50)))
        imgs.insert(0, spec_img(S2, "GBA reference (mGBA, same ROM)"))
        assert res["spec_corr"] > 0.7 and res["peak_freq_agree"] > 0.6
    w = max(i.width for i in imgs)
    sheet = Image.new("L", (w, sum(i.height for i in imgs) + 4 * len(imgs)), 40)
    y = 0
    for i in imgs:
        sheet.paste(i, (0, y))
        y += i.height + 4
    sheet.save(os.path.join(IMG, "sound_demo_spectrogram.png"))
    json.dump(res, open(os.path.join(ROOT, "build", "reports", "audio_compare.json"), "w"), indent=1)
    print(res)
