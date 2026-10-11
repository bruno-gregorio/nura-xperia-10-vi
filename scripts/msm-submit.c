// SPDX-License-Identifier: GPL-2.0
/*
 * msm-submit: run the smallest possible job on an Adreno through drm/msm,
 * and check that the GPU did it.
 *
 *   msm-submit [count [node]]
 *
 * It opens the render node (/dev/dri/renderD128 unless told otherwise),
 * which is what makes drm/msm load the GPU: firmware, GMU boot, zap shader
 * and CP init, so the firmware has to be in place first. It prints the GPU's
 * IDs, then submits count command buffers, 1 unless told otherwise, each a
 * single CP_MEM_WRITE of a new value to a buffer, and waits on each fence for
 * up to two seconds. A job passes when its fence signals and the buffer
 * holds its value; the last line says how many did. The fence needs the CP's
 * end-of-submit event and its interrupt, so a pass covers the ringbuffer, the
 * IB path, the SMMU mapping of both buffers and the IRQ.
 *
 * It exists for the initramfs shell, which has no Mesa. Built like vblank.c,
 * against the kernel's nolibc:
 *
 *   aarch64-linux-gnu-gcc -Os -static -nostdlib -fno-asynchronous-unwind-tables \
 *       -Wl,-z,max-page-size=4096 \
 *       -include out/linux/tools/include/nolibc/nolibc.h \
 *       -o out/tools/msm-submit scripts/msm-submit.c -lgcc
 */

/* include/uapi/drm/msm_drm.h */
#define MSM_PIPE_3D0		0x10
#define MSM_PARAM_GPU_ID	0x01
#define MSM_PARAM_GMEM_SIZE	0x02
#define MSM_PARAM_CHIP_ID	0x03
#define MSM_PARAM_MAX_FREQ	0x04
#define MSM_PARAM_FAULTS	0x09
#define MSM_BO_WC		0x00020000
#define MSM_INFO_GET_OFFSET	0x00
#define MSM_INFO_GET_IOVA	0x01
#define MSM_SUBMIT_CMD_BUF	0x0001
#define MSM_SUBMIT_BO_READ	0x0001
#define MSM_SUBMIT_BO_WRITE	0x0002

struct msm_param {
	unsigned int pipe;
	unsigned int param;
	unsigned long long value;
	unsigned int len;
	unsigned int pad;
};

struct msm_gem_new {
	unsigned long long size;
	unsigned int flags;
	unsigned int handle;
};

struct msm_gem_info {
	unsigned int handle;
	unsigned int info;
	unsigned long long value;
	unsigned int len;
	unsigned int pad;
};

struct msm_submit_cmd {
	unsigned int type;
	unsigned int submit_idx;
	unsigned int submit_offset;
	unsigned int size;
	unsigned int pad;
	unsigned int nr_relocs;
	unsigned long long relocs;
};

struct msm_submit_bo {
	unsigned int flags;
	unsigned int handle;
	unsigned long long presumed;
};

struct msm_submit {
	unsigned int flags;
	unsigned int fence;
	unsigned int nr_bos;
	unsigned int nr_cmds;
	unsigned long long bos;
	unsigned long long cmds;
	int fence_fd;
	unsigned int queueid;
	unsigned long long in_syncobjs;
	unsigned long long out_syncobjs;
	unsigned int nr_in_syncobjs;
	unsigned int nr_out_syncobjs;
	unsigned int syncobj_stride;
	unsigned int pad;
};

struct msm_wait_fence {
	unsigned int fence;
	unsigned int flags;
	long long tv_sec;
	long long tv_nsec;
	unsigned int queueid;
};

#define DRM_IOWR(nr, type)	(0xc0000000 | (sizeof(type) << 16) | ('d' << 8) | (0x40 + (nr)))
#define DRM_IOW(nr, type)	(0x40000000 | (sizeof(type) << 16) | ('d' << 8) | (0x40 + (nr)))
#define IOCTL_GET_PARAM		DRM_IOWR(0x00, struct msm_param)
#define IOCTL_GEM_NEW		DRM_IOWR(0x02, struct msm_gem_new)
#define IOCTL_GEM_INFO		DRM_IOWR(0x03, struct msm_gem_info)
#define IOCTL_GEM_SUBMIT	DRM_IOWR(0x06, struct msm_submit)
#define IOCTL_WAIT_FENCE	DRM_IOW(0x07, struct msm_wait_fence)

/* drivers/gpu/drm/msm/adreno/adreno_gpu.h */
#define CP_TYPE7_PKT		0x70000000
#define CP_MEM_WRITE		61

static unsigned int parity(unsigned int val)
{
	return (0x9669 >> (0xf & (val ^ (val >> 4) ^ (val >> 8) ^
		(val >> 12) ^ (val >> 16) ^ (val >> 20) ^ (val >> 24) ^
		(val >> 28)))) & 1;
}

static unsigned int pkt7(unsigned int opcode, unsigned int cnt)
{
	return CP_TYPE7_PKT | cnt | (parity(cnt) << 15) |
		((opcode & 0x7f) << 16) | (parity(opcode) << 23);
}

static unsigned long number(const char *s)
{
	unsigned long v = 0;

	while (*s >= '0' && *s <= '9')
		v = v * 10 + *s++ - '0';
	return v;
}

static unsigned long long param(int fd, unsigned int p)
{
	struct msm_param req = { .pipe = MSM_PIPE_3D0, .param = p };

	if (ioctl(fd, IOCTL_GET_PARAM, &req) < 0) {
		printf("msm-submit: param %u: errno %d\n", p, errno);
		return 0;
	}
	return req.value;
}

int main(int argc, char **argv)
{
	unsigned long count = argc > 1 ? number(argv[1]) : 1;
	const char *node = argc > 2 ? argv[2] : "/dev/dri/renderD128";
	struct msm_gem_new bo = { .size = 4096, .flags = MSM_BO_WC };
	struct msm_gem_info info = { 0 };
	unsigned long long iova;
	volatile unsigned int *map;
	unsigned long i, passed = 0;
	int fd;

	fd = open(node, O_RDWR);
	if (fd < 0) {
		printf("msm-submit: open %s: errno %d\n", node, errno);
		return 1;
	}
	printf("msm-submit: gpu_id %llu chip_id 0x%llx gmem %llu max_freq %llu faults %llu\n",
	       param(fd, MSM_PARAM_GPU_ID), param(fd, MSM_PARAM_CHIP_ID),
	       param(fd, MSM_PARAM_GMEM_SIZE), param(fd, MSM_PARAM_MAX_FREQ),
	       param(fd, MSM_PARAM_FAULTS));

	if (ioctl(fd, IOCTL_GEM_NEW, &bo) < 0) {
		printf("msm-submit: gem_new: errno %d\n", errno);
		return 1;
	}
	info.handle = bo.handle;
	info.info = MSM_INFO_GET_IOVA;
	if (ioctl(fd, IOCTL_GEM_INFO, &info) < 0) {
		printf("msm-submit: iova: errno %d\n", errno);
		return 1;
	}
	iova = info.value;
	info.info = MSM_INFO_GET_OFFSET;
	info.value = 0;
	if (ioctl(fd, IOCTL_GEM_INFO, &info) < 0) {
		printf("msm-submit: offset: errno %d\n", errno);
		return 1;
	}
	map = mmap(NULL, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, info.value);
	if (map == MAP_FAILED) {
		printf("msm-submit: mmap: errno %d\n", errno);
		return 1;
	}
	printf("msm-submit: buffer at iova 0x%llx\n", iova);

	for (i = 0; i < count; i++) {
		unsigned int value = 0xc0ffee00 + (unsigned int)i;
		struct msm_submit_bo sbo = {
			.flags = MSM_SUBMIT_BO_READ | MSM_SUBMIT_BO_WRITE,
			.handle = bo.handle,
		};
		struct msm_submit_cmd cmd = {
			.type = MSM_SUBMIT_CMD_BUF,
			.size = 4 * 4,
		};
		struct msm_submit submit = {
			.flags = MSM_PIPE_3D0,
			.nr_bos = 1,
			.nr_cmds = 1,
			.bos = (unsigned long)&sbo,
			.cmds = (unsigned long)&cmd,
			.fence_fd = -1,
		};
		struct msm_wait_fence wait = { 0 };
		struct timespec now;

		/* The command buffer is the first 16 bytes, the target at 2 KiB */
		map[512] = 0;
		map[0] = pkt7(CP_MEM_WRITE, 3);
		map[1] = (unsigned int)(iova + 2048);
		map[2] = (unsigned int)((iova + 2048) >> 32);
		map[3] = value;

		if (ioctl(fd, IOCTL_GEM_SUBMIT, &submit) < 0) {
			printf("msm-submit: job %lu: submit: errno %d\n", i, errno);
			break;
		}
		clock_gettime(CLOCK_MONOTONIC, &now);
		wait.fence = submit.fence;
		wait.tv_sec = now.tv_sec + 2;
		wait.tv_nsec = now.tv_nsec;
		if (ioctl(fd, IOCTL_WAIT_FENCE, &wait) < 0) {
			printf("msm-submit: job %lu: fence %u: errno %d, buffer 0x%x\n",
			       i, submit.fence, errno, map[512]);
			break;
		}
		if (map[512] != value) {
			printf("msm-submit: job %lu: fence %u signalled, buffer 0x%x, want 0x%x\n",
			       i, submit.fence, map[512], value);
			break;
		}
		if (i == 0)
			printf("msm-submit: job 0: fence %u, buffer 0x%x\n",
			       submit.fence, map[512]);
		passed++;
	}
	printf("msm-submit: %lu of %lu jobs passed, faults %llu\n", passed, count,
	       param(fd, MSM_PARAM_FAULTS));
	return passed == count ? 0 : 1;
}
