// SPDX-License-Identifier: GPL-2.0-only
//! Owned eventfd references for EC617 interrupt notifications.

use kernel::{bindings, error::from_err_ptr, prelude::*};

pub(super) struct EventFd(*mut bindings::eventfd_ctx);

// SAFETY: eventfd's reference count and counter are synchronized by the kernel.
// The reference remains held until Drop, and notification is IRQ-safe.
unsafe impl Send for EventFd {}

impl EventFd {
    pub(super) fn get(fd: i32) -> Result<Self> {
        // SAFETY: eventfd_ctx_fdget validates the calling task's fd and takes
        // a reference independent of the fd's subsequent close/reuse.
        Ok(Self(from_err_ptr(unsafe { bindings::eventfd_ctx_fdget(fd) })?))
    }

    /// Only called by our hardware IRQ handler, not an eventfd wake callback.
    pub(super) fn signal_from_irq(&self) {
        // SAFETY: self holds a reference; the IRQ handler cannot recursively
        // signal eventfds through this driver (no eventfd wait callbacks).
        unsafe { bindings::eventfd_signal_mask(self.0, 0) };
    }
}

impl Drop for EventFd {
    fn drop(&mut self) {
        // SAFETY: releases exactly the reference acquired by fdget.
        unsafe { bindings::eventfd_ctx_put(self.0) };
    }
}
