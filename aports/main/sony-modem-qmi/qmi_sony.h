/* SPDX-License-Identifier: BSD-3-Clause */
/*
 * The QMI services Sony's Android offers the modem.
 *
 * TA and MiscTA are ta_qmi_service's, as its IDL tables describe them
 * (service objects at 0x5720 and 0x5770 of the stock binary). Both put a
 * plain 32-bit status in TLV 0x01 where QMI services usually put
 * qmi_response_type_v01 in TLV 0x02, and both carry unit data as optional
 * TLV 0x10 byte arrays with 16-bit counts.
 *
 * MLog is mlog_qmi_service's, as the modem's client object (in modem.mbn)
 * describes it; the stock service binary was not looked at.
 */
#ifndef __QMI_SONY_H__
#define __QMI_SONY_H__

#include <stdbool.h>
#include <stdint.h>

#include "libqrtr.h"

#define TA_QMI_SERVICE		0xe3
#define TA_QMI_VERSION		1
#define TA_QMI_INSTANCE		0

#define MISCTA_QMI_SERVICE	0xe4
#define MISCTA_QMI_VERSION	1
#define MISCTA_QMI_INSTANCE	0

#define MLOG_QMI_SERVICE	0xe6
#define MLOG_QMI_VERSION	1
#define MLOG_QMI_INSTANCE	0

#define TA_QMI_DATA_MAX		0xfc00
#define MISCTA_QMI_DATA_MAX	0x1000

/* Service 0xe3: libta's calls, one partition open per client */
#define TA_QMI_OPEN		1
#define TA_QMI_CLOSE		2
#define TA_QMI_GET_SIZE		3
#define TA_QMI_READ		4
#define TA_QMI_READ_LARGE	5
#define TA_QMI_WRITE		6
#define TA_QMI_WRITE_LARGE	7
#define TA_QMI_DELETE		8
#define TA_QMI_GET_NEXT_ID	9

/* Service 0xe4: libmiscta's calls, always on partition 2 */
#define MISCTA_QMI_GET_SIZE		1
#define MISCTA_QMI_READ			2
#define MISCTA_QMI_WRITE		3
#define MISCTA_QMI_WRITE_CRITICAL	4
#define MISCTA_QMI_FLUSH		5

/*
 * Service 0xe6: one log line per LOG request, as TLVs 1 (u32 level),
 * 2 (u32, 7 in every line seen), 3 (source file), 4 (u32 line), 5 (up to
 * 32 bytes, not decoded) and 6 (the text). 3 and 6 have 16-bit counts.
 * GET takes nothing and answers a status and a u32; the modem has not been
 * seen to send it.
 */
#define MLOG_QMI_LOG		1
#define MLOG_QMI_GET		2

struct ta_qmi_status_resp {
	uint32_t status;
};

struct ta_qmi_unit_req {
	uint32_t unit;
};

struct ta_qmi_open_req {
	uint32_t partition;
	uint32_t mode;
};

struct ta_qmi_size_resp {
	uint32_t status;
	bool size_valid;
	uint32_t size;
};

struct ta_qmi_read_req {
	uint32_t unit;
	uint32_t size;
};

struct ta_qmi_read_large_req {
	uint32_t unit;
	uint32_t size;
	uint32_t chunk;
};

struct ta_qmi_data_resp {
	uint32_t status;
	bool data_valid;
	uint32_t data_len;
	uint8_t data[TA_QMI_DATA_MAX];
};

struct ta_qmi_write_req {
	uint32_t unit;
	uint32_t data_len;
	uint8_t data[TA_QMI_DATA_MAX];
};

struct ta_qmi_write_large_req {
	uint32_t unit;
	uint32_t chunk;
	uint32_t data_len;
	uint8_t data[TA_QMI_DATA_MAX];
};

struct ta_qmi_next_id_resp {
	uint32_t status;
	bool unit_valid;
	uint32_t unit;
	bool size_valid;
	uint32_t size;
};

struct miscta_qmi_data_resp {
	uint32_t status;
	bool data_valid;
	uint32_t data_len;
	uint8_t data[MISCTA_QMI_DATA_MAX];
};

struct miscta_qmi_write_req {
	uint32_t unit;
	uint32_t data_len;
	uint8_t data[MISCTA_QMI_DATA_MAX];
};

struct mlog_qmi_get_resp {
	uint32_t status;
	uint32_t value;
};

extern struct qmi_elem_info ta_qmi_empty_req_ei[];
extern struct qmi_elem_info ta_qmi_status_resp_ei[];
extern struct qmi_elem_info ta_qmi_unit_req_ei[];
extern struct qmi_elem_info ta_qmi_open_req_ei[];
extern struct qmi_elem_info ta_qmi_size_resp_ei[];
extern struct qmi_elem_info ta_qmi_read_req_ei[];
extern struct qmi_elem_info ta_qmi_read_large_req_ei[];
extern struct qmi_elem_info ta_qmi_data_resp_ei[];
extern struct qmi_elem_info ta_qmi_write_req_ei[];
extern struct qmi_elem_info ta_qmi_write_large_req_ei[];
extern struct qmi_elem_info ta_qmi_next_id_resp_ei[];
extern struct qmi_elem_info miscta_qmi_data_resp_ei[];
extern struct qmi_elem_info miscta_qmi_write_req_ei[];
extern struct qmi_elem_info mlog_qmi_get_resp_ei[];

#endif
