// SPDX-License-Identifier: GPL-2.0
/*
 * hcimon: print the HCI commands and events of every Bluetooth controller,
 * read from the kernel's monitor channel, the one btmon reads.
 *
 *   hcimon [packets [bytes]]
 *
 * Each command or event is one line: a sequence number, the direction, the
 * controller index, the length and the first bytes in hex, 24 unless told
 * otherwise, at most 63. It stops after the given number of packets, 200 by default,
 * or when killed. The point is the bytes the chip sends while hci_qca sets
 * it up, before any userspace exists to run btmon.
 *
 * It leaves out what can identify the phone. The monitor's index packets,
 * which carry the controller's address, print as their type alone, and so
 * does the reply to Read BD_ADDR, whose payload is that address.
 *
 * It exists for the initramfs shell. Built like regdump.c, against the
 * kernel's nolibc:
 *
 *   aarch64-linux-gnu-gcc -Os -static -nostdlib -fno-asynchronous-unwind-tables \
 *       -Wl,-z,max-page-size=4096 \
 *       -include out/linux/tools/include/nolibc/nolibc.h \
 *       -o out/tools/hcimon scripts/hcimon.c -lgcc
 *
 * Opening the channel needs CAP_NET_RAW and bluetooth.ko loaded first.
 */

#define AF_BLUETOOTH		31
#define BTPROTO_HCI		1
#define SOCK_RAW		3
#define HCI_DEV_NONE		0xffff
#define HCI_CHANNEL_MONITOR	2

#define HCI_MON_COMMAND_PKT	2
#define HCI_MON_EVENT_PKT	3

#define HCI_EV_CMD_COMPLETE	0x0e
#define HCI_OP_READ_BD_ADDR	0x1009

/* include/net/bluetooth/hci_sock.h */
struct sockaddr_hci {
	unsigned short hci_family;
	unsigned short hci_dev;
	unsigned short hci_channel;
};

/* include/net/bluetooth/hci_mon.h, all little-endian */
struct hci_mon_hdr {
	unsigned short opcode;
	unsigned short index;
	unsigned short len;
} __attribute__((packed));

/* nolibc's printf pads with spaces, never zeros */
static void hex2(char *p, unsigned char v)
{
	p[0] = ' ';
	p[1] = "0123456789abcdef"[v >> 4];
	p[2] = "0123456789abcdef"[v & 0xf];
}

static unsigned long number(const char *s)
{
	unsigned long v = 0;

	while (*s >= '0' && *s <= '9')
		v = v * 10 + *s++ - '0';
	return v;
}

int main(int argc, char **argv)
{
	unsigned long packets = argc > 1 ? number(argv[1]) : 200;
	unsigned long bytes = argc > 2 ? number(argv[2]) : 24;
	struct sockaddr_hci addr = {
		.hci_family = AF_BLUETOOTH,
		.hci_dev = HCI_DEV_NONE,
		.hci_channel = HCI_CHANNEL_MONITOR,
	};
	static unsigned char buf[sizeof(struct hci_mon_hdr) + 1024 + 4];
	unsigned long seq;
	long fd, ret;

	if (bytes > 63)
		bytes = 63;
	fd = my_syscall3(__NR_socket, AF_BLUETOOTH, SOCK_RAW, BTPROTO_HCI);
	if (fd < 0) {
		printf("hcimon: socket: errno %ld\n", -fd);
		return 1;
	}
	ret = my_syscall3(__NR_bind, fd, &addr, sizeof(addr));
	if (ret < 0) {
		printf("hcimon: bind: errno %ld\n", -ret);
		return 1;
	}

	for (seq = 0; seq < packets; ) {
		struct hci_mon_hdr *hdr = (struct hci_mon_hdr *)buf;
		unsigned char *data = buf + sizeof(*hdr);
		unsigned long n, i;
		char line[3 * 64];
		long got;

		got = read(fd, buf, sizeof(buf));
		if (got < 0) {
			printf("hcimon: read: errno %d\n", errno);
			return 1;
		}
		if (got < (long)sizeof(*hdr))
			continue;
		n = got - sizeof(*hdr);

		if (hdr->opcode != HCI_MON_COMMAND_PKT &&
		    hdr->opcode != HCI_MON_EVENT_PKT) {
			printf("hcimon %lu: monitor packet %u, hci%u\n", seq++,
			       hdr->opcode, hdr->index);
			continue;
		}
		/* Command Complete: event, length, credits, then the opcode */
		if (hdr->opcode == HCI_MON_EVENT_PKT && n >= 5 &&
		    data[0] == HCI_EV_CMD_COMPLETE &&
		    (data[3] | data[4] << 8) == HCI_OP_READ_BD_ADDR) {
			printf("hcimon %lu: < hci%u %lu: Read BD_ADDR reply, withheld\n",
			       seq++, hdr->index, n);
			continue;
		}

		printf("hcimon %lu: %s hci%u %lu:", seq++,
		       hdr->opcode == HCI_MON_COMMAND_PKT ? ">" : "<",
		       hdr->index, n);
		for (i = 0; i < n && i < bytes; i++)
			hex2(line + 3 * i, data[i]);
		line[3 * i] = 0;
		printf("%s%s\n", line, n > bytes ? " ..." : "");
	}
	return 0;
}
