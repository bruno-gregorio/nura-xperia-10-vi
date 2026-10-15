// SPDX-License-Identifier: BSD-3-Clause
// Copyright (c) 2026, Bruno Gregório
//
// egisfp-load - a Free Software smoke-test client for the Egis EC617
// fingerprint trusted app (egisap64) on the Sony Xperia 10 VI (pdx246),
// driven over the mainline qcomtee TEE driver and libqcomtee.
//
// Part of the postmarketOS mainline port. It exists to answer one question:
// can a plain Linux client load this phone's own signed fingerprint TA
// through QTEE and get an answer back? It does the least that proves that:
//
//   1. open the QTEE root object and register as a client,
//   2. open the QSEEComCompat app loader (UID 122),
//   3. assemble egisap64 from its MBN split segments (.b00 .. .b08) exactly
//      as Qualcomm's __qseecom_start_app does - each segment laid at its ELF
//      program-header p_offset,
//   4. loadFromBuffer(image, "egisap64") to get an IQSEEComCompat object,
//   5. sendRequest with a trivial top command (0x01 or 0x00). These
//      dereference no pointer inside the TA, so they are the safe first
//      invocations - unlike the 0xE0 ETS path, which carries an embedded
//      pointer QTEE must fix up. --protocol gates a read-only version
//      query behind ping, inline framing and memory-object checks.
//   6. unload, so the single-residency "fingerprint" app name is freed.
//
// It never touches RPMB and registers no listeners.
//
// On this phone, load and unload over UID 122 work (QTEE accepts Sony's
// chain). The original 64-byte request/response buffers were rejected by
// the TA's entry checks before dispatch. Disassembly at 0x4c8 and 0x54c
// requires response >= 0x814 and request >= 0x868 bytes. Command 1 really
// does store operand*10 at response offset 0 (0x694), and status at 16.
//
// Usage: egisfp-load <firmware-dir> [operand] [cmd_id]
//   <firmware-dir> holds egisap64.b00 .. egisap64.b08.
//   [operand] is the u32 at request offset 8 (default 7).
//   [cmd_id]  is the top command (default 0x01); arbitrary 0xE0 is refused.
//   --protocol instead of operand: run the bounded read-only BIX checks.

#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>

#include <qcomtee_object_types.h>
#include "qseecom-transport.h"

/* IClientEnv (root op 2 registers a client; env op 0 opens a service). */
#define IClientEnv_OP_registerAsClient 2
#define IClientEnv_OP_open 0

/* QTEE service UIDs. */
#define CQSEEComCompatAppLoader_UID 122

/* IQSEEComCompatAppLoader ops (securemsm-kernel IQSEEComCompatAppLoader.h). */
#define IQSEEComCompatAppLoader_OP_loadFromBuffer 1

/* IQSEEComCompat ops (securemsm-kernel IQSEEComCompat.h). */
#define IQSEEComCompat_OP_sendRequest 0
#define IQSEEComCompat_OP_unload      2

#define EGIS_APP_NAME   "egisap64"
#define EGIS_SEGMENTS   9        /* .b00 .. .b08 */
#define MAX_FW_APP_SIZE 256      /* distName output buffer, as the vendor uses */

/* Command 0x01 request/response framing, from the TA handler (RE findings):
 * request: u32 cmd_id @0, u32 operand @8; response: u32 result @0 (=operand*10),
 * u32 status @16 (0 on success). The vendor transport passes the aligned
 * lengths 0x880/0x840 (libets_teeclient_v2.so at 0x2344/0x2348).
 */
#define REQ_SIZE 0x880
#define RSP_SIZE 0x840
#define CMD_PING 0x01

#define MSG(...) printf(__VA_ARGS__)

/* ----- root object + supplicant thread (mirrors quic-teec tests/common.c) --- */

struct supplicant {
	pthread_t thread;
	struct qcomtee_object *root;
};

/* op is TEE_IOC_SUPPL_RECV or TEE_IOC_SUPPL_SEND; musl ioctl is (int, int, ...). */
#ifdef __GLIBC__
static int tee_call(int fd, unsigned long op, ...)
#else
static int tee_call(int fd, int op, ...)
#endif
{
	va_list ap;
	int ret;

	va_start(ap, op);
	void *arg = va_arg(ap, void *);
	va_end(ap);

	pthread_setcanceltype(PTHREAD_CANCEL_ASYNCHRONOUS, NULL);
	ret = ioctl(fd, op, arg);
	pthread_setcanceltype(PTHREAD_CANCEL_DEFERRED, NULL);
	if (ret < 0)
		MSG("  tee_call: %s\n", strerror(errno));

	return ret;
}

static void *supplicant_worker(void *arg)
{
	struct supplicant *sup = arg;

	while (1) {
		pthread_testcancel();
		if (qcomtee_object_process_one(sup->root))
			break;
	}
	return NULL;
}

static void supplicant_release(void *arg)
{
	struct supplicant *sup = arg;

	if (sup->thread) {
		pthread_cancel(sup->thread);
		pthread_join(sup->thread, NULL);
	}
	free(sup);
}

static struct qcomtee_object *get_root(void)
{
	struct qcomtee_object *root;
	struct supplicant *sup;
	pthread_t thread;
	char tee_path[32] = {0};
	int found = 0;
	/* TEE numbering changes when the legacy transport is also loaded. */
	for (unsigned int i = 0; i < 16; i++) {
		struct tee_ioctl_version_data version = {0};
		snprintf(tee_path, sizeof(tee_path), "/dev/tee%u", i);
		int fd = open(tee_path, O_RDWR | O_CLOEXEC);
		if (fd < 0) continue;
		int matched = !ioctl(fd, TEE_IOC_VERSION, &version) && version.impl_id == 4;
		close(fd);
		if (matched) { found = 1; break; }
	}
	if (!found) {
		MSG("  QTEE object transport is not present\n");
		return QCOMTEE_OBJECT_NULL;
	}

	sup = calloc(1, sizeof(*sup));
	if (!sup)
		return QCOMTEE_OBJECT_NULL;

	root = qcomtee_object_root_init(tee_path, tee_call, supplicant_release,
					sup);
	if (root == QCOMTEE_OBJECT_NULL) {
		MSG("  cannot open QTEE object transport\n");
		free(sup);
		return QCOMTEE_OBJECT_NULL;
	}

	sup->root = root;
	if (pthread_create(&thread, NULL, supplicant_worker, sup)) {
		MSG("  cannot start supplicant thread\n");
		qcomtee_object_refs_dec(root); /* calls supplicant_release */
		return QCOMTEE_OBJECT_NULL;
	}
	sup->thread = thread;

	return root;
}

static struct qcomtee_object *get_client_env(struct qcomtee_object *root)
{
	struct qcomtee_object *creds;
	struct qcomtee_param params[2];
	qcomtee_result_t result = -1;

	if (qcomtee_object_credentials_init(root, &creds)) {
		MSG("  cannot build credentials object\n");
		return QCOMTEE_OBJECT_NULL;
	}

	params[0].attr = QCOMTEE_OBJREF_INPUT;
	params[0].object = creds;
	params[1].attr = QCOMTEE_OBJREF_OUTPUT;
	if (qcomtee_object_invoke(root, IClientEnv_OP_registerAsClient, params,
				  2, &result)) {
		qcomtee_object_refs_dec(creds);
		MSG("  registerAsClient failed\n");
		return QCOMTEE_OBJECT_NULL;
	}
	/* On success QTEE took ownership of creds. */
	if (result != QCOMTEE_OK) {
		MSG("  registerAsClient result %d\n", result);
		return QCOMTEE_OBJECT_NULL;
	}

	return params[1].object;
}

static struct qcomtee_object *get_service(struct qcomtee_object *env,
					  uint32_t uid)
{
	struct qcomtee_param params[2];
	qcomtee_result_t result = -1;

	params[0].attr = QCOMTEE_UBUF_INPUT;
	params[0].ubuf.addr = &uid;
	params[0].ubuf.size = sizeof(uid);
	params[1].attr = QCOMTEE_OBJREF_OUTPUT;
	if (qcomtee_object_invoke(env, IClientEnv_OP_open, params, 2, &result) ||
	    result != QCOMTEE_OK) {
		MSG("  IClientEnv.open(UID=%u) result %d\n", uid, result);
		return QCOMTEE_OBJECT_NULL;
	}

	return params[1].object;
}

/* ----- MBN split image assembly (same layout as __qseecom_start_app) -------- */

static unsigned char *read_file(const char *path, size_t *out_size)
{
	FILE *f = fopen(path, "rb");
	long sz;
	unsigned char *buf;

	if (!f) {
		MSG("  cannot open %s: %s\n", path, strerror(errno));
		return NULL;
	}
	if (fseek(f, 0, SEEK_END) || (sz = ftell(f)) < 0 ||
	    fseek(f, 0, SEEK_SET)) {
		fclose(f);
		return NULL;
	}
	buf = malloc((size_t)sz ? (size_t)sz : 1);
	if (!buf) {
		fclose(f);
		return NULL;
	}
	if (fread(buf, 1, (size_t)sz, f) != (size_t)sz) {
		MSG("  short read on %s\n", path);
		free(buf);
		fclose(f);
		return NULL;
	}
	fclose(f);
	*out_size = (size_t)sz;
	return buf;
}

static inline uint16_t rd16(const unsigned char *p) { return p[0] | p[1] << 8; }
static inline uint64_t rd64(const unsigned char *p)
{
	uint64_t v = 0;
	for (int i = 7; i >= 0; i--)
		v = (v << 8) | p[i];
	return v;
}

/* Assemble egisap64 into one contiguous buffer. Returns it (caller frees) and
 * sets *out_size, or NULL on error.
 */
static unsigned char *assemble_ta(const char *dir, size_t *out_size)
{
	char path[1024];
	unsigned char *b00;
	size_t b00_size, total = 0;
	unsigned char *image;
	uint64_t phoff;
	uint16_t phentsize, phnum;

	snprintf(path, sizeof(path), "%s/%s.b00", dir, EGIS_APP_NAME);
	b00 = read_file(path, &b00_size);
	if (!b00)
		return NULL;

	if (b00_size < 64 || memcmp(b00, "\177ELF", 4) != 0 || b00[4] != 2) {
		MSG("  %s is not an ELF64\n", path);
		free(b00);
		return NULL;
	}
	phoff = rd64(b00 + 32);
	phentsize = rd16(b00 + 54);
	phnum = rd16(b00 + 56);
	if (phnum != EGIS_SEGMENTS || phentsize < 56 ||
	    phoff + (uint64_t)phnum * phentsize > b00_size) {
		MSG("  unexpected program headers (phnum=%u)\n", phnum);
		free(b00);
		return NULL;
	}

	/* First pass: total image size = max(p_offset + p_filesz). */
	for (uint16_t i = 0; i < phnum; i++) {
		const unsigned char *ph = b00 + phoff + (uint64_t)i * phentsize;
		uint64_t off = rd64(ph + 8), filesz = rd64(ph + 32);

		if (off + filesz > total)
			total = off + filesz;
	}

	image = calloc(1, total);
	if (!image) {
		MSG("  cannot allocate %zu bytes for the image\n", total);
		free(b00);
		return NULL;
	}

	/* Second pass: lay each .bNN at its p_offset, in ascending order. */
	for (uint16_t i = 0; i < phnum; i++) {
		const unsigned char *ph = b00 + phoff + (uint64_t)i * phentsize;
		uint64_t off = rd64(ph + 8), filesz = rd64(ph + 32);
		unsigned char *seg;
		size_t seg_size;

		if (filesz == 0)
			continue;

		snprintf(path, sizeof(path), "%s/%s.b%02u", dir, EGIS_APP_NAME, i);
		seg = read_file(path, &seg_size);
		if (!seg) {
			free(image);
			free(b00);
			return NULL;
		}
		if (seg_size != filesz)
			MSG("  note: %s is %zu bytes, p_filesz is %llu\n", path,
			    seg_size, (unsigned long long)filesz);
		memcpy(image + off, seg, seg_size < filesz ? seg_size : filesz);
		free(seg);
	}

	free(b00);
	*out_size = total;
	return image;
}

/* ----- load / invoke / unload ---------------------------------------------- */

static const char *loader_errname(qcomtee_result_t r)
{
	switch (r) {
	case 10: return "INVALID_BUFFER";
	case 11: return "PIL_ROLLBACK_FAILURE";
	case 12: return "ELF_SIGNATURE_ERROR";
	case 13: return "METADATA_INVALID";
	case 14: return "MAX_NUM_APPS";
	case 15: return "NO_NAME_IN_METADATA";
	case 16: return "ALREADY_LOADED";
	case 21: return "APP_UNTRUSTED_CLIENT";
	case 22: return "APP_BLACKLISTED";
	case 24: return "NOT_QSEECOM_COMPAT_APP";
	case 26: return "APP_ARCH_NOT_SUPPORTED";
	default: return "?";
	}
}

static struct qcomtee_object *load_ta(struct qcomtee_object *loader,
				      unsigned char *image, size_t image_size)
{
	struct qcomtee_param params[4];
	qcomtee_result_t result = -1;
	char dist_name[MAX_FW_APP_SIZE] = { 0 };

	params[0].attr = QCOMTEE_UBUF_INPUT;        /* appElf */
	params[0].ubuf.addr = image;
	params[0].ubuf.size = image_size;
	params[1].attr = QCOMTEE_UBUF_INPUT;        /* filename (no NUL) */
	params[1].ubuf.addr = (void *)EGIS_APP_NAME;
	params[1].ubuf.size = strlen(EGIS_APP_NAME);
	params[2].attr = QCOMTEE_UBUF_OUTPUT;       /* distName */
	params[2].ubuf.addr = dist_name;
	params[2].ubuf.size = sizeof(dist_name) - 1;
	params[3].attr = QCOMTEE_OBJREF_OUTPUT;     /* IQSEEComCompat */

	if (qcomtee_object_invoke(loader, IQSEEComCompatAppLoader_OP_loadFromBuffer,
				  params, 4, &result)) {
		MSG("  loadFromBuffer: transport error\n");
		return QCOMTEE_OBJECT_NULL;
	}
	if (result != QCOMTEE_OK) {
		MSG("  loadFromBuffer: result %d (%s)\n", result,
		    loader_errname(result));
		return QCOMTEE_OBJECT_NULL;
	}

	MSG("  loaded, distName=\"%.*s\"\n", (int)params[2].ubuf.size, dist_name);
	return params[3].object;
}

static void hexdump(const char *tag, const unsigned char *b, size_t n)
{
	MSG("  %s:", tag);
	for (size_t i = 0; i < n; i++) {
		if (i % 16 == 0)
			MSG("\n   %04zx:", i);
		MSG(" %02x", b[i]);
	}
	MSG("\n");
}

/* One embedded output buffer, matching IQSEEComCompat.sendRequest's
 * offset array and smo1 argument. A null smo means no pointer fix-up.
 */
static size_t response_input_size = RSP_SIZE;
static size_t request_output_size = REQ_SIZE;
static int legacy_transport;

static int send_request(struct qcomtee_object *app, unsigned char *req,
                        unsigned char *rsp, struct qcomtee_object *smo)
{
	struct qcomtee_param params[10] = { 0 };
	qcomtee_result_t result = -1;
	uint32_t is64 = 1, embedded_offset = 8;
	if (qsee.session_open)
		return egis_qseecom_send(req, REQ_SIZE, rsp, RSP_SIZE,
		        smo ? qcomtee_memory_object_addr(smo) : NULL,
		        smo ? qcomtee_memory_object_size(smo) : 0);
	if (legacy_transport) {
		if (smo) return -1;
		params[0].attr = QCOMTEE_UBUF_INPUT;
		params[0].ubuf.addr = req; params[0].ubuf.size = REQ_SIZE;
		params[1].attr = QCOMTEE_UBUF_OUTPUT;
		params[1].ubuf.addr = rsp; params[1].ubuf.size = RSP_SIZE;
		if (qcomtee_object_invoke(app, 0, params, 2, &result)) return -1;
		MSG("  legacy handleRequest: result %d, response size %zu\n",
		    result, params[1].ubuf.size);
		return result || params[1].ubuf.size != RSP_SIZE ? -1 : 0;
	}
	params[0].attr = QCOMTEE_UBUF_INPUT;  params[0].ubuf.addr = req; params[0].ubuf.size = REQ_SIZE;
	params[1].attr = QCOMTEE_UBUF_INPUT;  params[1].ubuf.addr = rsp; params[1].ubuf.size = response_input_size;
	params[2].attr = QCOMTEE_UBUF_INPUT;  params[2].ubuf.addr = &embedded_offset; params[2].ubuf.size = smo ? sizeof(embedded_offset) : 0;
	params[3].attr = QCOMTEE_UBUF_INPUT;  params[3].ubuf.addr = &is64; params[3].ubuf.size = sizeof(is64);
	params[4].attr = QCOMTEE_UBUF_OUTPUT; params[4].ubuf.addr = req; params[4].ubuf.size = request_output_size;
	params[5].attr = QCOMTEE_UBUF_OUTPUT; params[5].ubuf.addr = rsp; params[5].ubuf.size = RSP_SIZE;
	params[6].attr = QCOMTEE_OBJREF_INPUT; params[6].object = smo;
	params[7].attr = QCOMTEE_OBJREF_INPUT; params[7].object = QCOMTEE_OBJECT_NULL;
	params[8].attr = QCOMTEE_OBJREF_INPUT; params[8].object = QCOMTEE_OBJECT_NULL;
	params[9].attr = QCOMTEE_OBJREF_INPUT; params[9].object = QCOMTEE_OBJECT_NULL;

	if (qcomtee_object_invoke(app, IQSEEComCompat_OP_sendRequest, params, 10,
				  &result)) {
		MSG("  sendRequest: transport error\n");
		return -1;
	}
	if (result != QCOMTEE_OK) {
		MSG("  sendRequest: result %d\n", result);
		return -1;
	}

	if (params[4].ubuf.size != request_output_size || params[5].ubuf.size != RSP_SIZE) {
		MSG("  unexpected returned buffer lengths: %zu/%zu\n",
		    params[4].ubuf.size, params[5].ubuf.size);
		return -1;
	}
	return 0;
}

static void put32(unsigned char *b, size_t off, uint32_t value)
{
	memcpy(b + off, &value, sizeof(value));
}

static uint32_t rd32(const unsigned char *b)
{
	return (uint32_t)b[0] | ((uint32_t)b[1] << 8) |
	       ((uint32_t)b[2] << 16) | ((uint32_t)b[3] << 24);
}

static int send_ping(struct qcomtee_object *app, uint32_t cmd_id, uint32_t operand)
{
	unsigned char req[REQ_SIZE] = { 0 }, rsp[RSP_SIZE];
	memset(rsp, 0xaa, sizeof(rsp));
	put32(req, 0, cmd_id);
	put32(req, 8, operand);
	if (send_request(app, req, rsp, QCOMTEE_OBJECT_NULL))
		return -1;
	hexdump("rspOut prefix", rsp, 32);
	return (rd32(rsp + 16) == 0 &&
		rd32(rsp) == (cmd_id == 0 ? 1 : operand * 10)) ? 0 : -1;
}

/* Read-only protocol validation. These exact paths were checked by running
 * the phone's TA bytes in Unicorn (scripts/check-egis-ta-framing.py).
 * No GPIO, SPI-transfer, enroll, authentication, datastore or listener commands.
 * The original TA opens its secure SPI service while constructing the broker.
 */
static int hello_probe;
static int sensor_probe;

static int notify_spi_power(struct qcomtee_object *app, struct qcomtee_object *smo,
                            unsigned char *output, uint32_t enabled)
{
	unsigned char req[REQ_SIZE] = {0}, rsp[RSP_SIZE] = {0};
	/* Original ree_notify_spi_power_mode_state -> BIX broker IO control. */
	const uint32_t properties[] = {1, 12, 0x20070103, 4, enabled};
	put32(req, 0, 0xe0);
	put32(req, 24, 4096);
	put32(req, 108, 0x8004);
	put32(req, 120, sizeof(properties));
	memcpy(req + 124, properties, sizeof(properties));
	memset(output, 0, 4096);
	if (send_request(app, req, rsp, smo)) return -1;
	MSG("SPI power notification %u: status=%u output_length=%u\n",
	    enabled, rd32(rsp + 16), rd32(rsp + 36));
	return rd32(rsp + 16) || rd32(rsp + 36) ? -1 : 0;
}

static int check_sensor(struct qcomtee_object *app, struct qcomtee_object *smo,
                        unsigned char *output)
{
	unsigned char req[REQ_SIZE], rsp[RSP_SIZE];
	uint32_t power = 1;
	int fd = open("/dev/egisfp0", O_RDWR | O_CLOEXEC);
	int rc = -1;
	if (fd < 0) { perror("egisfp open"); return -1; }
	if (ioctl(fd, 0x40044581U, &power)) {
		perror("egisfp power");
		goto out;
	}
	if (notify_spi_power(app, smo, output, 1)) goto out;
	if (ioctl(fd, 0x4582U, 0)) { perror("egisfp reset"); goto out; }
	memset(req, 0, sizeof(req));
	put32(req, 0, 0xe0);
	put32(req, 24, 4096);
	/* Stock ree_init_sensor (agent 0x19b18..0x19bf0) precedes the
	 * acquisition workflow. Six serialized property records, recovered
	 * by executing the vendor initializer and serializer in Unicorn.
	 * EC617 uses the family-7 branch (48/800/500/50), not generic defaults.
	 * scripts/check-egis-vendor-init.py verifies the branch and serializer.
	 * No enrollment, templates or secure-storage commands.
	 */
	put32(req, 108, 0x8001);
	put32(req, 120, 84);
	put32(req, 124, 6);
	put32(req, 128, 76);
	const uint32_t properties[][3] = {
		{ 0x46040101, 8, 2 }, /* secure capture backend; sensor family 7 */
		{ 0x62040101, 4, 48 },
		{ 0x62040118, 4, 800 },
		{ 0x62040119, 4, 500 },
		{ 0x62040106, 4, 50 },
		{ 0x23000101, 4, 1 },
	};
	size_t at = 132;
	for (size_t i = 0; i < sizeof(properties)/sizeof(properties[0]); i++) {
		put32(req, at, properties[i][0]);
		put32(req, at + 4, properties[i][1]);
		put32(req, at + 8, properties[i][2]);
		if (properties[i][1] == 8) put32(req, at + 12, 7);
		at += 8 + properties[i][1];
	}
	if (at != 208) goto out;
	for (unsigned int step = 0; step < 24; step++) {
		memset(rsp, 0xaa, sizeof(rsp));
		memset(output, 0, 4096);
		if (send_request(app, req, rsp, smo)) goto out;
		uint32_t status = rd32(rsp + 16), length = rd32(rsp + 36);
		MSG("Sensor initialization step %u: status=%u output_length=%u\n", step, status, length);
		fflush(stdout);
		if (length > 4096) goto out;
		if (status != 10) {
			/* Do not print potential biometric data. */
			rc = status ? -1 : 0;
			break;
		}
		if (length < 40 || rd32(output) != 1 || rd32(output + 16) != 1 ||
		    rd32(output + 20) != length - 24) goto out;
		uint32_t token = rd32(output + 24), callback = rd32(output + 28);
		uint32_t input = rd32(output + 32), capacity = rd32(output + 36);
		MSG("  callback=%u input=%u output_capacity=%u\n", callback, input, capacity);
		if (input != length - 40) goto out;
		if (callback != 8 || input != 4 || capacity != 4) {
			MSG("  callback not implemented; stopping without servicing it\n");
			goto out;
		}
		uint32_t reset = rd32(output + 40);
		MSG("  hardware reset mode=%u\n", reset);
		fflush(stdout);
		if (reset == 2) {
			if (ioctl(fd, 0x4582U, 0)) goto out;
		} else if (reset == 1) {
			power = 0;
			if (ioctl(fd, 0x40044581U, &power)) goto out;
			usleep(1000000);
			power = 1;
			if (ioctl(fd, 0x40044581U, &power)) goto out;
			usleep(50000);
			if (ioctl(fd, 0x4582U, 0)) goto out;
		} else goto out;
		usleep(20000);
		memset(req, 0, sizeof(req));
		put32(req, 0, 0xe0);
		put32(req, 24, 4096);
		put32(req, 108, 0x5000);
		put32(req, 120, 20);
		put32(req, 124, token);
		put32(req, 132, 4);
		put32(req, 136, 4);
	}
out:
	close(fd); /* Kernel final-close powers off, including failed callbacks. */
	return rc;
}

static int check_protocol(struct qcomtee_object *root, struct qcomtee_object *app)
{
	unsigned char req[REQ_SIZE], rsp[RSP_SIZE];
	struct qcomtee_object *smo = QCOMTEE_OBJECT_NULL;
	unsigned char *output;
	int rc = -1;

	if (send_ping(app, 1, 7) || send_ping(app, 1, 3))
		return -1;
	MSG("PASS: correctly sized TA echo, two operands\n");
	memset(req, 0, sizeof(req));
	memset(rsp, 0xaa, sizeof(rsp));
	put32(req, 0, 0xe0);
	put32(req, 108, 0xe0000000); /* explicit no-dispatch branch at TA 0x7f0 */
	if (send_request(app, req, rsp, QCOMTEE_OBJECT_NULL) ||
	    rd32(rsp + 16) != 2 || rd32(rsp + 24) != 0xe0000000 || rd32(rsp + 36))
		return -1;
	MSG("PASS: pointer-free BIX framing\n");

	memset(req, 0, sizeof(req));
	memset(rsp, 0xaa, sizeof(rsp));
	put32(req, 0, 0xe0);
	put32(req, 108, 0xffffffff); /* BIX get property */
	put32(req, 120, 4);
	put32(req, 124, 0x00010000); /* LE u16 property set 0, id 1: version */
	if (send_request(app, req, rsp, QCOMTEE_OBJECT_NULL) || rd32(rsp + 16) != 7)
		return -1;
	MSG("PASS: version handler rejects absent output buffer\n");

	if (qcomtee_memory_object_alloc(4096, root, &smo))
		return -1;
	output = qcomtee_memory_object_addr(smo);
	if (!output || qcomtee_memory_object_size(smo) < 4096)
		goto out;
	memset(output, 0xaa, 4096);
	/* First ask compat to translate smo1 at offset 8 with a command that
	 * never dereferences that pointer. Only proceed after its valid reply.
	 */
	memset(req, 0, sizeof(req));
	memset(rsp, 0xaa, sizeof(rsp));
	if (send_request(app, req, rsp, smo) || rd32(rsp) != 1 || rd32(rsp + 16))
		goto out;
	MSG("PASS: transport accepts registered output object and offset 8\n");

	memset(req, 0, sizeof(req));
	memset(rsp, 0xaa, sizeof(rsp));
	put32(req, 0, 0xe0);
	put32(req, 24, 4096);
	put32(req, 108, 0xffffffff);
	put32(req, 120, 4);
	put32(req, 124, 0x00010000);
	if (send_request(app, req, rsp, smo) || rd32(rsp + 16) ||
	    rd32(rsp + 36) != 37 ||
	    memcmp(output, "SONY_pdx246_V20250211+build.6cd53fa4", 33))
		goto out;
	MSG("PASS: TA version via registered memory: %.*s\n", 37, output);
	if (hello_probe) {
		memset(req, 0, sizeof(req));
		memset(rsp, 0xaa, sizeof(rsp));
		memset(output, 0, 4096);
		put32(req, 0, 0xe0);
		put32(req, 24, 4096);
		/* BIX manager hello: asks only for the REE platform name.
		 * TA hello_handler 0x15cc8, callback proxy 0xb03c8.
		 */
		if (send_request(app, req, rsp, smo))
			goto out;
		uint32_t length = rd32(rsp + 36);
		MSG("BIX hello: status=%u output_length=%u\n", rd32(rsp + 16), length);
		if (length > 4096)
			goto out;
		hexdump("BIX hello output", output, length < 128 ? length : 128);
		/* libree_bix_agent 0x212f4..0x213ac replies with a flat
		 * {token, status, request_size, response_size, response} record;
		 * it is not the callback-list format returned by the TA.
		 * Accept only the exact platform-name callback, never a hardware
		 * or storage callback through this read-only probe.
		 */
		if (rd32(rsp + 16) != 10 || length != 44 ||
		    rd32(output) != 1 || rd32(output + 16) != 1 ||
		    rd32(output + 20) != 20 || rd32(output + 28) != 3 ||
		    rd32(output + 32) != 4 || rd32(output + 36) != 68 ||
		    rd32(output + 40) != 64)
			goto out;
		uint32_t token = rd32(output + 24);
		memset(req, 0, sizeof(req));
		memset(rsp, 0xaa, sizeof(rsp));
		memset(output, 0, 4096);
		put32(req, 0, 0xe0);
		put32(req, 24, 4096);
		put32(req, 108, 0x5000);
		put32(req, 120, 26);
		put32(req, 124, token);
		put32(req, 128, 0);
		put32(req, 132, 4);
		put32(req, 136, 10);
		put32(req, 140, 6); /* length includes terminating NUL */
		memcpy(req + 144, "Linux", 6);
		if (send_request(app, req, rsp, smo))
			goto out;
		length = rd32(rsp + 36);
		MSG("BIX hello completed: status=%u output_length=%u\n", rd32(rsp + 16), length);
		if (length > 4096)
			goto out;
		hexdump("BIX hello result", output, length < 128 ? length : 128);
		if (rd32(rsp + 16) || length < 19 ||
		    memcmp(output, "Linux:Hello BIX !!!", 19))
			goto out;
		MSG("PASS: BIX callback round trip, Linux platform hello\n");
	}
	if (sensor_probe && check_sensor(app, smo, output)) {
		/* Distinguish a rejected sensor transaction from a dead TA. */
		MSG("Post-failure TA echo: %s\n", send_ping(app, 1, 7) ? "FAIL" : "PASS");
		goto out;
	}
	rc = 0;
out:
	qcomtee_memory_object_release(smo);
	return rc;
}

static void unload_ta(struct qcomtee_object *app)
{
	struct qcomtee_param params[1];
	qcomtee_result_t result = -1;

	(void)params;
	if (qcomtee_object_invoke(app, IQSEEComCompat_OP_unload, NULL, 0,
				  &result) || result != QCOMTEE_OK)
		MSG("  unload: result %d (may need a clean round)\n", result);
	else
		MSG("  unloaded\n");
}

/* Qualcomm's IAppLoader (UID 3), IAppController ops 1/2 and
 * IAppLegacyTest op 0. Only exercise pointer-free echo on this route. */
static int check_legacy(struct qcomtee_object *env, unsigned char *image,
                        size_t image_size)
{
	struct qcomtee_object *loader = get_service(env, 3);
	struct qcomtee_object *controller, *app;
	struct qcomtee_param p[2] = {0};
	qcomtee_result_t result = -1;
	int rc = -1;
	if (!loader) return -1;
	p[0].attr = QCOMTEE_UBUF_INPUT;
	p[0].ubuf.addr = image; p[0].ubuf.size = image_size;
	p[1].attr = QCOMTEE_OBJREF_OUTPUT;
	if (qcomtee_object_invoke(loader, 0, p, 2, &result)) goto done;
	MSG("  legacy loadFromBuffer: %d\n", result);
	if (result) goto done;
	controller = p[1].object;
	p[0].attr = QCOMTEE_OBJREF_OUTPUT;
	if (!qcomtee_object_invoke(controller, 2, p, 1, &result) && !result) {
		app = p[0].object;
		legacy_transport = 1;
		rc = send_ping(app, 1, 7) || send_ping(app, 1, 3);
		qcomtee_object_refs_dec(app);
	} else MSG("  legacy getAppObject failed: %d\n", result);
	if (qcomtee_object_invoke(controller, 1, NULL, 0, &result) || result) {
		MSG("  legacy unload failed: %d\n", result);
		rc = -1;
	} else MSG("  legacy unloaded\n");
	qcomtee_object_refs_dec(controller);
done:
	qcomtee_object_refs_dec(loader);
	return rc;
}

int main(int argc, char **argv)
{
	int protocol = argc == 3 && !strcmp(argv[2], "--protocol");
	int transport = argc == 3 && !strcmp(argv[2], "--transport-check");
	int legacy = argc == 3 && !strcmp(argv[2], "--legacy-ping");
	sensor_probe = argc == 3 && (!strcmp(argv[2], "--qseecom-sensor") ||
	                            !strcmp(argv[2], "--qseecom-sensor-nohello"));
	hello_probe = (argc == 3 && !strcmp(argv[2], "--qseecom-sensor")) ||
	              (argc == 3 && !strcmp(argv[2], "--qseecom-hello"));
	int native = sensor_probe || hello_probe || (argc == 3 && !strcmp(argv[2], "--qseecom-native-protocol"));
	int qseecom = argc == 3 && !strcmp(argv[2], "--qseecom-protocol");
	setvbuf(stdout, NULL, _IOLBF, 0);
	struct qcomtee_object *root, *env, *loader, *app;
	unsigned char *image;
	size_t image_size;
	uint32_t operand = 7;
	uint32_t cmd_id = CMD_PING;
	int rc = 1;

	if (argc < 2) {
		fprintf(stderr,
			"usage: %s <firmware-dir> [operand] [cmd_id]\n"
			"  or: <firmware-dir> --protocol | --qseecom-protocol | --qseecom-native-protocol | --legacy-ping | --transport-check\n",
			argv[0]);
		return 2;
	}
	if (argc >= 3 && !protocol && !transport && !legacy && !qseecom && !native)
		operand = (uint32_t)strtoul(argv[2], NULL, 0);
	if (argc >= 4)
		cmd_id = (uint32_t)strtoul(argv[3], NULL, 0);
	if (cmd_id != 0 && cmd_id != CMD_PING) {
		fprintf(stderr, "Only pointer-free commands 0 and 1 are supported.\n");
		return 2;
	}

	MSG("egisfp-load: assembling %s from %s\n", EGIS_APP_NAME, argv[1]);
	image = assemble_ta(argv[1], &image_size);
	if (!image)
		return 1;
	MSG("  image assembled, %zu bytes\n", image_size);

	root = get_root();
	if (root == QCOMTEE_OBJECT_NULL)
		goto out_image;
	MSG("  root object + supplicant up\n");

	if (native) {
		if (!egis_qseecom_load())
			rc = check_protocol(root, QCOMTEE_OBJECT_NULL);
		MSG("%s: native QSEECom protocol checks\n", rc ? "FAILED" : "SUCCESS");
		egis_qseecom_close();
		goto out_root;
	}

	env = get_client_env(root);
	if (env == QCOMTEE_OBJECT_NULL)
		goto out_root;
	if (legacy) {
		rc = check_legacy(env, image, image_size);
		goto out_env;
	}

	loader = get_service(env, CQSEEComCompatAppLoader_UID);
	if (loader == QCOMTEE_OBJECT_NULL)
		goto out_env;
	MSG("  opened QSEEComCompat app loader (UID %u)\n",
	    CQSEEComCompatAppLoader_UID);

	app = load_ta(loader, image, image_size);
	if (app == QCOMTEE_OBJECT_NULL)
		goto out_loader;
	if (qseecom && egis_qseecom_open())
		goto out_app;

	if (transport) {
		/* Known pointer-free ping only. Test whether the legacy compat
		 * service permits omission of redundant in/out copies. */
		for (unsigned int i = 0; i < 4; i++) {
			response_input_size = (i & 1) ? 0 : RSP_SIZE;
			request_output_size = (i & 2) ? 0 : REQ_SIZE;
			MSG("transport case %u: reqIn=%u rspIn=%zu reqOut=%zu rspOut=%u\n",
			    i, REQ_SIZE, response_input_size, request_output_size, RSP_SIZE);
			int test_rc = send_ping(app, 1, 7);
			MSG("transport case %u: %s\n", i, test_rc ? "FAIL" : "PASS");
			if (!test_rc) rc = 0;
		}
	} else {
		rc = (protocol || qseecom) ? check_protocol(root, app) : send_ping(app, cmd_id, operand);
	}
	if (rc == 0)
		MSG("SUCCESS: selected TA protocol checks passed.\n");
	else
		MSG("FAILED: TA protocol check; no hardware/enrollment claim.\n");

out_app:
	egis_qseecom_close();
	unload_ta(app);
	qcomtee_object_refs_dec(app);
out_loader:
	qcomtee_object_refs_dec(loader);
out_env:
	qcomtee_object_refs_dec(env);
out_root:
	qcomtee_object_refs_dec(root);
out_image:
	free(image);
	return rc ? 1 : 0;
}
