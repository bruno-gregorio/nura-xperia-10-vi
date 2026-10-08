// SPDX-License-Identifier: GPL-2.0
/*
 * regdump: print a range of physical registers as 32-bit words, read
 * through /dev/mem.
 *
 *   regdump 0x1d87000 0x1000
 *
 * Each line is "address: word word word word". Every word is a single
 * 32-bit load, which is what Qualcomm's register blocks expect, and the
 * mapping is read-only: this looks and never touches.
 *
 * It exists for the initramfs shell, whose busybox has no devmem. Built
 * against the kernel's nolibc it is a few kilobytes, small enough for
 * scripts/tsh.py to push over telnet (@push in a command file):
 *
 *   aarch64-linux-gnu-gcc -Os -static -nostdlib -fno-asynchronous-unwind-tables \
 *       -Wl,-z,max-page-size=4096 \
 *       -include out/linux/tools/include/nolibc/nolibc.h \
 *       -o out/tools/regdump scripts/regdump.c -lgcc
 *
 * Reading a block whose clock or power domain is off can hang the bus
 * rather than fault, so check clk_summary and pm_genpd_summary first.
 */

#ifndef REGDUMP_DEV
#define REGDUMP_DEV "/dev/mem"
#endif

static void hex(char *p, unsigned long v, int digits)
{
	while (digits--) {
		p[digits] = "0123456789abcdef"[v & 0xf];
		v >>= 4;
	}
}

int main(int argc, char **argv)
{
	unsigned long addr, len, base, off, i;
	volatile unsigned int *reg;
	char line[10 + 4 * 9 + 1];
	char *end;
	void *map;
	int fd;

	if (argc != 3) {
		fprintf(stderr, "usage: regdump ADDR LEN\n");
		return 2;
	}
	addr = strtoul(argv[1], &end, 0) & ~3UL;
	if (*end) {
		fprintf(stderr, "regdump: bad address %s\n", argv[1]);
		return 2;
	}
	len = (strtoul(argv[2], &end, 0) + 3) & ~3UL;
	if (*end || !len) {
		fprintf(stderr, "regdump: bad length %s\n", argv[2]);
		return 2;
	}

	base = addr & ~4095UL;
	off = addr - base;
	fd = open(REGDUMP_DEV, O_RDONLY | O_SYNC);
	if (fd < 0) {
		perror("regdump: " REGDUMP_DEV);
		return 1;
	}
	map = mmap(NULL, off + len, PROT_READ, MAP_SHARED, fd, base);
	if (map == MAP_FAILED) {
		perror("regdump: mmap");
		return 1;
	}
	reg = (volatile unsigned int *)((char *)map + off);

	for (i = 0; i < len / 4; i++) {
		int col = i % 4;

		if (col == 0) {
			hex(line, addr + i * 4, 8);
			line[8] = ':';
		}
		line[9 + col * 9] = ' ';
		hex(line + 10 + col * 9, reg[i], 8);
		if (col == 3 || i == len / 4 - 1) {
			int n = 10 + col * 9 + 8;

			line[n] = '\n';
			write(1, line, n + 1);
		}
	}
	return 0;
}
