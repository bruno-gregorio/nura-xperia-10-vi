/* SPDX-License-Identifier: BSD-3-Clause
 * Client for the QSEECom TEE UAPI carried by this project's kernel.
 * Opens an already loaded TA; never loads firmware or registers listeners.
 */
#include <fcntl.h>
#include <linux/tee.h>
#include <sys/mman.h>
#include <unistd.h>

struct egis_qseecom {
	int fd, shm_fd;
	int32_t shm_id;
	uint32_t session;
	int session_open;
	unsigned char *memory;
};

static struct egis_qseecom qsee = { .fd = -1, .shm_fd = -1 };
static struct egis_qseecom qsee_loader = { .fd = -1, .shm_fd = -1 };
#define EGIS_QSEE_MEMORY_SIZE 12288
#define EGIS_QSEE_RSP_OFFSET 4096
#define EGIS_QSEE_DATA_OFFSET 8192
/* Local out-of-tree UAPI identifier, verified against the kernel patch. */
#define EGIS_TEE_IMPL_QSEECOM 5

static void egis_qseecom_close_one(struct egis_qseecom *state)
{
	if (state->session_open) {
		struct tee_ioctl_close_session_arg arg = { .session = state->session };
		if (ioctl(state->fd, TEE_IOC_CLOSE_SESSION, &arg))
			perror("QSEECom close session");
	}
	if (state->memory) munmap(state->memory, EGIS_QSEE_MEMORY_SIZE);
	if (state->shm_fd >= 0) close(state->shm_fd);
	if (state->fd >= 0) close(state->fd);
	*state = (struct egis_qseecom) { .fd = -1, .shm_fd = -1 };
}

static int egis_qseecom_open_one(struct egis_qseecom *state, int privileged, const char *name)
{
	struct tee_ioctl_shm_alloc_data alloc = { .size = EGIS_QSEE_MEMORY_SIZE };
	struct tee_ioctl_open_session_arg *arg;
	struct tee_ioctl_buf_data buf;

	size_t size = sizeof(*arg) + sizeof(struct tee_ioctl_param);
	int rc = -1;

	for (unsigned int i = 0; i < 16; i++) {
		char path[32];
		struct tee_ioctl_version_data version = {0};
		snprintf(path, sizeof(path), privileged ? "/dev/teepriv%u" : "/dev/tee%u", i);
		int fd = open(path, O_RDWR | O_CLOEXEC);
		if (fd < 0) continue;
		if (!ioctl(fd, TEE_IOC_VERSION, &version) &&
		    version.impl_id == EGIS_TEE_IMPL_QSEECOM) {
			state->fd = fd;
			printf("  QSEECom transport: %s\n", path);
			break;
		}
		close(fd);
	}
	if (state->fd < 0) {
		fprintf(stderr, "QSEECom TEE transport is not present\n");
		return -1;
	}
	state->shm_fd = ioctl(state->fd, TEE_IOC_SHM_ALLOC, &alloc);
	if (state->shm_fd < 0) goto fail;
	state->shm_id = alloc.id;
	void *memory = mmap(NULL, EGIS_QSEE_MEMORY_SIZE, PROT_READ | PROT_WRITE,
	                    MAP_SHARED, state->shm_fd, 0);
	if (memory == MAP_FAILED) goto fail;
	state->memory = memory;
	memcpy(state->memory, name, strlen(name) + 1);
	arg = calloc(1, size);
	if (!arg) goto fail;
	arg->num_params = 1;
	arg->params[0] = (struct tee_ioctl_param) {
		.attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INPUT,
		.a = 0, .b = strlen(name) + 1, .c = state->shm_id,
	};
	buf = (struct tee_ioctl_buf_data) {
		.buf_ptr = (uintptr_t)arg, .buf_len = size,
	};
	if (!ioctl(state->fd, TEE_IOC_OPEN_SESSION, &buf) && !arg->ret) {
		state->session = arg->session;
		state->session_open = 1;
		rc = 0;
	} else {
		fprintf(stderr, "QSEECom open: errno=%d ret=%u origin=%u\n",
		        errno, arg->ret, arg->ret_origin);
	}
	free(arg);
	if (!rc) return 0;
fail:
	egis_qseecom_close_one(state);
	return -1;
}

static void egis_qseecom_close(void)
{
	/* The client releases its app reference before the owning loader. */
	egis_qseecom_close_one(&qsee);
	egis_qseecom_close_one(&qsee_loader);
}

static int egis_qseecom_open(void)
{
	return egis_qseecom_open_one(&qsee, 0, "fingerprint");
}

static int egis_qseecom_load(void)
{
	/* Kernel request_firmware loads only egisap64.mdt and its signed
	 * segments. Closing this owner session unloads the app. No listener
	 * or secure-storage service is registered by this client.
	 */
	if (egis_qseecom_open_one(&qsee_loader, 1, "egisap64"))
		return -1;
	if (egis_qseecom_open_one(&qsee, 0, "egisap64")) {
		egis_qseecom_close();
		return -1;
	}
	return 0;
}

static int egis_qseecom_send(const unsigned char *request, size_t request_size,
                            unsigned char *response, size_t response_size,
                            void *data, size_t data_size)
{
	unsigned int count = data ? 4 : 2;
	size_t size = sizeof(struct tee_ioctl_invoke_arg) +
	              count * sizeof(struct tee_ioctl_param);
	struct tee_ioctl_invoke_arg *arg;
	struct tee_ioctl_buf_data buf;
	int rc = -1;
	if (!qsee.session_open || request_size > 4096 || response_size > 4096 ||
	    data_size > 4096 || (!data && data_size)) return -1;
	arg = calloc(1, size);
	if (!arg) return -1;
	memcpy(qsee.memory, request, request_size);
	memcpy(qsee.memory + EGIS_QSEE_RSP_OFFSET, response, response_size);
	arg->session = qsee.session;
	arg->num_params = count;
	arg->params[0] = (struct tee_ioctl_param) {
		.attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INPUT,
		.a = 0, .b = request_size, .c = qsee.shm_id,
	};
	arg->params[1] = (struct tee_ioctl_param) {
		.attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_OUTPUT,
		.a = EGIS_QSEE_RSP_OFFSET, .b = response_size, .c = qsee.shm_id,
	};
	if (data) {
		memcpy(qsee.memory + EGIS_QSEE_DATA_OFFSET, data, data_size);
		arg->params[2] = (struct tee_ioctl_param) {
			.attr = TEE_IOCTL_PARAM_ATTR_TYPE_VALUE_INPUT, .a = 8, .b = 8,
		};
		arg->params[3] = (struct tee_ioctl_param) {
			.attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INOUT,
			.a = EGIS_QSEE_DATA_OFFSET, .b = data_size, .c = qsee.shm_id,
		};
	}
	buf = (struct tee_ioctl_buf_data) { .buf_ptr = (uintptr_t)arg, .buf_len = size };
	if (!ioctl(qsee.fd, TEE_IOC_INVOKE, &buf) && !arg->ret &&
	    arg->params[1].b == response_size &&
	    (!data || arg->params[3].b == data_size)) {
		memcpy(response, qsee.memory + EGIS_QSEE_RSP_OFFSET, response_size);
		if (data) memcpy(data, qsee.memory + EGIS_QSEE_DATA_OFFSET, data_size);
		rc = 0;
	} else {
		fprintf(stderr, "QSEECom invoke: errno=%d ret=%u origin=%u\n",
		        errno, arg->ret, arg->ret_origin);
	}
	free(arg);
	return rc;
}
