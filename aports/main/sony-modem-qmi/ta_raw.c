// SPDX-License-Identifier: BSD-3-Clause
/*
 * The raw trim area, as Sony's tad (ta_raw.c) lays it out.
 *
 * The partition is a run of erase blocks. A block in use starts with
 *
 *	0x0  u32 magic 0x3bf8e9c1
 *	0x4  u32 Adler-32 of the block's used bytes from 0x8 on
 *	0x8  u8  format version, 1 to 3
 *	0x9  u8  logical block number
 *	0xa  u8  partition, 1 or 2
 *	0xb  u8  size class: 0xff for the whole block, else (s << 11) + 0x800
 *
 * and its units follow from 0xc, each a 16-byte header (u32 id, u32 length,
 * u32 magic, four bytes nothing reads) and the data, padded to four bytes.
 * The walk ends at the first header without the magic. All little-endian.
 *
 * tad is told the block size; we are not, so we try 512 kB and 128 kB and
 * keep whichever finds more valid blocks. This phone's is 512 kB.
 */
#include <string.h>

#include "ta_raw.h"

#define TA_MAGIC	0x3bf8e9c1
#define TA_BLOCK_HDR	0x0c
#define TA_UNIT_HDR	0x10
#define TA_MAX_BLOCKS	256

struct block {
	const uint8_t *data;
	size_t used;
	uint8_t version;
	uint8_t number;
	uint8_t partition;
};

static uint32_t get_le32(const uint8_t *p)
{
	return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24;
}

static uint32_t adler32(const uint8_t *p, size_t n)
{
	uint32_t a = 1, b = 0;

	while (n--) {
		a = (a + *p++) % 65521;
		b = (b + a) % 65521;
	}

	return b << 16 | a;
}

static int scan(const uint8_t *buf, size_t len, size_t bs,
		struct block *blocks)
{
	const uint8_t *p;
	size_t i, used;
	int n = 0;

	for (i = 0; i < len / bs && n < TA_MAX_BLOCKS; i++) {
		p = buf + i * bs;
		if (get_le32(p) != TA_MAGIC)
			continue;

		used = p[0xb] == 0xff ? bs : ((size_t)p[0xb] << 11) + 0x800;
		if (used > bs)
			used = bs;
		if (adler32(p + 8, used - 8) != get_le32(p + 4))
			continue;
		if (p[0x8] < 1 || p[0x8] > 3)
			continue;

		blocks[n].data = p;
		blocks[n].used = used;
		blocks[n].version = p[0x8];
		blocks[n].number = p[0x9];
		blocks[n].partition = p[0xa];
		n++;
	}

	return n;
}

/* The offset of the unit after the one at off, or 0 at the end */
static size_t next_unit(const struct block *b, size_t off)
{
	uint32_t length = get_le32(b->data + off + 4);
	size_t padded = ((size_t)length + 3) & ~(size_t)3;

	if (padded > b->used - off - TA_UNIT_HDR)
		return 0;

	return off + TA_UNIT_HDR + padded;
}

static int unit_at(const struct block *b, size_t off)
{
	return off + TA_UNIT_HDR <= b->used &&
	       get_le32(b->data + off + 8) == TA_MAGIC;
}

/* Within one block the first copy of a unit is the one tad finds */
static int seen_before(const struct block *b, size_t off, uint32_t id)
{
	size_t p;

	for (p = TA_BLOCK_HDR; p && p < off; p = next_unit(b, p))
		if (get_le32(b->data + p) == id)
			return 1;

	return 0;
}

int ta_raw_parse(const uint8_t *buf, size_t len, ta_raw_unit_fn fn,
		 void *cookie)
{
	static struct block big[TA_MAX_BLOCKS], small[TA_MAX_BLOCKS];
	const struct block *blocks;
	const struct block *b;
	int nbig, nsmall, n;
	int count = 0;
	uint32_t id, length;
	size_t off;
	int i, j;
	int ret;

	nbig = len >= 0x80000 ? scan(buf, len, 0x80000, big) : 0;
	nsmall = scan(buf, len, 0x20000, small);
	blocks = nbig >= nsmall ? big : small;
	n = nbig >= nsmall ? nbig : nsmall;
	if (!n)
		return -1;

	/*
	 * Blocks in ascending order, as tad walks them: a later copy of a
	 * logical block is a leftover and loses, a later copy of a unit in
	 * another block wins, which the store's replace gives us.
	 */
	for (i = 0; i < n; i++) {
		b = &blocks[i];

		for (j = 0; j < i; j++)
			if (blocks[j].partition == b->partition &&
			    blocks[j].number == b->number)
				break;
		if (j < i)
			continue;

		for (off = TA_BLOCK_HDR; off && unit_at(b, off);
		     off = next_unit(b, off)) {
			id = get_le32(b->data + off);
			length = get_le32(b->data + off + 4);
			if (length > b->used - off - TA_UNIT_HDR)
				break;
			if (seen_before(b, off, id))
				continue;

			ret = fn(cookie, b->partition, id,
				 b->data + off + TA_UNIT_HDR, length);
			if (ret < 0)
				return ret;
			count++;
		}
	}

	return count;
}
