// SPDX-License-Identifier: BSD-3-Clause
/*
 * The QMI services Sony's modem firmware expects of Android.
 *
 * The modem reads units of the phone's trim area (TA) through two services
 * Android provides from ta_qmi_service: 0xe3, which is libta's interface
 * (open a partition, read, write, iterate), and 0xe4, which is libmiscta's
 * (read and write units of partition 2). Until both are up, the modem's data
 * side never finishes starting. Once they are, its SIM manager starts
 * sending log lines to 0xe6, mlog_qmi_service's, and does not register the
 * UIM service until that one answers.
 *
 * This answers TA and MiscTA from the TA partition, which it opens
 * read-only. Writes are kept in memory for as long as we run and never reach
 * the partition: the TA also holds the bootloader's unlock state and the
 * device keys, and nothing here is sure enough of the format to rewrite it.
 * MLog's lines go to standard output.
 */
#include <sys/select.h>
#include <sys/socket.h>
#include <ctype.h>
#include <errno.h>
#include <getopt.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include <linux/qrtr.h>

#include "libqrtr.h"
#include "qmi_sony.h"
#include "ta.h"

#define DEFAULT_TA_PATH "/dev/disk/by-partlabel/TA"

/*
 * libta's TA_ErrCode_t and libmiscta's miscta_status_t, from tad and
 * libmiscta. ta_qmi_service passes both through unchanged: its tables at
 * 0x1370 and 0x13c8 map every code to itself.
 */
#define TA_OK			0
#define TA_ERR_GENERAL		1
#define TA_ERR_NOT_FOUND	4
#define TA_ERR_ACCESS		5
#define TA_ERR_INVALID		7

#define MISCTA_OK		0
#define MISCTA_ERR_GENERAL	1
#define MISCTA_ERR_TOO_SMALL	4
#define MISCTA_ERR_NOT_FOUND	5

/* ta_open's mode bits; 0 and 6 are refused */
#define TA_MODE_READ		0x1
#define TA_MODE_WRITE		0x6

/* One partition open at a time per client, as libta has per process */
struct client {
	unsigned int node;
	unsigned int port;
	uint32_t partition;
	uint32_t mode;
	const struct ta_unit *iter;
	bool iter_started;
	struct client *next;
};

static struct client *clients;
static volatile sig_atomic_t done;

static struct client *client_get(unsigned int node, unsigned int port)
{
	struct client *c;

	for (c = clients; c; c = c->next)
		if (c->node == node && c->port == port)
			return c;

	c = calloc(1, sizeof(*c));
	if (!c)
		return NULL;
	c->node = node;
	c->port = port;
	c->next = clients;
	clients = c;

	return c;
}

static void client_drop(unsigned int node, unsigned int port, bool all_ports)
{
	struct client **p = &clients;
	struct client *c;

	while ((c = *p)) {
		if (c->node == node && (all_ports || c->port == port)) {
			*p = c->next;
			free(c);
		} else {
			p = &c->next;
		}
	}
}

/* CLOSE, GET_NEXT_ID and FLUSH carry no TLVs; this still checks the header */
static int decode_empty(const struct qrtr_packet *pkt, unsigned int msg_id,
			unsigned int *txn)
{
	char unused;

	return qmi_decode_message(&unused, txn, pkt, QMI_REQUEST, msg_id,
				  ta_qmi_empty_req_ei);
}

static void respond(int sock, const struct qrtr_packet *pkt, int msg_id,
		    unsigned int txn, const void *resp,
		    struct qmi_elem_info *ei, const char *tag)
{
	/* The largest response is a full TA read: 64,524 bytes of TLVs */
	static char buf[TA_QMI_DATA_MAX + 256];
	struct qrtr_packet out = { .data = buf, .data_len = sizeof(buf) };
	ssize_t len;

	len = qmi_encode_message(&out, QMI_RESPONSE, msg_id, txn, resp, ei);
	if (len < 0) {
		fprintf(stderr, "[%s] failed to encode response %d: %s\n",
			tag, msg_id, strerror(-len));
		return;
	}

	if (qrtr_sendto(sock, pkt->node, pkt->port, out.data, len) < 0)
		fprintf(stderr, "[%s] failed to send response %d: %s\n",
			tag, msg_id, strerror(errno));
}

static void handle_ta(int sock, const struct qrtr_packet *pkt,
		      unsigned int msg_id)
{
	static struct ta_qmi_write_large_req wlreq;
	static struct ta_qmi_write_req wreq;
	static struct ta_qmi_data_resp dresp;
	struct ta_qmi_read_large_req rlreq = {};
	struct ta_qmi_status_resp sresp = {};
	struct ta_qmi_next_id_resp nresp = {};
	struct ta_qmi_size_resp zresp = {};
	struct ta_qmi_read_req rreq = {};
	struct ta_qmi_open_req oreq = {};
	struct ta_qmi_unit_req ureq = {};
	uint32_t offset;
	struct client *c;
	struct ta_unit *u;
	unsigned int txn;

	c = client_get(pkt->node, pkt->port);
	if (!c)
		return;

	switch (msg_id) {
	case TA_QMI_OPEN:
		if (qmi_decode_message(&oreq, &txn, pkt, QMI_REQUEST, msg_id,
				       ta_qmi_open_req_ei) < 0)
			break;
		oreq.mode &= 7;
		if (c->partition)
			sresp.status = TA_ERR_GENERAL;
		else if ((oreq.partition != TA_PARTITION_TRIM &&
			  oreq.partition != TA_PARTITION_MISC) ||
			 !oreq.mode || oreq.mode == TA_MODE_WRITE)
			sresp.status = TA_ERR_INVALID;
		else
			sresp.status = TA_OK;
		if (sresp.status == TA_OK) {
			c->partition = oreq.partition;
			c->mode = oreq.mode;
			c->iter = NULL;
			c->iter_started = false;
		}
		printf("[TA] %u:%u open partition %u mode 0x%x => %u\n",
		       c->node, c->port, oreq.partition, oreq.mode,
		       sresp.status);
		respond(sock, pkt, msg_id, txn, &sresp,
			ta_qmi_status_resp_ei, "TA");
		return;

	case TA_QMI_CLOSE:
		if (decode_empty(pkt, msg_id, &txn) < 0)
			break;
		sresp.status = c->partition ? TA_OK : TA_ERR_GENERAL;
		printf("[TA] %u:%u close partition %u => %u\n",
		       c->node, c->port, c->partition, sresp.status);
		c->partition = 0;
		respond(sock, pkt, msg_id, txn, &sresp,
			ta_qmi_status_resp_ei, "TA");
		return;

	case TA_QMI_GET_SIZE:
		if (qmi_decode_message(&ureq, &txn, pkt, QMI_REQUEST, msg_id,
				       ta_qmi_unit_req_ei) < 0)
			break;
		u = c->partition ? ta_store_find(c->partition, ureq.unit) : NULL;
		zresp.status = !c->partition ? TA_ERR_GENERAL :
			       u ? TA_OK : TA_ERR_NOT_FOUND;
		zresp.size_valid = zresp.status == TA_OK;
		zresp.size = u ? u->size : 0;
		printf("[TA] %u:%u size %u/%u => %u, %u bytes\n", c->node,
		       c->port, c->partition, ureq.unit, zresp.status,
		       zresp.size);
		respond(sock, pkt, msg_id, txn, &zresp,
			ta_qmi_size_resp_ei, "TA");
		return;

	case TA_QMI_READ:
		if (qmi_decode_message(&rreq, &txn, pkt, QMI_REQUEST, msg_id,
				       ta_qmi_read_req_ei) < 0)
			break;
		memset(&dresp, 0, sizeof(dresp));
		u = c->partition ? ta_store_find(c->partition, rreq.unit) : NULL;
		/* libta reads a unit whole, and only at its exact size */
		if (!c->partition)
			dresp.status = TA_ERR_GENERAL;
		else if (!(c->mode & TA_MODE_READ))
			dresp.status = TA_ERR_ACCESS;
		else if (!u)
			dresp.status = TA_ERR_NOT_FOUND;
		else if (rreq.size != u->size || u->size > TA_QMI_DATA_MAX)
			dresp.status = TA_ERR_INVALID;
		else
			dresp.status = TA_OK;
		if (dresp.status == TA_OK) {
			memcpy(dresp.data, u->data, u->size);
			dresp.data_len = u->size;
			dresp.data_valid = true;
		}
		printf("[TA] %u:%u read %u/%u, %u bytes => %u, %u bytes\n",
		       c->node, c->port, c->partition, rreq.unit, rreq.size,
		       dresp.status, dresp.data_len);
		respond(sock, pkt, msg_id, txn, &dresp,
			ta_qmi_data_resp_ei, "TA");
		return;

	case TA_QMI_READ_LARGE:
		if (qmi_decode_message(&rlreq, &txn, pkt, QMI_REQUEST, msg_id,
				       ta_qmi_read_large_req_ei) < 0)
			break;
		memset(&dresp, 0, sizeof(dresp));
		u = c->partition ? ta_store_find(c->partition, rlreq.unit) : NULL;
		/* Chunk n of a unit too big for one response starts at n * 64512 */
		offset = rlreq.chunk * TA_QMI_DATA_MAX;
		if (!c->partition)
			dresp.status = TA_ERR_GENERAL;
		else if (!(c->mode & TA_MODE_READ))
			dresp.status = TA_ERR_ACCESS;
		else if (!u)
			dresp.status = TA_ERR_NOT_FOUND;
		else if (rlreq.chunk >= UINT32_MAX / TA_QMI_DATA_MAX ||
			 rlreq.size > TA_QMI_DATA_MAX || offset > u->size ||
			 rlreq.size > u->size - offset)
			dresp.status = TA_ERR_INVALID;
		else
			dresp.status = TA_OK;
		if (dresp.status == TA_OK) {
			memcpy(dresp.data, u->data + offset, rlreq.size);
			dresp.data_len = rlreq.size;
			dresp.data_valid = true;
		}
		printf("[TA] %u:%u read %u/%u chunk %u, %u bytes => %u, %u bytes\n",
		       c->node, c->port, c->partition, rlreq.unit, rlreq.chunk,
		       rlreq.size, dresp.status, dresp.data_len);
		respond(sock, pkt, msg_id, txn, &dresp,
			ta_qmi_data_resp_ei, "TA");
		return;

	case TA_QMI_WRITE:
		memset(&wreq, 0, sizeof(wreq));
		if (qmi_decode_message(&wreq, &txn, pkt, QMI_REQUEST, msg_id,
				       ta_qmi_write_req_ei) < 0)
			break;
		if (!c->partition)
			sresp.status = TA_ERR_GENERAL;
		else if (!(c->mode & TA_MODE_WRITE))
			sresp.status = TA_ERR_ACCESS;
		else
			sresp.status = ta_store_put(c->partition, wreq.unit,
						    wreq.data, wreq.data_len,
						    false) ?
				       TA_ERR_GENERAL : TA_OK;
		printf("[TA] %u:%u write %u/%u, %u bytes, held in memory => %u\n",
		       c->node, c->port, c->partition, wreq.unit,
		       wreq.data_len, sresp.status);
		respond(sock, pkt, msg_id, txn, &sresp,
			ta_qmi_status_resp_ei, "TA");
		return;

	case TA_QMI_WRITE_LARGE:
		memset(&wlreq, 0, sizeof(wlreq));
		if (qmi_decode_message(&wlreq, &txn, pkt, QMI_REQUEST, msg_id,
				       ta_qmi_write_large_req_ei) < 0)
			break;
		/* Chunk 0 replaces the unit and later ones append, as Sony's does */
		if (!c->partition)
			sresp.status = TA_ERR_GENERAL;
		else if (!(c->mode & TA_MODE_WRITE))
			sresp.status = TA_ERR_ACCESS;
		else
			sresp.status = ta_store_put(c->partition, wlreq.unit,
						    wlreq.data, wlreq.data_len,
						    wlreq.chunk != 0) ?
				       TA_ERR_GENERAL : TA_OK;
		printf("[TA] %u:%u write %u/%u chunk %u, %u bytes, held in memory => %u\n",
		       c->node, c->port, c->partition, wlreq.unit, wlreq.chunk,
		       wlreq.data_len, sresp.status);
		respond(sock, pkt, msg_id, txn, &sresp,
			ta_qmi_status_resp_ei, "TA");
		return;

	case TA_QMI_DELETE:
		if (qmi_decode_message(&ureq, &txn, pkt, QMI_REQUEST, msg_id,
				       ta_qmi_unit_req_ei) < 0)
			break;
		if (!c->partition)
			sresp.status = TA_ERR_GENERAL;
		else if (!(c->mode & TA_MODE_WRITE))
			sresp.status = TA_ERR_ACCESS;
		else
			sresp.status = ta_store_delete(c->partition, ureq.unit) ?
				       TA_ERR_NOT_FOUND : TA_OK;
		printf("[TA] %u:%u delete %u/%u, in memory => %u\n", c->node,
		       c->port, c->partition, ureq.unit, sresp.status);
		respond(sock, pkt, msg_id, txn, &sresp,
			ta_qmi_status_resp_ei, "TA");
		return;

	case TA_QMI_GET_NEXT_ID:
		if (decode_empty(pkt, msg_id, &txn) < 0)
			break;
		/* The end of the walk is "not found", as in libta */
		if (c->partition) {
			c->iter = ta_store_next(c->partition,
						c->iter_started ? c->iter : NULL);
			c->iter_started = true;
		}
		nresp.status = !c->partition ? TA_ERR_GENERAL :
			       c->iter ? TA_OK : TA_ERR_NOT_FOUND;
		nresp.unit_valid = nresp.size_valid = nresp.status == TA_OK;
		nresp.unit = nresp.unit_valid ? c->iter->id : 0;
		nresp.size = nresp.size_valid ? c->iter->size : 0;
		printf("[TA] %u:%u next id in %u => %u, unit %u, %u bytes\n",
		       c->node, c->port, c->partition, nresp.status,
		       nresp.unit, nresp.size);
		respond(sock, pkt, msg_id, txn, &nresp,
			ta_qmi_next_id_resp_ei, "TA");
		return;

	default:
		printf("[TA] %u:%u unknown request %u\n", pkt->node, pkt->port,
		       msg_id);
		return;
	}

	fprintf(stderr, "[TA] %u:%u malformed request %u\n", pkt->node,
		pkt->port, msg_id);
}

static void handle_miscta(int sock, const struct qrtr_packet *pkt,
			  unsigned int msg_id)
{
	static struct miscta_qmi_write_req wreq;
	static struct miscta_qmi_data_resp dresp;
	struct ta_qmi_status_resp sresp = {};
	struct ta_qmi_size_resp zresp = {};
	struct ta_qmi_unit_req ureq = {};
	struct ta_unit *u;
	unsigned int txn;

	switch (msg_id) {
	case MISCTA_QMI_GET_SIZE:
		if (qmi_decode_message(&ureq, &txn, pkt, QMI_REQUEST, msg_id,
				       ta_qmi_unit_req_ei) < 0)
			break;
		u = ta_store_find(TA_PARTITION_MISC, ureq.unit);
		zresp.status = u ? MISCTA_OK : MISCTA_ERR_NOT_FOUND;
		zresp.size_valid = !!u;
		zresp.size = u ? u->size : 0;
		printf("[MiscTA] %u:%u size %u => %u, %u bytes\n", pkt->node,
		       pkt->port, ureq.unit, zresp.status, zresp.size);
		respond(sock, pkt, msg_id, txn, &zresp,
			ta_qmi_size_resp_ei, "MiscTA");
		return;

	case MISCTA_QMI_READ:
		if (qmi_decode_message(&ureq, &txn, pkt, QMI_REQUEST, msg_id,
				       ta_qmi_unit_req_ei) < 0)
			break;
		memset(&dresp, 0, sizeof(dresp));
		u = ta_store_find(TA_PARTITION_MISC, ureq.unit);
		if (!u) {
			dresp.status = MISCTA_ERR_NOT_FOUND;
		} else if (u->size > MISCTA_QMI_DATA_MAX) {
			dresp.status = MISCTA_ERR_TOO_SMALL;
		} else {
			dresp.status = MISCTA_OK;
			memcpy(dresp.data, u->data, u->size);
			dresp.data_len = u->size;
			dresp.data_valid = true;
		}
		printf("[MiscTA] %u:%u read %u => %u, %u bytes\n", pkt->node,
		       pkt->port, ureq.unit, dresp.status, dresp.data_len);
		respond(sock, pkt, msg_id, txn, &dresp,
			miscta_qmi_data_resp_ei, "MiscTA");
		return;

	case MISCTA_QMI_WRITE:
	case MISCTA_QMI_WRITE_CRITICAL:
		memset(&wreq, 0, sizeof(wreq));
		if (qmi_decode_message(&wreq, &txn, pkt, QMI_REQUEST, msg_id,
				       miscta_qmi_write_req_ei) < 0)
			break;
		sresp.status = ta_store_put(TA_PARTITION_MISC, wreq.unit,
					    wreq.data, wreq.data_len, false) ?
			       MISCTA_ERR_GENERAL : MISCTA_OK;
		printf("[MiscTA] %u:%u write%s %u, %u bytes, held in memory => %u\n",
		       pkt->node, pkt->port,
		       msg_id == MISCTA_QMI_WRITE_CRITICAL ? " critical" : "",
		       wreq.unit, wreq.data_len, sresp.status);
		respond(sock, pkt, msg_id, txn, &sresp,
			ta_qmi_status_resp_ei, "MiscTA");
		return;

	case MISCTA_QMI_FLUSH:
		if (decode_empty(pkt, msg_id, &txn) < 0)
			break;
		sresp.status = MISCTA_OK;
		printf("[MiscTA] %u:%u flush, nothing written => %u\n",
		       pkt->node, pkt->port, sresp.status);
		respond(sock, pkt, msg_id, txn, &sresp,
			ta_qmi_status_resp_ei, "MiscTA");
		return;

	default:
		printf("[MiscTA] %u:%u unknown request %u\n", pkt->node,
		       pkt->port, msg_id);
		return;
	}

	fprintf(stderr, "[MiscTA] %u:%u malformed request %u\n", pkt->node,
		pkt->port, msg_id);
}

/* MLog's requests are read by hand: TLV 5's layout is not known */
static const uint8_t *qmi_tlv(const struct qrtr_packet *pkt, uint8_t type,
			      uint16_t *len)
{
	const uint8_t *p = (const uint8_t *)pkt->data + 7;
	const uint8_t *end = (const uint8_t *)pkt->data + pkt->data_len;
	uint16_t l;

	while (end - p >= 3) {
		l = p[1] | p[2] << 8;
		if (l > end - p - 3)
			return NULL;
		if (p[0] == type) {
			*len = l;
			return p + 3;
		}
		p += 3 + l;
	}

	return NULL;
}

static uint32_t tlv_u32(const struct qrtr_packet *pkt, uint8_t type)
{
	const uint8_t *v;
	uint16_t len;

	v = qmi_tlv(pkt, type, &len);
	if (!v || len != 4)
		return 0;

	return v[0] | v[1] << 8 | v[2] << 16 | (uint32_t)v[3] << 24;
}

/* A text TLV: a 16-bit count, then that many bytes */
static void print_text(const struct qrtr_packet *pkt, uint8_t type)
{
	const uint8_t *v;
	uint16_t len, n, i;

	v = qmi_tlv(pkt, type, &len);
	if (!v || len < 2) {
		putchar('?');
		return;
	}

	n = v[0] | v[1] << 8;
	if (n > len - 2)
		n = len - 2;
	for (i = 0; i < n && v[2 + i]; i++)
		putchar(isprint(v[2 + i]) ? v[2 + i] : '.');
}

static void handle_mlog(int sock, const struct qrtr_packet *pkt,
			unsigned int msg_id)
{
	const uint8_t *hdr = pkt->data;
	struct ta_qmi_status_resp sresp = {};
	struct mlog_qmi_get_resp gresp = {};
	unsigned int txn = hdr[1] | hdr[2] << 8;

	if (hdr[0] != QMI_REQUEST)
		return;

	switch (msg_id) {
	case MLOG_QMI_LOG:
		printf("[MLog] <%u> ", tlv_u32(pkt, 1));
		print_text(pkt, 3);
		printf(":%u: ", tlv_u32(pkt, 4));
		print_text(pkt, 6);
		putchar('\n');
		respond(sock, pkt, msg_id, txn, &sresp,
			ta_qmi_status_resp_ei, "MLog");
		return;

	case MLOG_QMI_GET:
		printf("[MLog] %u:%u get => 0\n", pkt->node, pkt->port);
		respond(sock, pkt, msg_id, txn, &gresp,
			mlog_qmi_get_resp_ei, "MLog");
		return;

	default:
		printf("[MLog] %u:%u unknown request %u\n", pkt->node,
		       pkt->port, msg_id);
		return;
	}
}

struct service {
	const char *name;
	unsigned int id;
	unsigned int version;
	unsigned int instance;
	void (*handle)(int sock, const struct qrtr_packet *pkt,
		       unsigned int msg_id);
	int sock;
};

static struct service services[] = {
	{
		.name = "TA",
		.id = TA_QMI_SERVICE,
		.version = TA_QMI_VERSION,
		.instance = TA_QMI_INSTANCE,
		.handle = handle_ta,
	},
	{
		.name = "MiscTA",
		.id = MISCTA_QMI_SERVICE,
		.version = MISCTA_QMI_VERSION,
		.instance = MISCTA_QMI_INSTANCE,
		.handle = handle_miscta,
	},
	{
		.name = "MLog",
		.id = MLOG_QMI_SERVICE,
		.version = MLOG_QMI_VERSION,
		.instance = MLOG_QMI_INSTANCE,
		.handle = handle_mlog,
	},
};

#define NSERVICES (sizeof(services) / sizeof(services[0]))

static int handle_packet(struct service *s)
{
	/* The largest request is a full TA write: 64,531 bytes of TLVs */
	static char buf[TA_QMI_DATA_MAX + 256];
	struct sockaddr_qrtr sq;
	struct qrtr_packet pkt;
	unsigned int msg_id;
	socklen_t sl = sizeof(sq);
	int ret;

	ret = recvfrom(s->sock, buf, sizeof(buf), 0, (void *)&sq, &sl);
	if (ret < 0) {
		ret = -errno;
		if (ret != -ENETRESET)
			fprintf(stderr, "recvfrom failed: %s\n", strerror(-ret));
		return ret;
	}

	ret = qrtr_decode(&pkt, buf, ret, &sq);
	if (ret < 0) {
		fprintf(stderr, "unable to decode qrtr packet\n");
		return ret;
	}

	switch (pkt.type) {
	case QRTR_TYPE_BYE:
		client_drop(pkt.node, 0, true);
		break;
	case QRTR_TYPE_DEL_CLIENT:
		client_drop(pkt.node, pkt.port, false);
		break;
	case QRTR_TYPE_DATA:
		if (qmi_decode_header(&pkt, &msg_id) < 0)
			break;
		s->handle(s->sock, &pkt, msg_id);
		fflush(stdout);
		break;
	}

	return 0;
}

static int open_service(unsigned int service, unsigned int version,
			unsigned int instance)
{
	int sock;

	sock = qrtr_open(0);
	if (sock < 0) {
		fprintf(stderr, "failed to open a qrtr socket: %s\n",
			strerror(errno));
		return -1;
	}

	if (qrtr_publish(sock, service, version, instance) < 0) {
		fprintf(stderr, "failed to publish service 0x%x: %s\n",
			service, strerror(errno));
		qrtr_close(sock);
		return -1;
	}

	return sock;
}

static void on_signal(int sig)
{
	done = 1;
}

static void usage(const char *argv0)
{
	fprintf(stderr,
		"Usage: %s [-i image] [-d dir]\n"
		"  -i image  raw TA partition or a copy of one, opened read-only\n"
		"            (default " DEFAULT_TA_PATH ")\n"
		"  -d dir    units to serve in place of the image's, as dir/<partition>/<unit>\n",
		argv0);
}

int main(int argc, char **argv)
{
	const char *image = DEFAULT_TA_PATH;
	const char *dir = NULL;
	struct sigaction sa = { .sa_handler = on_signal };
	struct service *s;
	fd_set rfds;
	int nfds = 0;
	int opt;
	int ret;

	while ((opt = getopt(argc, argv, "i:d:h")) != -1) {
		switch (opt) {
		case 'i':
			image = optarg;
			break;
		case 'd':
			dir = optarg;
			break;
		default:
			usage(argv[0]);
			return opt == 'h' ? 0 : 1;
		}
	}

	setvbuf(stdout, NULL, _IOLBF, 0);

	if (ta_store_load(image) < 0)
		return 1;
	if (dir && ta_store_load_dir(dir) < 0)
		return 1;

	sigaction(SIGINT, &sa, NULL);
	sigaction(SIGTERM, &sa, NULL);

	for (s = services; s < services + NSERVICES; s++) {
		s->sock = open_service(s->id, s->version, s->instance);
		if (s->sock < 0)
			return 1;
		if (s->sock >= nfds)
			nfds = s->sock + 1;
		printf("serving %s (0x%x)\n", s->name, s->id);
	}

	while (!done) {
		FD_ZERO(&rfds);
		for (s = services; s < services + NSERVICES; s++)
			FD_SET(s->sock, &rfds);

		ret = select(nfds, &rfds, NULL, NULL, NULL);
		if (ret < 0) {
			if (errno == EINTR)
				continue;
			fprintf(stderr, "select failed: %s\n", strerror(errno));
			break;
		}

		for (s = services; s < services + NSERVICES; s++)
			if (FD_ISSET(s->sock, &rfds))
				handle_packet(s);
	}

	for (s = services; s < services + NSERVICES; s++) {
		qrtr_bye(s->sock, s->id, s->version, s->instance);
		qrtr_close(s->sock);
	}
	ta_store_free();

	return 0;
}
