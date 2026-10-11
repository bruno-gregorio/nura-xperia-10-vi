// SPDX-License-Identifier: GPL-2.0
/*
 * fastrpc-probe: make the smallest calls a FastRPC device has, and say
 * whether the DSP answered.
 *
 *   fastrpc-probe node [step...]
 *
 * node is a FastRPC device, such as /dev/fastrpc-adsp. The steps run in
 * order on one open of it, "info attach" unless told otherwise:
 *   - info: FASTRPC_IOCTL_GET_DSP_INFO for attributes 1 to 15. The first
 *     query is a call into the DSP's utilities handle, which needs no
 *     process on the DSP; the kernel caches the answer, so the rest are
 *     local. A DSP that does not know the call still answers, and the
 *     ioctl then fails with EOPNOTSUPP.
 *   - attach: FASTRPC_IOCTL_INIT_ATTACH, the call that attaches to the
 *     DSP's root protection domain.
 *   - sns: FASTRPC_IOCTL_INIT_ATTACH_SNS, the same for the sensors
 *     domain. Nothing here serves the files that domain asks for after,
 *     which is hexagonrpcd's job, so this is a check that it attaches and
 *     no more.
 * Closing the device releases whatever was attached.
 *
 * It exists for the initramfs shell. Built like msm-submit.c, against the
 * kernel's nolibc:
 *
 *   aarch64-linux-gnu-gcc -Os -static -nostdlib -fno-asynchronous-unwind-tables \
 *       -Wl,-z,max-page-size=4096 \
 *       -include out/linux/tools/include/nolibc/nolibc.h \
 *       -o out/tools/fastrpc-probe scripts/fastrpc-probe.c -lgcc
 */

/* include/uapi/misc/fastrpc.h */
struct fastrpc_ioctl_capability {
	unsigned int unused;
	unsigned int attribute_id;
	unsigned int capability;
	unsigned int reserved[4];
};

#define FASTRPC_IOCTL_INIT_ATTACH	(('R' << 8) | 4)
#define FASTRPC_IOCTL_INIT_ATTACH_SNS	(('R' << 8) | 8)
#define FASTRPC_IOCTL_GET_DSP_INFO	(0xc0000000 | \
	(sizeof(struct fastrpc_ioctl_capability) << 16) | ('R' << 8) | 13)

static int same(const char *a, const char *b)
{
	while (*a && *a == *b) {
		a++;
		b++;
	}
	return *a == *b;
}

static int info(int fd, const char *node)
{
	struct fastrpc_ioctl_capability cap;
	unsigned int id;

	for (id = 1; id < 16; id++) {
		cap = (struct fastrpc_ioctl_capability){ .attribute_id = id };
		if (ioctl(fd, FASTRPC_IOCTL_GET_DSP_INFO, &cap) < 0) {
			printf("fastrpc-probe: %s: info %u: errno %d\n",
			       node, id, errno);
			return 1;
		}
		printf("fastrpc-probe: %s: attribute %u = 0x%x\n",
		       node, id, cap.capability);
	}
	return 0;
}

static int attach(int fd, const char *node, unsigned long req,
		  const char *what)
{
	if (ioctl(fd, req, 0) < 0) {
		printf("fastrpc-probe: %s: %s: errno %d\n", node, what, errno);
		return 1;
	}
	printf("fastrpc-probe: %s: %s: done\n", node, what);
	return 0;
}

int main(int argc, char **argv)
{
	static char *steps[] = { "info", "attach" };
	char **step = argc > 2 ? argv + 2 : steps;
	int nsteps = argc > 2 ? argc - 2 : 2;
	const char *node;
	int fd, i, failed = 0;

	if (argc < 2) {
		printf("usage: fastrpc-probe node [info|attach|sns]...\n");
		return 2;
	}
	node = argv[1];
	fd = open(node, O_RDWR);
	if (fd < 0) {
		printf("fastrpc-probe: open %s: errno %d\n", node, errno);
		return 1;
	}
	for (i = 0; i < nsteps; i++) {
		if (same(step[i], "info"))
			failed += info(fd, node);
		else if (same(step[i], "attach"))
			failed += attach(fd, node, FASTRPC_IOCTL_INIT_ATTACH,
					 "attach");
		else if (same(step[i], "sns"))
			failed += attach(fd, node,
					 FASTRPC_IOCTL_INIT_ATTACH_SNS,
					 "attach sns");
		else
			printf("fastrpc-probe: unknown step %s\n", step[i]);
	}
	close(fd);
	printf("fastrpc-probe: %s: %d of %d steps failed\n", node, failed,
	       nsteps);
	return failed ? 1 : 0;
}
