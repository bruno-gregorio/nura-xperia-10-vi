/* SPDX-License-Identifier: BSD-3-Clause */
#ifndef __TA_RAW_H__
#define __TA_RAW_H__

#include <stddef.h>
#include <stdint.h>

/* The pdx246's is 8 MiB; anything far larger is not a trim area */
#define TA_RAW_MAX_SIZE		(64 << 20)

typedef int (*ta_raw_unit_fn)(void *cookie, uint32_t partition, uint32_t id,
			      const void *data, uint32_t size);

int ta_raw_parse(const uint8_t *buf, size_t len, ta_raw_unit_fn fn,
		 void *cookie);

#endif
