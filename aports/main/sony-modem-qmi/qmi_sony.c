// SPDX-License-Identifier: BSD-3-Clause
#include <stddef.h>

#include "qmi_sony.h"

#define TA_U32(tlv, type, field) {					\
	.data_type = QMI_UNSIGNED_4_BYTE,				\
	.elem_len = 1,							\
	.elem_size = sizeof(uint32_t),					\
	.tlv_type = tlv,						\
	.offset = offsetof(struct type, field),				\
}

#define TA_OPT(tlv, type, field) {					\
	.data_type = QMI_OPT_FLAG,					\
	.elem_len = 1,							\
	.elem_size = sizeof(bool),					\
	.tlv_type = tlv,						\
	.offset = offsetof(struct type, field),				\
}

/*
 * The IDL marks these arrays SZ_IS_16, so the count on the wire is two
 * bytes even when it would fit in one. libqrtr writes two for an
 * elem_size of 2, and decodes into a uint32_t whatever the size.
 */
#define TA_DATA(tlv, type, len, field, max)				\
	{								\
		.data_type = QMI_DATA_LEN,				\
		.elem_len = 1,						\
		.elem_size = sizeof(uint16_t),				\
		.tlv_type = tlv,					\
		.offset = offsetof(struct type, len),			\
	},								\
	{								\
		.data_type = QMI_UNSIGNED_1_BYTE,			\
		.elem_len = max,					\
		.elem_size = sizeof(uint8_t),				\
		.array_type = VAR_LEN_ARRAY,				\
		.tlv_type = tlv,					\
		.offset = offsetof(struct type, field),			\
	}

struct qmi_elem_info ta_qmi_empty_req_ei[] = {
	{}
};

struct qmi_elem_info ta_qmi_status_resp_ei[] = {
	TA_U32(0x01, ta_qmi_status_resp, status),
	{}
};

struct qmi_elem_info ta_qmi_unit_req_ei[] = {
	TA_U32(0x01, ta_qmi_unit_req, unit),
	{}
};

struct qmi_elem_info ta_qmi_open_req_ei[] = {
	TA_U32(0x01, ta_qmi_open_req, partition),
	TA_U32(0x02, ta_qmi_open_req, mode),
	{}
};

struct qmi_elem_info ta_qmi_size_resp_ei[] = {
	TA_U32(0x01, ta_qmi_size_resp, status),
	TA_OPT(0x10, ta_qmi_size_resp, size_valid),
	TA_U32(0x10, ta_qmi_size_resp, size),
	{}
};

struct qmi_elem_info ta_qmi_read_req_ei[] = {
	TA_U32(0x01, ta_qmi_read_req, unit),
	TA_U32(0x02, ta_qmi_read_req, size),
	{}
};

struct qmi_elem_info ta_qmi_read_large_req_ei[] = {
	TA_U32(0x01, ta_qmi_read_large_req, unit),
	TA_U32(0x02, ta_qmi_read_large_req, size),
	TA_U32(0x03, ta_qmi_read_large_req, chunk),
	{}
};

struct qmi_elem_info ta_qmi_data_resp_ei[] = {
	TA_U32(0x01, ta_qmi_data_resp, status),
	TA_OPT(0x10, ta_qmi_data_resp, data_valid),
	TA_DATA(0x10, ta_qmi_data_resp, data_len, data, TA_QMI_DATA_MAX),
	{}
};

struct qmi_elem_info ta_qmi_write_req_ei[] = {
	TA_U32(0x01, ta_qmi_write_req, unit),
	TA_DATA(0x02, ta_qmi_write_req, data_len, data, TA_QMI_DATA_MAX),
	{}
};

struct qmi_elem_info ta_qmi_write_large_req_ei[] = {
	TA_U32(0x01, ta_qmi_write_large_req, unit),
	TA_U32(0x02, ta_qmi_write_large_req, chunk),
	TA_DATA(0x03, ta_qmi_write_large_req, data_len, data, TA_QMI_DATA_MAX),
	{}
};

struct qmi_elem_info ta_qmi_next_id_resp_ei[] = {
	TA_U32(0x01, ta_qmi_next_id_resp, status),
	TA_OPT(0x10, ta_qmi_next_id_resp, unit_valid),
	TA_U32(0x10, ta_qmi_next_id_resp, unit),
	TA_OPT(0x11, ta_qmi_next_id_resp, size_valid),
	TA_U32(0x11, ta_qmi_next_id_resp, size),
	{}
};

struct qmi_elem_info miscta_qmi_data_resp_ei[] = {
	TA_U32(0x01, miscta_qmi_data_resp, status),
	TA_OPT(0x10, miscta_qmi_data_resp, data_valid),
	TA_DATA(0x10, miscta_qmi_data_resp, data_len, data, MISCTA_QMI_DATA_MAX),
	{}
};

struct qmi_elem_info miscta_qmi_write_req_ei[] = {
	TA_U32(0x01, miscta_qmi_write_req, unit),
	TA_DATA(0x02, miscta_qmi_write_req, data_len, data, MISCTA_QMI_DATA_MAX),
	{}
};

struct qmi_elem_info mlog_qmi_get_resp_ei[] = {
	TA_U32(0x01, mlog_qmi_get_resp, status),
	TA_U32(0x02, mlog_qmi_get_resp, value),
	{}
};
