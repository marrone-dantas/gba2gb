# Phase 2 demos: Thumb-only C, ARM crt0, no libc/libtonc.
CC=arm-none-eabi-gcc
CFLAGS=-mcpu=arm7tdmi -mthumb -O2 -ffreestanding -nostdlib -fno-builtin -fno-jump-tables -fno-pic -fno-tree-loop-distribute-patterns
OUT=../../build/demos
DEMOS=obj_demo key_demo brin_demo oam_stress input_test affine_demo sound_demo spill_demo
all: $(DEMOS:%=$(OUT)/%.elf)
assets.h: ../../tools/hal/make_assets.py
	python3 ../../tools/hal/make_assets.py > $@
$(OUT)/%.elf: %.c gba.h assets.h crt0.s gba.ld
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) -T gba.ld -o $@ crt0.s $<
	arm-none-eabi-objcopy -O binary $@ $(OUT)/$*.gba
clean:
	rm -rf $(OUT)
