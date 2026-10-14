# Mapa da HRAM (Fase 0)

O código SM83 gerado mantém o estado da CPU ARM7 (modo Thumb) na HRAM, acessível com
`ldh` (rápido, 3 M-cycles) e também via `[hl]` com `h=$FF`.

| Endereço        | Conteúdo                                   |
|-----------------|--------------------------------------------|
| `$FF80-$FFBF`   | R0..R15, 4 bytes cada, little-endian (Rn em `$FF80+4n`) |
| `$FFC0`         | flag N (0/1)                               |
| `$FFC1`         | flag Z (0/1)                               |
| `$FFC2`         | flag C (0/1) — semântica ARM (C=1 = sem empréstimo na subtração) |
| `$FFC3`         | flag V (0/1)                               |
| `$FFC4-$FFC7`   | T0: temporário/resultado de 32 bits        |
| `$FFC8-$FFCB`   | T1: temporário (imediatos, endereços)      |
| `$FFCC-$FFCF`   | T2: temporário (multiplicação)             |
| `$FFD0`         | START: harness escreve 1 para executar     |
| `$FFD1`         | DONE: runtime escreve 1 ao terminar (marcador de fim) |
| `$FFD2-$FFD3`   | contador de overflows do timer (medição de ciclos) |
| `$FFD4`         | TIMA amostrado no fim                      |

R15 (PC) não é materializado: o fluxo de controle é traduzido estaticamente.
R14 (LR) recebe o endereço de retorno ARM em `BL`, mas o retorno real usa a pilha SM83
(`call`/`ret`).

## Memória ARM
Todo acesso LDR/STR/PUSH/POP é mapeado para WRAM: `$C000 | (addr & $1FFF)`.
Na Fase 0 só a pilha (SP inicial `0x03001F00` → `$DF00`) é usada pelos kernels.
A pilha nativa SM83 começa em `$D000`.

## Medição de ciclos
Timer em 262144 Hz (TAC=5, 1 tick = 4 M-cycles); a ISR conta overflows de TIMA.
Custo ≈ (TCNT·256 + TIMA)·4 M-cycles.
