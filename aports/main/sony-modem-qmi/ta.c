// SPDX-License-Identifier: BSD-3-Clause
/*
 * The units of a trim area, held in memory.
 *
 * They are read once, at start, from the raw partition (opened read-only) and
 * from an optional directory of overrides, and from then on only this copy
 * changes.
 */
#include <sys/stat.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "ta.h"
#include "ta_raw.h"

static struct ta_unit *units;

struct ta_unit *ta_store_find(uint32_t partition, uint32_t id)
{
	struct ta_unit *u;

	for (u = units; u; u = u->next)
		if (u->partition == partition && u->id == id)
			return u;

	return NULL;
}

/* Units are kept sorted by partition and id, which is the order this walks */
struct ta_unit *ta_store_next(uint32_t partition, const struct ta_unit *after)
{
	struct ta_unit *u = after ? after->next : units;

	for (; u; u = u->next)
		if (u->partition == partition)
			return u;

	return NULL;
}

static int set_data(struct ta_unit *u, const void *data, uint32_t size,
		    bool append)
{
	uint32_t total = append ? u->size + size : size;
	uint8_t *p;

	if (append && total < u->size)
		return -EOVERFLOW;

	p = malloc(total ? total : 1);
	if (!p)
		return -ENOMEM;
	if (append)
		memcpy(p, u->data, u->size);
	memcpy(p + (append ? u->size : 0), data, size);

	free(u->data);
	u->data = p;
	u->size = total;

	return 0;
}

static int store_put(uint32_t partition, uint32_t id, const void *data,
		     uint32_t size, bool append, bool dirty)
{
	struct ta_unit **p = &units;
	struct ta_unit *u;
	int ret;

	while (*p && ((*p)->partition < partition ||
		      ((*p)->partition == partition && (*p)->id < id)))
		p = &(*p)->next;

	u = *p;
	if (!u || u->partition != partition || u->id != id) {
		u = calloc(1, sizeof(*u));
		if (!u)
			return -ENOMEM;
		u->partition = partition;
		u->id = id;
		u->next = *p;
		*p = u;
	}

	ret = set_data(u, data, size, append && u->data);
	if (ret)
		return ret;
	u->dirty |= dirty;

	return 0;
}

int ta_store_put(uint32_t partition, uint32_t id, const void *data,
		 uint32_t size, bool append)
{
	return store_put(partition, id, data, size, append, true);
}

int ta_store_delete(uint32_t partition, uint32_t id)
{
	struct ta_unit **p = &units;
	struct ta_unit *u;

	for (; (u = *p); p = &u->next) {
		if (u->partition == partition && u->id == id) {
			*p = u->next;
			free(u->data);
			free(u);
			return 0;
		}
	}

	return -ENOENT;
}

void ta_store_free(void)
{
	struct ta_unit *u;

	while ((u = units)) {
		units = u->next;
		free(u->data);
		free(u);
	}
}

static int add_unit(void *cookie, uint32_t partition, uint32_t id,
		    const void *data, uint32_t size)
{
	return store_put(partition, id, data, size, false, false);
}

int ta_store_load(const char *path)
{
	struct stat st;
	uint8_t *buf;
	ssize_t n;
	off_t len;
	int ret;
	int fd;

	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0) {
		fprintf(stderr, "failed to open %s: %s\n", path, strerror(errno));
		return -1;
	}

	if (fstat(fd, &st) < 0)
		goto err_close;
	len = S_ISBLK(st.st_mode) ? lseek(fd, 0, SEEK_END) : st.st_size;
	if (len <= 0 || len > TA_RAW_MAX_SIZE) {
		fprintf(stderr, "%s: unexpected size %lld\n", path,
			(long long)len);
		close(fd);
		return -1;
	}

	buf = malloc(len);
	if (!buf)
		goto err_close;
	n = pread(fd, buf, len, 0);
	close(fd);
	if (n != len) {
		fprintf(stderr, "%s: short read\n", path);
		free(buf);
		return -1;
	}

	ret = ta_raw_parse(buf, len, add_unit, NULL);
	free(buf);
	if (ret < 0) {
		fprintf(stderr, "%s: not a trim area this understands\n", path);
		return -1;
	}

	printf("%s: %d units\n", path, ret);

	return 0;

err_close:
	fprintf(stderr, "%s: %s\n", path, strerror(errno));
	close(fd);
	return -1;
}

static int load_file(const char *path, uint32_t partition, uint32_t id)
{
	uint8_t buf[0x10000];
	ssize_t n;
	int fd;

	fd = open(path, O_RDONLY | O_CLOEXEC);
	if (fd < 0)
		return -errno;
	n = read(fd, buf, sizeof(buf));
	close(fd);
	if (n < 0)
		return -errno;

	printf("%s: unit %u/%u, %zd bytes, in place of the partition's\n",
	       path, partition, id, n);

	return store_put(partition, id, buf, n, false, false);
}

/* dir/<partition>/<unit>, both decimal, as libta numbers them */
int ta_store_load_dir(const char *dir)
{
	char path[4096];
	struct dirent *de;
	unsigned long id;
	char *end;
	DIR *d;
	int partition;
	int ret;

	for (partition = TA_PARTITION_TRIM; partition <= TA_PARTITION_MISC;
	     partition++) {
		snprintf(path, sizeof(path), "%s/%d", dir, partition);
		d = opendir(path);
		if (!d)
			continue;

		while ((de = readdir(d))) {
			id = strtoul(de->d_name, &end, 10);
			if (*end || end == de->d_name)
				continue;
			snprintf(path, sizeof(path), "%s/%d/%s", dir,
				 partition, de->d_name);
			ret = load_file(path, partition, id);
			if (ret < 0)
				fprintf(stderr, "%s: %s\n", path,
					strerror(-ret));
		}
		closedir(d);
	}

	return 0;
}
