# Phase 2 demos: Thumb-only C, ARM crt0, no libc/libtonc.
CC=arm-none-eabi-gcc
CFLAGS=-mcpu=arm7tdmi -mthumb -O2 -ffreestanding -nostdlib -fno-builtin -fno-jump-tables -fno-pic -fno-tree-loop-distribute-patterns
OUT=../../build/demos
DEMOS=obj_demo key_demo brin_demo oam_stress input_test affine_demo sound_demo spill_demo ewram_demo
all: $(DEMOS:%=$(OUT)/%.elf)
assets.h: ../../tools/hal/make_assets.py
	python3 ../../tools/hal/make_assets.py > $@
$(OUT)/%.elf: %.c gba.h assets.h crt0.s gba.ld
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) -T gba.ld -o $@ crt0.s $<
	arm-none-eabi-objcopy -O binary $@ $(OUT)/$*.gba
# Phase 5 A2: EWRAM objects placed into MBC5 SRAM banks by the allocator
$(OUT)/ewram_demo.elf: ewram_demo.c gba.h crt0.s gba.ld ../../tools/sram/ewram_alloc.py
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) -c -o $(OUT)/ewram_demo.o ewram_demo.c
	python3 ../../tools/sram/ewram_alloc.py $(OUT)/ewram_demo.o --base gba.ld -o $(OUT)/ewram_demo_ewram.ld --report $(OUT)/ewram_demo_ewram.json
	$(CC) $(CFLAGS) -T $(OUT)/ewram_demo_ewram.ld -o $@ crt0.s $(OUT)/ewram_demo.o
	arm-none-eabi-objcopy -O binary $@ $(OUT)/ewram_demo.gba
clean:
	rm -rf $(OUT)
