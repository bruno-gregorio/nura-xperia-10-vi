/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef _EGISFP_BRINGUP_H
#define _EGISFP_BRINGUP_H
#include <linux/ioctl.h>
#include <linux/types.h>

/* Experimental hardware-control ABI, not Android /dev/esfp0 compatibility.
 * One open owner. Close powers off and releases the eventfd subscription.
 * This interface never loads trusted apps, performs SPI, or stores templates.
 */
struct egisfp_status {
	__u32 abi_version;
	__u32 powered;
	__u32 irq_level;
	__u32 irq_sequence;
};
#define EGISFP_GET_STATUS _IOR('E', 0x80, struct egisfp_status)
#define EGISFP_POWER _IOW('E', 0x81, __u32) /* exactly 0 or 1 */
#define EGISFP_RESET _IO('E', 0x82)
#define EGISFP_EVENTFD _IOW('E', 0x83, __s32) /* -1 unregisters */
/* One notification per arm, then disabled. Reset/power-off also disarm.
 * 0: disarm; 1: rising; 2: falling; 4: high; 8: low (Linux IRQ_TYPE_*).
 */
#define EGISFP_IRQ_ARM _IOW('E', 0x84, __u32)
#endif
