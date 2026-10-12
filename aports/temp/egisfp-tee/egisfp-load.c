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
//      pointer QTEE must fix up and which this tool refuses to send.
//   6. unload, so the single-residency "fingerprint" app name is freed.
//
// It never touches RPMB and registers no listeners.
//
// On this phone, load and unload over UID 122 work (QTEE accepts Sony's
// chain), and sendRequest round-trips. Command 0x01 leaves the response
// buffer untouched, though: its "len*10" is a C return value the compat path
// does not surface, so 0x01 cannot confirm the in-TA handler ran. Real data
// needs the 0xE0/BIX path and its pointer fix-up (see docs/05-status.md).
//
// Usage: egisfp-load <firmware-dir> [operand] [cmd_id]
//   <firmware-dir> holds egisap64.b00 .. egisap64.b08.
//   [operand] is the u32 at request offset 8 (default 7).
//   [cmd_id]  is the top command (default 0x01); 0xE0 is refused.

#include <errno.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>

#include <qcomtee_object_types.h>

#define DEV_TEE "/dev/tee0"

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
 * u32 status @16 (0 on success). We give each buffer room to spare.
 */
#define REQ_SIZE 64
#define RSP_SIZE 64
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

	sup = calloc(1, sizeof(*sup));
	if (!sup)
		return QCOMTEE_OBJECT_NULL;

	root = qcomtee_object_root_init(DEV_TEE, tee_call, supplicant_release,
					sup);
	if (root == QCOMTEE_OBJECT_NULL) {
		MSG("  cannot open %s\n", DEV_TEE);
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
	qcomtee_result_t result;

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
	qcomtee_result_t result;

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
	qcomtee_result_t result;
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

static int send_ping(struct qcomtee_object *app, uint32_t cmd_id,
		     uint32_t operand)
{
	struct qcomtee_param params[10];
	qcomtee_result_t result;
	unsigned char req[REQ_SIZE];
	unsigned char rsp[RSP_SIZE];
	uint32_t is64 = 1;              /* egisap64 is ELFCLASS64 */
	uint32_t embedded_none = 0;    /* no embedded pointers for 0x01 */
	uint32_t res_val, status;

	/* request: cmd_id @0, operand @8; rest a sentinel so we can see what the
	 * TA leaves untouched. The response buffer is a sentinel too, so a byte
	 * that comes back != 0xAA is one QTEE/the TA actually wrote.
	 */
	memset(req, 0xAA, sizeof(req));
	memset(rsp, 0xAA, sizeof(rsp));
	memcpy(req + 0, &cmd_id, 4);
	memset(req + 4, 0, 4);
	memcpy(req + 8, &operand, 4);
	memset(req + 12, 0, 4);

	/* IQSEEComCompat.sendRequest, ObjectCounts_pack(4, 2, 4, 0):
	 * in  bufs: reqIn, rspIn, embeddedBufOffsets, is64
	 * out bufs: reqOut, rspOut   (same storage as reqIn/rspIn, per vendor)
	 * in  objs: smo1..smo4       (all NULL - no shared memory for 0x01)
	 */
	params[0].attr = QCOMTEE_UBUF_INPUT;  params[0].ubuf.addr = req; params[0].ubuf.size = sizeof(req);
	params[1].attr = QCOMTEE_UBUF_INPUT;  params[1].ubuf.addr = rsp; params[1].ubuf.size = sizeof(rsp);
	params[2].attr = QCOMTEE_UBUF_INPUT;  params[2].ubuf.addr = &embedded_none; params[2].ubuf.size = 0;
	params[3].attr = QCOMTEE_UBUF_INPUT;  params[3].ubuf.addr = &is64; params[3].ubuf.size = sizeof(is64);
	params[4].attr = QCOMTEE_UBUF_OUTPUT; params[4].ubuf.addr = req; params[4].ubuf.size = sizeof(req);
	params[5].attr = QCOMTEE_UBUF_OUTPUT; params[5].ubuf.addr = rsp; params[5].ubuf.size = sizeof(rsp);
	params[6].attr = QCOMTEE_OBJREF_INPUT; params[6].object = QCOMTEE_OBJECT_NULL;
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

	/* reqOut/rspOut carry the lengths the TA actually produced. */
	MSG("  sendRequest ok: reqOut_len=%zu rspOut_len=%zu\n",
	    params[4].ubuf.size, params[5].ubuf.size);
	hexdump("reqOut", req, sizeof(req));
	hexdump("rspOut", rsp, sizeof(rsp));

	memcpy(&res_val, rsp + 0, 4);
	memcpy(&status, rsp + 16, 4);
	MSG("  cmd 0x%02x: operand=%u -> rsp[0]=%u (operand*10=%u), rsp[16]=%u\n",
	    cmd_id, operand, res_val, operand * 10, status);

	return (res_val == operand * 10) ? 0 : -1;
}

static void unload_ta(struct qcomtee_object *app)
{
	struct qcomtee_param params[1];
	qcomtee_result_t result;

	(void)params;
	if (qcomtee_object_invoke(app, IQSEEComCompat_OP_unload, NULL, 0,
				  &result) || result != QCOMTEE_OK)
		MSG("  unload: result %d (may need a clean round)\n", result);
	else
		MSG("  unloaded\n");
}

int main(int argc, char **argv)
{
	struct qcomtee_object *root, *env, *loader, *app;
	unsigned char *image;
	size_t image_size;
	uint32_t operand = 7;
	uint32_t cmd_id = CMD_PING;
	int rc = 1;

	if (argc < 2) {
		fprintf(stderr,
			"usage: %s <firmware-dir> [operand] [cmd_id]\n",
			argv[0]);
		return 2;
	}
	if (argc >= 3)
		operand = (uint32_t)strtoul(argv[2], NULL, 0);
	if (argc >= 4)
		cmd_id = (uint32_t)strtoul(argv[3], NULL, 0);

	MSG("egisfp-load: assembling %s from %s\n", EGIS_APP_NAME, argv[1]);
	image = assemble_ta(argv[1], &image_size);
	if (!image)
		return 1;
	MSG("  image assembled, %zu bytes\n", image_size);

	root = get_root();
	if (root == QCOMTEE_OBJECT_NULL)
		goto out_image;
	MSG("  root object + supplicant up\n");

	env = get_client_env(root);
	if (env == QCOMTEE_OBJECT_NULL)
		goto out_root;

	loader = get_service(env, CQSEEComCompatAppLoader_UID);
	if (loader == QCOMTEE_OBJECT_NULL)
		goto out_env;
	MSG("  opened QSEEComCompat app loader (UID %u)\n",
	    CQSEEComCompatAppLoader_UID);

	app = load_ta(loader, image, image_size);
	if (app == QCOMTEE_OBJECT_NULL)
		goto out_loader;

	/* Safety belt: top command 0xE0 (the ETS/BIX message) carries a pointer
	 * at request offset 8 that TrustZone must fix up; a wrong one resets the
	 * phone. It must not be sent through this flat-buffer path. Refuse it
	 * until the embeddedBufOffsets fix-up is built and proven.
	 */
	if (cmd_id == 0xE0) {
		MSG("refusing cmd 0x%02x: the ETS pointer fix-up is not proven "
		    "yet (would risk a reset)\n", cmd_id);
		rc = 2;
	} else {
		rc = send_ping(app, cmd_id, operand);
		if (rc == 0)
			MSG("SUCCESS: egisap64 echoed operand*10 for command "
			    "0x%02x.\n", cmd_id);
	}

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
	return rc;
}
