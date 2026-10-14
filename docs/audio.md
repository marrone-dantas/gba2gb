# Audio: GBA PSG / DirectSound → DMG APU (Phase 4.3)

`runtime/gb_audio_shims.asm` is included by `gb_hal_shims.asm`. The interceptor
sends every constant-address store to 0x04000060-0x0400009F to `HAL_SND_WR`, along
with the GBA offset and the store width. Every byte is then mapped on its own, so
8-, 16- and 32-bit stores all behave as they do on the GBA. Every DMG register write
of the mapping goes through `SndOut`, which the tests hook. Reads of sound registers
return 0 (no status readback).

## Register map
The GBA PSG descends from the DMG APU: most fields have the same bit positions, but
the registers sit at different addresses, with gaps and with 16-bit grouping. The
mixer registers have no 1:1 equivalent.

| GBA register (offset) | byte | DMG target | remapping |
|---|---|---|---|
| SOUND1CNT_L (60) | lo | NR10 | sweep shift 0-2, direction 3, time 4-6: same; bit 7 masked |
| | hi | — | unused |
| SOUND1CNT_H (62) | lo | NR11 | length 0-5, duty 6-7: same |
| | hi | NR12 | envelope step 0-2, direction 3, initial volume 4-7: same |
| SOUND1CNT_X (64) | lo | NR13 | frequency 0-7 |
| | hi | NR14 | freq 8-10 → 0-2, length enable 14 → 6, init 15 → 7; bits 3-5 masked |
| SOUND2CNT_L (68) | lo / hi | NR21 / NR22 | as NR11 / NR12 (bytes 6A-6B unused) |
| SOUND2CNT_H (6C) | lo / hi | NR23 / NR24 | as NR13 / NR14 |
| SOUND3CNT_L (70) | lo | NR30 + wave bank | bit 7 (DAC) → NR30 bit 7. Bit 6 (played bank) switches the DMG wave RAM to the shadow of that bank: DAC off, copy 16 bytes, DAC on, retrigger. Bit 5 (64-digit mode) is not supported: only the selected bank plays. |
| SOUND3CNT_H (72) | lo | NR31 | length 0-7 |
| | hi | NR32 | volume bits 13-14 → NR32 bits 5-6 (same codes); force-75 % (bit 15) → 100 % |
| SOUND3CNT_X (74) | lo / hi | NR33 / NR34 | as NR13 / NR14 |
| SOUND4CNT_L (78) | lo | NR41 | length 0-5 (bits 6-7 masked) |
| | hi | NR42 | envelope: same |
| SOUND4CNT_H (7C) | lo | NR43 | ratio 0-2, width 3, shift 4-7: same |
| | hi | NR44 | length enable 14 → 6, init 15 → 7 |
| SOUNDCNT_L (80) | lo | NR50 | right/left master volume 0-2 / 4-6, each scaled by the PSG ratio of SOUNDCNT_H: v' = max((v+1)·r − 1, 0), with r = ¼, ½, 1 |
| | hi | NR51 | channel enables R 0-3 / L 4-7: same layout. Channel 3's bits follow DMA A routing while a DirectSound SFX plays. |
| SOUNDCNT_H (82) | lo | NR50 (recomputed) | PSG ratio bits 0-1. DMA A volume (bit 2) sets the SFX volume (NR32 100 % / 50 %). DMA B is ignored. |
| | hi | NR51 (recomputed) | DMA A right/left (bits 8-9) route the SFX on channel 3. Timer select, FIFO reset and DMA B are ignored. |
| SOUNDCNT_X (84) | lo | NR52 | master enable bit 7. Status bits are read-only on both. |
| 86-8F | — | — | ignored (SOUNDBIAS etc.) |
| WAVE_RAM (90-9F) | | shadow `wWave` | the CPU writes the bank that is **not** being played, as on the GBA; that bank reaches the DMG wave RAM when the program selects it for playback |

At reset the HAL turns the APU off (NR52 = 0), matching SOUNDCNT_X = 0 on the GBA.
The ordering effects are reproduced: for example, SOUNDCNT_L written before
SOUNDCNT_H first gives NR50 at 25 % (ratio 0).

## DirectSound SFX
* **Offline** (`tools/audio/dsound_convert.py`, run by `build(..., hal=True)` when
  the program writes DMA1SAD): a GBA reference run logs the DMA1SAD values and the
  TM0CNT_L reload. The length of each SFX comes from the ELF symbol containing that
  address. Each SFX is resampled to 8192 Hz, quantised to 4 bits (8 = silence), and
  packed high nibble first into 32-sample / 16-byte chunks in MBC5 bank 16 or later.
  `SfxTab` holds ARM address → bank / pointer / chunk count.
* **Run time**:
  * `HAL_WR_DMA1SAD` latches the source address.
  * When both DMA1 (DMA1CNT_H bit 15) and timer 0 (TM0CNT_H bit 7) are on, the HAL
    looks the source up in `SfxTab` and borrows channel 3. It sets NR32 from the DMA A
    volume, the period to x = 1792 (32 samples per period at 8192 Hz), and the timer
    to 4096 Hz / 16 = **256 Hz = 8192 / 32**.
  * Each timer interrupt (`SfxTimerISR` → `SfxChunk`) turns the DAC off, writes 16
    bytes of wave RAM, turns the DAC on and retriggers.
  * The SFX ends when the chunks run out or when the program stops DMA1 or timer 0.
    Channel 3 then gets its wave bank and register shadows back. PSG channel-3 writes
    made during the SFX were kept in the shadows.
* **Measured in PyBoy**: the timer ISR takes **199 M-cycles** per chunk, and 318 M on
  the final chunk, which also restores channel 3. At 256 interrupts per second that is
  **4.9 % of the CPU while an SFX plays** (7.8 % if every call cost the peak).
  `HAL_SND_WR` costs 58-276 M per store; the upper end is a SOUND3CNT_L bank switch
  that copies wave RAM.

## Demo and comparison
* `tests/demos/sound_demo.c` is original Thumb code: a lead on channel 1 (with sweep
  notes), bass on channel 2, two bank-switched wave-RAM waveforms on channel 3, a
  noise hi-hat on channel 4, and an 8192 Hz "zap" SFX (DirectSound A, DMA1 + timer
  0) at frames 90 and 210.
* `tests/test_audio.py` checks three things:
  1. The DMG register writes equal the `tools/audio/psg_map.py` model of the GBA
     reference's write log, per register, in order.
  2. Every streamed chunk equals the offline conversion, byte for byte.
  3. PyBoy's audio is compared with a **real GBA recording of the same ROM made by
     mGBA** (`tools/gba_capture/mgba_capture`, new `audio FILE` command; the test is
     skipped when that binary is missing). Both are aligned on their first non-silent
     sample; the PyBoy boot-ROM chime is skipped.

Result: log-spectrogram correlation **0.79**; the dominant frequency agrees within
3 % on **78 %** of loud frames.

Files:
* `docs/audio/sound_demo_gb_dmg.wav` (PyBoy DMG, 48 kHz)
* `docs/audio/sound_demo_gba_mgba.wav` (mGBA, resampled to 48 kHz)
* `docs/img/sound_demo_spectrogram.png` (top: GBA, bottom: DMG)

## Limits
* DirectSound is reduced to 4 bits at 8192 Hz on channel 3. While an SFX plays it
  takes channel 3 away from the PSG.
* Every chunk retriggers channel 3 after a DAC-off write, as DMG wave RAM requires,
  so there is a small click every 3.9 ms. The SFX is quieter than on the GBA
  (4-bit DAC, no 8-bit mix).
* Only DMA1 → FIFO A with timer 0 is recognised. DMA B, FIFO B, timer 1 and
  CPU-driven FIFO writes are not. The SFX data and rate are frozen at bake time (the
  reference run must reach every SFX start within 400 frames). An unknown source
  address plays nothing.
* The 64-digit wave mode is not supported. A wave bank switch retriggers channel 3,
  which resets its phase.
* Sound register reads return 0.
