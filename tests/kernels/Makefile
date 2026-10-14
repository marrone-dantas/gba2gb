# Compila os micro-kernels para Thumb (ARM7TDMI), sem libc/libgcc.
CC=arm-none-eabi-gcc
CFLAGS=-mcpu=arm7tdmi -mthumb -O2 -ffreestanding -nostdlib -fno-builtin -fno-jump-tables -fno-pic
OUT=../../build/kernels
SRC=$(wildcard k*.c)
ELF=$(SRC:%.c=$(OUT)/%.elf)
all: $(ELF)
$(OUT)/%.elf: %.c
	@mkdir -p $(OUT)
	$(CC) $(CFLAGS) -Wl,-Ttext=0x08000000 -Wl,-e,f -o $@ $<
clean:
	rm -rf $(OUT)
