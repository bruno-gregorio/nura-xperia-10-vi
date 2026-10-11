// SPDX-License-Identifier: GPL-2.0
/*
 * qrtr-lookup: list the QRTR services the remote processors have announced,
 * and optionally keep listening for new ones.
 *
 *   qrtr-lookup [seconds]
 *
 * Sends the kernel's QRTR name service one NEW_LOOKUP with service and
 * instance zero, which matches everything. It answers with one NEW_SERVER
 * per service it knows, then an all-zero NEW_SERVER that ends the list; the
 * lookup stays registered, so a service announced later arrives as another
 * NEW_SERVER, and a removed one as DEL_SERVER. With no argument it prints
 * the list and stops at its end; with one, it keeps printing for that many
 * seconds after the end. Each line is
 *
 *   qrtr: service S version V instance I node N port P
 *
 * where the name service's instance field is split the way qrtr-lookup in
 * linux-msm/qrtr splits it: version in the low byte, instance above it.
 *
 * It exists for the initramfs shell, to see whether the ADSP's sensor
 * service (400, SNS) registers. Built like fastrpc-probe.c, against the
 * kernel's nolibc, which has no socket calls, so they are raw syscalls:
 *
 *   aarch64-linux-gnu-gcc -Os -static -nostdlib -fno-asynchronous-unwind-tables \
 *       -Wl,-z,max-page-size=4096 \
 *       -include out/linux/tools/include/nolibc/nolibc.h \
 *       -o out/tools/qrtr-lookup scripts/qrtr-lookup.c -lgcc
 */

#define AF_QIPCRTR		42
#define SOCK_DGRAM		2
#define QRTR_PORT_CTRL		0xfffffffeu
#define QRTR_TYPE_NEW_SERVER	4
#define QRTR_TYPE_DEL_SERVER	5
#define QRTR_TYPE_NEW_LOOKUP	10

/* include/uapi/linux/qrtr.h */
struct sockaddr_qrtr {
	unsigned short sq_family;
	unsigned int sq_node;
	unsigned int sq_port;
};

struct qrtr_ctrl_pkt {
	unsigned int cmd;
	unsigned int service;
	unsigned int instance;
	unsigned int node;
	unsigned int port;
} __attribute__((packed));

static long sys_socket(int domain, int type, int proto)
{
	return my_syscall3(__NR_socket, domain, type, proto);
}

static long sys_getsockname(int fd, void *addr, unsigned int *len)
{
	return my_syscall3(__NR_getsockname, fd, addr, len);
}

static long sys_sendto(int fd, const void *buf, unsigned long len,
		       const void *addr, unsigned int alen)
{
	return my_syscall6(__NR_sendto, fd, buf, len, 0, addr, alen);
}

static long sys_recvfrom(int fd, void *buf, unsigned long len)
{
	return my_syscall6(__NR_recvfrom, fd, buf, len, 0, 0, 0);
}

static int number(const char *s)
{
	int n = 0;

	while (*s >= '0' && *s <= '9')
		n = n * 10 + (*s++ - '0');
	return n;
}

int main(int argc, char **argv)
{
	struct sockaddr_qrtr sq;
	struct qrtr_ctrl_pkt pkt;
	struct pollfd pfd;
	unsigned int len = sizeof(sq);
	int linger = argc > 1 ? number(argv[1]) : -1;
	int ended = 0, n = 0;
	long fd, r;

	fd = sys_socket(AF_QIPCRTR, SOCK_DGRAM, 0);
	if (fd < 0) {
		printf("qrtr-lookup: socket: errno %ld\n", -fd);
		return 1;
	}
	r = sys_getsockname(fd, &sq, &len);
	if (r < 0) {
		printf("qrtr-lookup: getsockname: errno %ld\n", -r);
		return 1;
	}

	memset(&pkt, 0, sizeof(pkt));
	pkt.cmd = QRTR_TYPE_NEW_LOOKUP;
	sq.sq_port = QRTR_PORT_CTRL;
	r = sys_sendto(fd, &pkt, sizeof(pkt), &sq, sizeof(sq));
	if (r < 0) {
		printf("qrtr-lookup: lookup: errno %ld\n", -r);
		return 1;
	}

	pfd.fd = fd;
	pfd.events = POLLIN;
	for (;;) {
		/* Ten seconds for the list itself, then the lingering time. */
		r = poll(&pfd, 1, ended ? linger * 1000 : 10000);
		if (r < 0) {
			printf("qrtr-lookup: poll: errno %d\n", errno);
			return 1;
		}
		if (r == 0) {
			if (!ended)
				printf("qrtr-lookup: the list never ended\n");
			break;
		}
		r = sys_recvfrom(fd, &pkt, sizeof(pkt));
		if (r < 0) {
			printf("qrtr-lookup: recv: errno %ld\n", -r);
			return 1;
		}
		if (r < (long)sizeof(pkt))
			continue;
		if (pkt.cmd == QRTR_TYPE_NEW_SERVER && !pkt.service &&
		    !pkt.instance && !pkt.node && !pkt.port) {
			printf("qrtr-lookup: %d services\n", n);
			ended = 1;
			if (linger <= 0)
				break;
			continue;
		}
		if (pkt.cmd != QRTR_TYPE_NEW_SERVER &&
		    pkt.cmd != QRTR_TYPE_DEL_SERVER)
			continue;
		if (pkt.cmd == QRTR_TYPE_NEW_SERVER)
			n++;
		printf("qrtr: %sservice %u version %u instance %u node %u port %u\n",
		       pkt.cmd == QRTR_TYPE_DEL_SERVER ? "gone: " : "",
		       pkt.service, pkt.instance & 0xff, pkt.instance >> 8,
		       pkt.node, pkt.port);
	}
	return 0;
}
