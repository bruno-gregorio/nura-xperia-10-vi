// SPDX-License-Identifier: GPL-2.0
/*
 * ssc-probe: ask the Snapdragon Sensor Core which sensors it has.
 *
 *   ssc-probe [data_type ...]
 *
 * libssc asks the sensor core for one data type at a time, with "default
 * only" set, and gives up with "No 'accel' sensor available" when the
 * answer is empty. That says nothing about why. This asks for every data
 * type named on the command line, or for a built-in list that covers the
 * framework's own platform sensors as well as the physical and virtual
 * ones, with "default only" cleared. Then it asks each sensor it found for
 * its attributes. Whether the platform sensors (interrupt, async_com_port,
 * timer) are there, and whether a physical sensor exists but is marked
 * unavailable, separates "the drivers never ran" from "the drivers found
 * no hardware".
 *
 * The sensor core is QMI service 400 on QRTR. A request is QMI message
 * 0x20 (Control) with TLV 0x01 holding a protobuf client request, and the
 * answers come back as indications 0x21 and 0x22 (Report Small and Large)
 * with the protobuf in TLV 0x02. The layouts are libqmi's
 * data/qmi-service-ssc.json and the .proto files in libssc's data/. The SUID lookup
 * sensor has the fixed UID abab...ab; its request is message 512 and its
 * answer message 768. An attribute request is message 1, its answer 128.
 *
 * Each line it prints starts with "ssc:". Of the attributes it prints only
 * name, vendor, type, available, version, stream type, dynamic, hardware
 * index and physical sensor, so nothing that identifies the phone, such as
 * a sensor serial number, reaches a log.
 *
 * For the initramfs shell, static:
 *
 *   aarch64-linux-gnu-gcc -O2 -static -Wall -o out/tools/ssc-probe scripts/ssc-probe.c
 */
#include <errno.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#ifndef AF_QIPCRTR
#define AF_QIPCRTR		42
#endif
#define QRTR_PORT_CTRL		0xfffffffeu
#define QRTR_TYPE_NEW_SERVER	4
#define QRTR_TYPE_NEW_LOOKUP	10

#define SSC_SERVICE		400
#define SSC_CONTROL		0x20
#define SSC_REPORT_SMALL	0x21
#define SSC_REPORT_LARGE	0x22

#define MSG_ATTR_REQ		1
#define MSG_ATTR_EVENT		128
#define MSG_SUID_REQ		512
#define MSG_SUID_EVENT		768

#define SUID_LOOKUP		0xababababababababull
#define MAX_UIDS		96

struct sockaddr_qrtr {
	unsigned short sq_family;
	unsigned int sq_node;
	unsigned int sq_port;
};

struct qrtr_ctrl_pkt {
	uint32_t cmd;
	uint32_t service;
	uint32_t instance;
	uint32_t node;
	uint32_t port;
} __attribute__((packed));

static const char *const default_types[] = {
	/* The framework's own sensors. */
	"registry", "remote_proc_state", "interrupt", "async_com_port",
	"timer", "resampler", "data_acquisition_engine", "dae",
	"diag_sensor", "island", "ext_svc", "power",
	/* Physical. */
	"accel", "gyro", "mag", "proximity", "prox", "ambient_light",
	"pressure", "humidity", "hall", "sar", "sensor_temperature",
	"motion_detect", "ultra_violet", "rgb", "ambient_temperature",
	/* Virtual, built on the physical ones. */
	"accel_cal", "gyro_cal", "mag_cal", "amd", "sig_motion", "smd",
	"pedometer", "step_detect", "step_count", "tilt", "tilt_to_wake",
	"device_orient", "game_rv", "rotv", "geomag_rv", "gravity", "psmd",
	"bhh_detect", "fmv", "gyro_rot_matrix", "offbody_detect",
	"wrist_tilt_gesture", "facing", "cmc", "multishake", "basic_gestures",
};

struct uid {
	uint64_t lo, hi;
	char type[48];
};

static struct uid uids[MAX_UIDS];
static int n_uids;
static int sock;
static struct sockaddr_qrtr ssc;
static uint16_t txn;

/* A growable-by-nothing output buffer: everything here is small. */
struct obuf {
	uint8_t d[512];
	size_t n;
};

static void put(struct obuf *b, const void *p, size_t n)
{
	if (b->n >= sizeof(b->d))
		return;
	if (n > sizeof(b->d) - b->n)
		n = sizeof(b->d) - b->n;
	memcpy(b->d + b->n, p, n);
	b->n += n;
}

static void put_varint(struct obuf *b, uint64_t v)
{
	uint8_t c;

	do {
		c = v & 0x7f;
		v >>= 7;
		if (v)
			c |= 0x80;
		put(b, &c, 1);
	} while (v);
}

static void put_key(struct obuf *b, unsigned int field, unsigned int wt)
{
	put_varint(b, (uint64_t)field << 3 | wt);
}

static void put_fixed64(struct obuf *b, unsigned int field, uint64_t v)
{
	uint8_t le[8];
	int i;

	for (i = 0; i < 8; i++)
		le[i] = v >> (8 * i);
	put_key(b, field, 1);
	put(b, le, 8);
}

static void put_fixed32(struct obuf *b, unsigned int field, uint32_t v)
{
	uint8_t le[4];
	int i;

	for (i = 0; i < 4; i++)
		le[i] = v >> (8 * i);
	put_key(b, field, 5);
	put(b, le, 4);
}

static void put_bytes(struct obuf *b, unsigned int field, const void *p, size_t n)
{
	put_key(b, field, 2);
	put_varint(b, n);
	put(b, p, n);
}

static void put_le16(struct obuf *b, uint16_t v)
{
	uint8_t le[2] = { v & 0xff, v >> 8 };

	put(b, le, 2);
}

/* A protobuf reader, enough for the messages here. */
struct pb {
	const uint8_t *p, *end;
};

static int get_varint(struct pb *r, uint64_t *v)
{
	int shift = 0;

	*v = 0;
	while (r->p < r->end && shift < 64) {
		uint8_t c = *r->p++;

		*v |= (uint64_t)(c & 0x7f) << shift;
		if (!(c & 0x80))
			return 0;
		shift += 7;
	}
	return -1;
}

/*
 * The next field: its number and wire type, and either its value (varint
 * and fixed) or its bytes (length-delimited). Returns 0, or -1 at the end
 * or on malformed input.
 */
static int pb_next(struct pb *r, unsigned int *field, unsigned int *wt,
		   uint64_t *v, const uint8_t **d, size_t *n)
{
	uint64_t key, len;
	int i;

	if (r->p >= r->end || get_varint(r, &key))
		return -1;
	*field = key >> 3;
	*wt = key & 7;
	*v = 0;
	*d = NULL;
	*n = 0;
	switch (*wt) {
	case 0:
		return get_varint(r, v);
	case 1:
	case 5:
		len = *wt == 1 ? 8 : 4;
		if ((size_t)(r->end - r->p) < len)
			return -1;
		for (i = 0; i < (int)len; i++)
			*v |= (uint64_t)r->p[i] << (8 * i);
		r->p += len;
		return 0;
	case 2:
		if (get_varint(r, &len) || (size_t)(r->end - r->p) < len)
			return -1;
		*d = r->p;
		*n = len;
		r->p += len;
		return 0;
	default:
		return -1;
	}
}

static double now(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec / 1e9;
}

static int lookup_ssc(void)
{
	struct qrtr_ctrl_pkt pkt;
	struct sockaddr_qrtr sq;
	socklen_t len = sizeof(sq);
	struct pollfd pfd = { .fd = sock, .events = POLLIN };
	double end = now() + 10;

	if (getsockname(sock, (struct sockaddr *)&sq, &len) < 0) {
		printf("ssc: getsockname: %s\n", strerror(errno));
		return -1;
	}
	memset(&pkt, 0, sizeof(pkt));
	pkt.cmd = QRTR_TYPE_NEW_LOOKUP;
	pkt.service = SSC_SERVICE;
	sq.sq_port = QRTR_PORT_CTRL;
	if (sendto(sock, &pkt, sizeof(pkt), 0, (struct sockaddr *)&sq, sizeof(sq)) < 0) {
		printf("ssc: lookup: %s\n", strerror(errno));
		return -1;
	}
	while (now() < end) {
		if (poll(&pfd, 1, 1000) <= 0)
			continue;
		if (recv(sock, &pkt, sizeof(pkt), 0) < (ssize_t)sizeof(pkt))
			continue;
		if (pkt.cmd != QRTR_TYPE_NEW_SERVER)
			continue;
		if (!pkt.service && !pkt.node && !pkt.port)
			break;
		if (pkt.service != SSC_SERVICE)
			continue;
		ssc.sq_family = AF_QIPCRTR;
		ssc.sq_node = pkt.node;
		ssc.sq_port = pkt.port;
		printf("ssc: service 400 at node %u port %u\n", pkt.node, pkt.port);
		return 0;
	}
	printf("ssc: service 400 not found\n");
	return -1;
}

/* One client request, wrapped in QMI Control. */
static int send_request(uint64_t lo, uint64_t hi, uint32_t msg_id,
			const struct obuf *payload)
{
	struct obuf uid = { .n = 0 }, cfg = { .n = 0 }, req = { .n = 0 };
	struct obuf msg = { .n = 0 }, qmi = { .n = 0 };
	uint8_t one = 1;

	put_fixed64(&uid, 1, lo);
	put_fixed64(&uid, 2, hi);
	put_key(&cfg, 1, 0);
	put_varint(&cfg, 1);		/* the apps processor */
	put_key(&cfg, 2, 0);
	put_varint(&cfg, 0);		/* wake it up */
	put_bytes(&req, 2, payload->d, payload->n);

	put_bytes(&msg, 1, uid.d, uid.n);
	put_fixed32(&msg, 2, msg_id);
	put_bytes(&msg, 3, cfg.d, cfg.n);
	put_bytes(&msg, 4, req.d, req.n);

	qmi.d[0] = 0;			/* request */
	qmi.n = 1;
	put_le16(&qmi, ++txn);
	put_le16(&qmi, SSC_CONTROL);
	put_le16(&qmi, 4 + 3 + 2 + msg.n);
	put(&qmi, "\x10", 1);		/* report type: large */
	put_le16(&qmi, 1);
	put(&qmi, &one, 1);
	put(&qmi, "\x01", 1);		/* data */
	put_le16(&qmi, 2 + msg.n);
	put_le16(&qmi, msg.n);
	put(&qmi, msg.d, msg.n);

	if (sendto(sock, qmi.d, qmi.n, 0, (struct sockaddr *)&ssc, sizeof(ssc)) < 0) {
		printf("ssc: send: %s\n", strerror(errno));
		return -1;
	}
	return 0;
}

static int uid_index(uint64_t lo, uint64_t hi)
{
	int i;

	for (i = 0; i < n_uids; i++)
		if (uids[i].lo == lo && uids[i].hi == hi)
			return i;
	return -1;
}

static void print_value(const uint8_t *d, size_t n, int depth);

/* SscAttrValue: a (nested array), s, f, i or b. */
static void print_value(const uint8_t *d, size_t n, int depth)
{
	struct pb r = { d, d + n };
	unsigned int f, wt;
	uint64_t v;
	const uint8_t *b;
	size_t bn;

	while (!pb_next(&r, &f, &wt, &v, &b, &bn)) {
		if (f == 1 && wt == 2 && depth < 3) {
			struct pb a = { b, b + bn };

			printf(" [");
			while (!pb_next(&a, &f, &wt, &v, &b, &bn))
				if (f == 1 && wt == 2)
					print_value(b, bn, depth + 1);
			printf(" ]");
		} else if (f == 2 && wt == 2) {
			printf(" \"%.*s\"", (int)bn, (const char *)b);
		} else if (f == 3 && wt == 5) {
			float fl;
			uint32_t u = v;

			memcpy(&fl, &u, sizeof(fl));
			printf(" %g", fl);
		} else if (f == 4 && wt == 1) {
			printf(" %lld", (long long)v);
		} else if (f == 5 && wt == 0) {
			printf(" %s", v ? "true" : "false");
		}
	}
}

static int attr_wanted(uint64_t id)
{
	switch (id) {
	case 0: case 1: case 2: case 3: case 4:	/* name .. version */
	case 16: case 17: case 18: case 21:	/* stream type .. physical */
		return 1;
	}
	return 0;
}

static void handle_attrs(int idx, const uint8_t *d, size_t n)
{
	struct pb r = { d, d + n };
	unsigned int f, wt;
	uint64_t v;
	const uint8_t *b;
	size_t bn;

	printf("ssc: attrs of %s #%d:", idx >= 0 ? uids[idx].type : "?", idx);
	while (!pb_next(&r, &f, &wt, &v, &b, &bn)) {
		struct pb a;
		uint64_t id = ~0ull;
		const uint8_t *val = NULL;
		size_t valn = 0;

		if (f != 1 || wt != 2)
			continue;
		a = (struct pb){ b, b + bn };
		while (!pb_next(&a, &f, &wt, &v, &b, &bn)) {
			if (f == 1 && wt == 0)
				id = v;
			else if (f == 2 && wt == 2) {
				val = b;
				valn = bn;
			}
		}
		if (!attr_wanted(id) || !val)
			continue;
		printf(" %llu=", (unsigned long long)id);
		/* SscAttrArrayValue: repeated SscAttrValue v = 1 */
		a = (struct pb){ val, val + valn };
		while (!pb_next(&a, &f, &wt, &v, &b, &bn))
			if (f == 1 && wt == 2)
				print_value(b, bn, 0);
	}
	printf("\n");
}

/*
 * One indication: a client response holding the sensor's UID and its
 * events. Returns the message ID of the last event, or -1.
 */
static int handle_report(const uint8_t *d, size_t n, const char *want_type)
{
	struct pb r = { d, d + n }, s;
	unsigned int f, wt;
	uint64_t v, lo = 0, hi = 0;
	const uint8_t *b;
	size_t bn;
	int last = -1;

	while (!pb_next(&r, &f, &wt, &v, &b, &bn)) {
		if (f == 1 && wt == 2) {
			s = (struct pb){ b, b + bn };
			while (!pb_next(&s, &f, &wt, &v, &b, &bn))
				if (f == 1)
					lo = v;
				else if (f == 2)
					hi = v;
		} else if (f == 2 && wt == 2) {
			uint32_t msg_id = 0;
			const uint8_t *m = NULL;
			size_t mn = 0;

			s = (struct pb){ b, b + bn };
			while (!pb_next(&s, &f, &wt, &v, &b, &bn))
				if (f == 1)
					msg_id = v;
				else if (f == 3 && wt == 2) {
					m = b;
					mn = bn;
				}
			last = msg_id;
			if (msg_id == MSG_SUID_EVENT && m) {
				struct pb e = { m, m + mn };
				char type[48] = "";
				int count = 0;

				while (!pb_next(&e, &f, &wt, &v, &b, &bn)) {
					if (f == 1 && wt == 2) {
						snprintf(type, sizeof(type), "%.*s", (int)bn, (const char *)b);
					} else if (f == 2 && wt == 2) {
						struct pb u = { b, b + bn };
						uint64_t ulo = 0, uhi = 0;

						while (!pb_next(&u, &f, &wt, &v, &b, &bn))
							if (f == 1)
								ulo = v;
							else if (f == 2)
								uhi = v;
						count++;
						if (uid_index(ulo, uhi) < 0 && n_uids < MAX_UIDS) {
							uids[n_uids].lo = ulo;
							uids[n_uids].hi = uhi;
							snprintf(uids[n_uids].type, sizeof(uids[0].type), "%s", type);
							n_uids++;
						}
					}
				}
				printf("ssc: suid %s: %d\n", type, count);
			} else if (msg_id == MSG_ATTR_EVENT && m) {
				handle_attrs(uid_index(lo, hi), m, mn);
			} else {
				printf("ssc: event %u from %s #%d, %zu bytes\n", msg_id,
				       uid_index(lo, hi) >= 0 ? uids[uid_index(lo, hi)].type :
				       (lo == SUID_LOOKUP ? "suid" : "?"),
				       uid_index(lo, hi), mn);
			}
		}
	}
	(void)want_type;
	return last;
}

/* Reads until an event with message ID @want arrives, or @secs pass. */
static int wait_for(int want, double secs)
{
	uint8_t m[65536];
	struct pollfd pfd = { .fd = sock, .events = POLLIN };
	double end = now() + secs;

	while (now() < end) {
		ssize_t n;
		size_t i, tl;
		uint16_t id;

		if (poll(&pfd, 1, (int)((end - now()) * 1000) + 1) <= 0)
			continue;
		n = recv(sock, m, sizeof(m), 0);
		if (n < 7)
			continue;
		id = m[3] | m[4] << 8;
		tl = m[5] | m[6] << 8;
		if ((size_t)n < 7 + tl)
			tl = n - 7;
		for (i = 7; i + 3 <= 7 + tl;) {
			uint8_t t = m[i];
			size_t l = m[i + 1] | m[i + 2] << 8;
			const uint8_t *val = m + i + 3;

			if (i + 3 + l > 7 + tl)
				break;
			if (m[0] == 2 && id == SSC_CONTROL && t == 0x02 && l >= 4) {
				unsigned int res = val[0] | val[1] << 8;
				unsigned int err = val[2] | val[3] << 8;

				if (res || err)
					printf("ssc: control result %u error %u\n", res, err);
			} else if (m[0] == 4 && (id == SSC_REPORT_SMALL || id == SSC_REPORT_LARGE) &&
				   t == 0x02 && l >= 2) {
				size_t pl = val[0] | val[1] << 8;

				if (pl + 2 <= l && handle_report(val + 2, pl, NULL) == want)
					return 0;
			}
			i += 3 + l;
		}
	}
	return -1;
}

int main(int argc, char **argv)
{
	const char *const *types = default_types;
	int n_types = sizeof(default_types) / sizeof(default_types[0]);
	int i;

	if (argc > 1) {
		types = (const char *const *)argv + 1;
		n_types = argc - 1;
	}

	sock = socket(AF_QIPCRTR, SOCK_DGRAM, 0);
	if (sock < 0) {
		printf("ssc: socket: %s\n", strerror(errno));
		return 1;
	}
	if (lookup_ssc())
		return 1;

	for (i = 0; i < n_types; i++) {
		struct obuf p = { .n = 0 };

		put_bytes(&p, 1, types[i], strlen(types[i]));
		put_key(&p, 2, 0);
		put_varint(&p, 0);		/* no updates */
		put_key(&p, 3, 0);
		put_varint(&p, 0);		/* every sensor, not the default */
		if (send_request(SUID_LOOKUP, SUID_LOOKUP, MSG_SUID_REQ, &p))
			return 1;
		if (wait_for(MSG_SUID_EVENT, 2))
			printf("ssc: suid %s: no answer\n", types[i]);
	}
	printf("ssc: %d sensors\n", n_uids);

	for (i = 0; i < n_uids; i++) {
		struct obuf p = { .n = 0 };

		if (send_request(uids[i].lo, uids[i].hi, MSG_ATTR_REQ, &p))
			return 1;
		if (wait_for(MSG_ATTR_EVENT, 2))
			printf("ssc: attrs of %s #%d: no answer\n", uids[i].type, i);
	}
	return 0;
}
