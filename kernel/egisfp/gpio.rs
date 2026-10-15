// SPDX-License-Identifier: GPL-2.0-only
//! Minimal owned GPIO consumers for the EC617 bring-up driver.
//!
//! This is built in the kernel crate because Device::as_raw is crate-private.
//! Descriptors are explicitly released, not devres-managed: outstanding file
//! handles must never gain access to a descriptor freed during unbind.

use crate::{bindings, device::Device, error::{from_err_ptr, to_result}, prelude::*};

struct Descriptor(*mut bindings::gpio_desc);

// SAFETY: gpiolib descriptors are reference-stable until gpiod_put. Its
// cansleep operations may run on any task; the driver serializes sequencing.
unsafe impl Send for Descriptor {}

impl Descriptor {
    fn get(dev: &Device, name: &CStr, flags: bindings::gpiod_flags) -> Result<Self> {
        // SAFETY: dev and the nul-terminated name remain valid during the call.
        let ptr = from_err_ptr(unsafe {
            bindings::gpiod_get(dev.as_raw(), name.as_char_ptr(), flags)
        })?;
        Ok(Self(ptr))
    }
}

impl Drop for Descriptor {
    fn drop(&mut self) {
        // SAFETY: we own exactly one descriptor acquired by gpiod_get.
        unsafe { bindings::gpiod_put(self.0) };
    }
}

/// An exclusively requested output GPIO; values respect DT active polarity.
pub struct Output(Descriptor);

impl Output {
    /// Acquire an output with its initial logical value.
    pub fn get(dev: &Device, name: &CStr, value: bool) -> Result<Self> {
        let flags = if value { bindings::gpiod_flags_GPIOD_OUT_HIGH }
                    else { bindings::gpiod_flags_GPIOD_OUT_LOW };
        Ok(Self(Descriptor::get(dev, name, flags)?))
    }

    /// Set the logical output value from sleepable context.
    pub fn set(&mut self, value: bool) {
        // SAFETY: the owned descriptor is configured as an output.
        unsafe { bindings::gpiod_set_value_cansleep(self.0.0, value.into()) };
    }
}

/// An exclusively requested input GPIO.
pub struct Input(Descriptor, Bias);

// Qualcomm TLMM exposes bias through pinctrl, not gpio_chip.set_config.
// Keep a counted pinctrl handle and its state pointers until the input drops.
struct Bias {
    handle: *mut bindings::pinctrl,
    off: *mut bindings::pinctrl_state,
    on: *mut bindings::pinctrl_state,
}

// SAFETY: owned handle; all state changes run under the hardware mutex.
unsafe impl Send for Bias {}

impl Bias {
    fn get(dev: &Device) -> Result<Self> {
        // SAFETY: dev is live throughout probe and binding.
        let handle = from_err_ptr(unsafe { bindings::pinctrl_get(dev.as_raw()) })?;
        let mut bias = Self { handle, off: core::ptr::null_mut(), on: core::ptr::null_mut() };
        // SAFETY: counted handle is valid; lookup states are owned by it.
        bias.off = from_err_ptr(unsafe {
            bindings::pinctrl_lookup_state(handle, c"irq-off".as_ptr())
        })?;
        // SAFETY: same valid handle and static nul-terminated name.
        bias.on = from_err_ptr(unsafe {
            bindings::pinctrl_lookup_state(handle, c"irq-on".as_ptr())
        })?;
        Ok(bias)
    }
}

impl Drop for Bias {
    fn drop(&mut self) {
        // SAFETY: release the counted handle once, including lookup failures.
        unsafe { bindings::pinctrl_put(self.handle) };
    }
}

impl Input {
    /// Acquire an input.
    pub fn get(dev: &Device, name: &CStr) -> Result<Self> {
        Ok(Self(Descriptor::get(dev, name, bindings::gpiod_flags_GPIOD_IN)?, Bias::get(dev)?))
    }

    /// Read the logical input level from sleepable context.
    pub fn value(&self) -> Result<bool> {
        // SAFETY: self owns the descriptor throughout the call.
        let ret = unsafe { bindings::gpiod_get_value_cansleep(self.0.0) };
        to_result(ret)?;
        Ok(ret != 0)
    }

    /// Enable the default pull-up, or disable bias to avoid back-powering.
    pub fn pull_up(&mut self, enabled: bool) -> Result {
        let state = if enabled { self.1.on } else { self.1.off };
        // SAFETY: both states belong to our live, counted handle. These DT
        // states affect only the IRQ input, never reset or power outputs.
        to_result(unsafe { bindings::pinctrl_select_state(self.1.handle, state) })
    }
}
