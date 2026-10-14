# Soft-float lockstep kernels: Thumb, linked against the real libgcc helpers.
CC=arm-none-eabi-gcc
CFLAGS=-mcpu=arm7tdmi -mthumb -O2 -ffreestanding -nostdlib -fno-builtin -fno-optimize-sibling-calls -fno-pic
OUT=../../build/softfloat
SRC=$(wildcard s_*.c)
ELF=$(SRC:%.c=$(OUT)/%.elf)
all: $(ELF)
$(OUT)/%.elf: %.c
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) -Wl,-Ttext=0x08000000 -Wl,-e,f -o $@ $< -lgcc
