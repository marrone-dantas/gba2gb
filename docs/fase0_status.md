# Fase 0 — status

**Resultado: 20/20 kernels passando**, 1000 sementes por kernel (4 fixas de borda + 996
aleatórias determinísticas por kernel), R0 comparado bit a bit (Unicorn × PyBoy, HRAM
`$FF80-$FF83`). Execução completa: ~7 s (`.venv/bin/python -m pytest tests/`).
`LOCKSTEP_SEEDS=N` reduz o número de sementes.

## Custo medido (M-cycles SM83 por chamada, média de 1000 sementes)
Medido pelo timer do runtime (resolução de 4 M-cycles; inclui ~overhead da ISR).
Ver `build/ciclos.csv` após rodar o teste.

| kernel | M-cycles | kernel | M-cycles |
|---|---|---|---|
| k01_fibonacci | 13452 | k11_shifts_var | 4705 |
| k02_crc16 | 163467 | k12_clamp_sat | 7155 |
| k03_inimigo_fsm | 73439 | k13_abs_minmax | 2281 |
| k04_aabb | 2646 | k14_isqrt | 13336 |
| k05_ordenacao | 28253 | k15_bitrev | 31231 |
| k06_bubble_u8 | 20834 | k16_carry64 | 1844 |
| k07_popcount | 10249 | k17_chamadas | 8748 |
| k08_gcd | 18484 | k18_bytes_half | 11409 |
| k09_mul_acc | 7618 | k19_tilemap_hash | 248660 |
| k10_xorshift | 15880 | k20_fixed_point | 43757 |

Média geral ≈ 38 000 M-cycles (≈ 2,2 quadros de 17 556 M-cycles).

## Limitações conhecidas
- Todo `BX` e `POP {..,PC}` é tratado como retorno (`ret` SM83); não há saltos indiretos,
  interworking ARM, `MOV PC` nem tabelas de salto (kernels compilados com `-fno-jump-tables`).
- Memória ARM mapeada em janela de 8 KiB de WRAM (`$C000 | addr&$1FFF`); só pilha/locais.
  Sem globais/.data/.rodata além de literal pools (resolvidos em tempo de tradução).
  Acessos desalinhados e travessia da janela de 8 KiB não são tratados.
- Sem divisão/libgcc (`__aeabi_*`), sem SWI, sem modo ARM de 32 bits.
- Flag C após `MULS` não é modelada (imprevisível no ARMv4; só N/Z).
- Deslocamentos e MUL usam rotinas iterativas (lentas: MUL ~32 iterações);
  cada op de 32 bits é inline byte a byte — sem alocação de registradores nem poda de
  largura (planejado para a Fase 2).
- O teste compara apenas R0; flags e demais registradores não são verificados.
