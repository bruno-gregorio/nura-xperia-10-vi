// SPDX-License-Identifier: GPL-2.0
/*
 * vblank: wait for a CRTC's vblanks with DRM_IOCTL_WAIT_VBLANK and print
 * each one's sequence number and timestamp.
 *
 *   vblank [count [crtc]]
 *
 * On a command-mode DSI panel the DPU's vblank is the tear check's read
 * pointer interrupt, and the read pointer is reset by the vsync source: the
 * panel's TE pin unless the DSI endpoint names another. So the spacing of
 * the timestamps is the panel's TE period, about 16.7 ms at 60 Hz. With no
 * TE the counter runs free and wraps at the tear check's sync height, which
 * mainline sets to 0xfff0 lines, so the spacing becomes hundreds of
 * milliseconds; with no read pointer interrupt at all, each wait times out
 * after three seconds, and the first that does ends the run.
 *
 * It exists for the initramfs shell, which has no DRM tools. Built like
 * regdump.c, against the kernel's nolibc:
 *
 *   aarch64-linux-gnu-gcc -Os -static -nostdlib -fno-asynchronous-unwind-tables \
 *       -Wl,-z,max-page-size=4096 \
 *       -include out/linux/tools/include/nolibc/nolibc.h \
 *       -o out/tools/vblank scripts/vblank.c -lgcc
 *
 * It only waits and commits nothing. Opening the card makes it DRM master
 * while it runs, if nothing else is, which holds off fbdev's commits until
 * it exits; fbdev then restores its mode.
 */

#define DRM_VBLANK_RELATIVE		0x00000001
#define DRM_VBLANK_HIGH_CRTC_SHIFT	1
#define DRM_VBLANK_HIGH_CRTC_MASK	0x0000003e

/* include/uapi/drm/drm.h, union drm_wait_vblank, as laid out on arm64 */
union wait_vblank {
	struct {
		unsigned int type;
		unsigned int sequence;
		unsigned long signal;
	} request;
	struct {
		unsigned int type;
		unsigned int sequence;
		long tval_sec;
		long tval_usec;
	} reply;
};

/* _IOWR('d', 0x3a, union drm_wait_vblank) */
#define DRM_IOCTL_WAIT_VBLANK	(0xc0000000 | (sizeof(union wait_vblank) << 16) | ('d' << 8) | 0x3a)

static unsigned long number(const char *s)
{
	unsigned long v = 0;

	while (*s >= '0' && *s <= '9')
		v = v * 10 + *s++ - '0';
	return v;
}

int main(int argc, char **argv)
{
	unsigned long count = argc > 1 ? number(argv[1]) : 60;
	unsigned long crtc = argc > 2 ? number(argv[2]) : 0;
	long first_us = 0, last_us = 0;
	unsigned long i;
	int fd;

	fd = open("/dev/dri/card0", O_RDWR);
	if (fd < 0) {
		printf("vblank: open /dev/dri/card0: errno %d\n", errno);
		return 1;
	}

	for (i = 0; i < count; i++) {
		union wait_vblank vbl = { 0 };
		long us;

		vbl.request.type = DRM_VBLANK_RELATIVE |
			((crtc << DRM_VBLANK_HIGH_CRTC_SHIFT) & DRM_VBLANK_HIGH_CRTC_MASK);
		vbl.request.sequence = 1;
		if (ioctl(fd, DRM_IOCTL_WAIT_VBLANK, &vbl) < 0) {
			printf("vblank %lu: errno %d\n", i, errno);
			return 1;
		}
		us = vbl.reply.tval_sec * 1000000 + vbl.reply.tval_usec;
		if (i == 0)
			first_us = us;
		printf("vblank %lu: seq %u at %ld.%06ld, +%ld us\n", i,
		       vbl.reply.sequence, vbl.reply.tval_sec, vbl.reply.tval_usec,
		       i ? us - last_us : 0);
		last_us = us;
	}
	if (count > 1)
		printf("vblank: %lu in %ld us, %ld us apart\n", count,
		       last_us - first_us, (last_us - first_us) / (long)(count - 1));
	return 0;
}
