/* SPDX-License-Identifier: BSD-3-Clause */
#ifndef __TA_H__
#define __TA_H__

#include <stdbool.h>
#include <stdint.h>

/* Partitions as libta numbers them: 1 is the trim area, 2 is MiscTA */
#define TA_PARTITION_TRIM	1
#define TA_PARTITION_MISC	2

struct ta_unit {
	uint32_t partition;
	uint32_t id;
	uint32_t size;
	uint8_t *data;
	/* Written by a client since we started; never on the partition */
	bool dirty;
	struct ta_unit *next;
};

int ta_store_load(const char *path);
int ta_store_load_dir(const char *dir);
void ta_store_free(void);

struct ta_unit *ta_store_find(uint32_t partition, uint32_t id);
struct ta_unit *ta_store_next(uint32_t partition, const struct ta_unit *after);
int ta_store_put(uint32_t partition, uint32_t id, const void *data,
		 uint32_t size, bool append);
int ta_store_delete(uint32_t partition, uint32_t id);

#endif
