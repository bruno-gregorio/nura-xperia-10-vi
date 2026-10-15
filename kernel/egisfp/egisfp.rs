// SPDX-License-Identifier: GPL-2.0-only
//! Egis EC617 GPIO/IRQ controller for a TrustZone-owned sensor.
//!
//! SPI and biometric processing belong to egisap64; no raw sensor or secure
//! storage access is provided here. The initial ABI uses eventfd for IRQs so
//! userspace can integrate with poll/epoll without spinning on GPIO status.

mod eventfd;

use core::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use kernel::{
    bindings, c_str, container_of,
    device::{Bound, Core, Device},
    egis_gpio::{Input, Output},
    fs::File,
    ioctl::{_IO, _IOR, _IOW},
    irq::{self, Flags, IrqReturn, ThreadedIrqReturn},
    miscdevice::{MiscDevice, MiscDeviceOptions, MiscDeviceRegistration},
    new_mutex, of, platform, prelude::*,
    sync::{Arc, Mutex},
    time::{delay::fsleep, Delta},
    types::ForeignOwnable,
    uaccess::UserSlice,
};

const GET_STATUS: u32 = _IOR::<[u32; 4]>('E' as u32, 0x80);
const POWER: u32 = _IOW::<u32>('E' as u32, 0x81);
const RESET: u32 = _IO('E' as u32, 0x82);
const EVENTFD: u32 = _IOW::<i32>('E' as u32, 0x83);
const IRQ_ARM: u32 = _IOW::<u32>('E' as u32, 0x84);

fn sleep_ms(ms: i64) {
    fsleep(Delta::from_millis(ms));
}

struct Hardware {
    reset: Output,
    vdd: Output,
    vcc: Output,
    interrupt: Input,
    irq: u32,
    events: Arc<Events>,
    powered: bool,
}

impl Hardware {
    fn power_on(&mut self) -> Result {
        if self.powered { return Ok(()); }
        self.reset.set(true);
        self.vdd.set(true);
        self.vcc.set(true);
        sleep_ms(3);
        self.reset.set(false);
        if let Err(err) = self.interrupt.pull_up(true) {
            self.vdd.set(false);
            self.vcc.set(false);
            sleep_ms(10);
            self.reset.set(true);
            sleep_ms(50);
            return Err(err);
        }
        sleep_ms(3);
        self.powered = true;
        Ok(())
    }

    fn power_off(&mut self) {
        if !self.powered { return; }
        self.disarm();
        // A failed bias change must not prevent rails being switched off.
        if self.interrupt.pull_up(false).is_err() {
            pr_err!("egisfp: failed to disable IRQ bias during power-off\n");
        }
        self.vdd.set(false);
        self.vcc.set(false);
        sleep_ms(10);
        self.reset.set(true);
        sleep_ms(50);
        self.powered = false;
    }

    fn reset(&mut self) -> Result {
        if !self.powered { return Err(Error::from_errno(-(bindings::EHOSTDOWN as i32))); }
        self.disarm();
        self.reset.set(true);
        sleep_ms(10);
        self.reset.set(false);
        sleep_ms(3);
        Ok(())
    }

    fn disarm(&self) {
        // SAFETY: armed owns the single enable reference. If the handler
        // consumed it, wait until its disable_irq_nosync has completed.
        unsafe {
            if self.events.armed.swap(false, Ordering::AcqRel) {
                pr_info!("egisfp: disarm mask IRQ {}\n", self.irq);
                bindings::disable_irq_nosync(self.irq);
                pr_info!("egisfp: disarm masked IRQ {}\n", self.irq);
            }
            bindings::synchronize_irq(self.irq);
            pr_info!("egisfp: disarm drained IRQ {}\n", self.irq);
        }
    }

    fn arm(&self, mode: u32) -> Result {
        if !matches!(mode, 0 | 1 | 2 | 4 | 8) { return Err(EINVAL); }
        self.disarm();
        if mode == 0 { return Ok(()); }
        if !self.powered { return Err(Error::from_errno(-(bindings::EHOSTDOWN as i32))); }
        // SAFETY: disabled, drained, exclusively owned IRQ. Modes are the
        // four Linux IRQ_TYPE_* constants, never the emulated BOTH mode.
        pr_info!("egisfp: configuring IRQ {} type {}\n", self.irq, mode);
        let ret = unsafe { bindings::irq_set_irq_type(self.irq, mode) };
        if ret < 0 { return Err(Error::from_errno(ret)); }
        pr_info!("egisfp: enabling IRQ {}\n", self.irq);
        self.events.armed.store(true, Ordering::Release);
        unsafe { bindings::enable_irq(self.irq) };
        pr_info!("egisfp: IRQ {} enabled\n", self.irq);
        Ok(())
    }
}

impl Drop for Hardware {
    fn drop(&mut self) { self.power_off(); }
}

#[pin_data]
struct Events {
    #[pin]
    target: Mutex<Option<eventfd::EventFd>>,
    sequence: AtomicU32,
    armed: AtomicBool,
    irq: u32,
}

struct Handler { events: Arc<Events> }

impl irq::ThreadedHandler for Handler {
    fn handle(&self, _dev: &Device<Bound>) -> ThreadedIrqReturn {
        if !self.events.armed.swap(false, Ordering::AcqRel) {
            return ThreadedIrqReturn::Handled;
        }
        // Mask in hard IRQ context, as the stock driver's level handler
        // does. An asserted line must not depend on scheduling the thread
        // before it is masked. This callback never takes a sleeping lock.
        // SAFETY: consume the single enable reference without waiting.
        unsafe { bindings::disable_irq_nosync(self.events.irq) };
        pr_info!("egisfp: IRQ {} masked in primary handler\n", self.events.irq);
        self.events.sequence.fetch_add(1, Ordering::Relaxed);
        ThreadedIrqReturn::WakeThread
    }

    fn handle_threaded(&self, _dev: &Device<Bound>) -> IrqReturn {
        if let Some(target) = &*self.events.target.lock() {
            target.signal_from_irq();
        }
        IrqReturn::Handled
    }
}

struct State {
    hardware: Option<Hardware>,
    opened: bool,
}

#[pin_data]
struct Shared {
    #[pin]
    state: Mutex<State>,
    events: Arc<Events>,
}

#[pin_data]
struct Egis {
    // Deregister before releasing the remaining owner references.
    #[pin]
    misc: MiscDeviceRegistration<Handle>,
    shared: Arc<Shared>,
    #[pin]
    _irq: irq::ThreadedRegistration<Handler>,
}

struct Handle(Arc<Shared>, bool);

impl Drop for Handle {
    fn drop(&mut self) {
        if !self.1 { return; }
        let mut state = self.0.state.lock();
        if let Some(hw) = &mut state.hardware { hw.power_off(); }
        // IRQs are drained above. Drop the eventfd reference outside the lock.
        let old = self.0.events.target.lock().take();
        drop(old);
        state.opened = false;
    }
}

#[vtable]
impl MiscDevice for Handle {
    type Ptr = KBox<Self>;

    fn open(_file: &File, misc: &MiscDeviceRegistration<Self>) -> Result<Self::Ptr> {
        // SAFETY: this registration is only embedded in Egis. shared is
        // initialized before misc_register publishes the device, and remains
        // initialized until misc_deregister finishes. Read only that field:
        // the rest of Egis may still be under construction during open.
        let shared = unsafe {
            &(*container_of!(misc as *const MiscDeviceRegistration<Handle>, Egis, misc)).shared
        }.clone();
        // Allocate before taking the state mutex: allocation failure drops
        // its value, and an owning Handle's destructor also takes that mutex.
        let mut handle = KBox::new(Self(shared.clone(), false), GFP_KERNEL)?;
        let mut state = shared.state.lock();
        if state.hardware.is_none() { return Err(ENODEV); }
        if state.opened { return Err(EBUSY); }
        state.opened = true;
        handle.1 = true;
        Ok(handle)
    }

    fn ioctl(me: <Self::Ptr as ForeignOwnable>::Borrowed<'_>, _file: &File,
             cmd: u32, arg: usize) -> Result<isize> {
        let arg = UserPtr::from_addr(arg);
        let mut state = me.0.state.lock();
        let hw = state.hardware.as_mut().ok_or(ENODEV)?;
        match cmd {
            GET_STATUS => {
                let values = [1, hw.powered as u32, hw.interrupt.value()? as u32,
                              me.0.events.sequence.load(Ordering::Relaxed)];
                let mut writer = UserSlice::new(arg, 16).writer();
                for value in values { writer.write(&value)?; }
            }
            POWER => match UserSlice::new(arg, 4).reader().read::<u32>()? {
                0 => hw.power_off(),
                1 => hw.power_on()?,
                _ => return Err(EINVAL),
            },
            RESET => hw.reset()?,
            IRQ_ARM => hw.arm(UserSlice::new(arg, 4).reader().read::<u32>()?)?,
            EVENTFD => {
                let fd = UserSlice::new(arg, 4).reader().read::<i32>()?;
                let target = if fd == -1 { None } else { Some(eventfd::EventFd::get(fd)?) };
                let old = core::mem::replace(&mut *me.0.events.target.lock(), target);
                drop(old);
            }
            _ => return Err(ENOTTY),
        }
        Ok(0)
    }
}

kernel::of_device_table!(OF_TABLE, MODULE_OF_TABLE, (), [
    (of::DeviceId::new(c_str!("egistec,ec617-tee")), ())
]);

impl platform::Driver for Egis {
    type IdInfo = ();
    const OF_ID_TABLE: Option<of::IdTable<Self::IdInfo>> = Some(&OF_TABLE);

    fn probe(pdev: &platform::Device<Core>, _: Option<&()>) -> Result<Pin<KBox<Self>>> {
        let dev = pdev.as_ref();
        let request = pdev.irq_by_index(0)?;
        let irq_number = request.irq();
        let mut interrupt = Input::get(dev, c_str!("irq"))?;
        interrupt.pull_up(false)?;
        let events = Arc::pin_init(pin_init!(Events {
            target <- new_mutex!(None),
            sequence: AtomicU32::new(0),
            armed: AtomicBool::new(false),
            irq: irq_number,
        }), GFP_KERNEL)?;
        let hardware = Hardware {
            reset: Output::get(dev, c_str!("reset"), true)?,
            vdd: Output::get(dev, c_str!("vdd-enable"), false)?,
            vcc: Output::get(dev, c_str!("vcc-enable"), false)?,
            interrupt,
            irq: irq_number,
            events: events.clone(),
            powered: false,
        };
        let irq_events = events.clone();
        let shared = Arc::pin_init(pin_init!(Shared {
            state <- new_mutex!(State { hardware: Some(hardware), opened: false }),
            events,
        }), GFP_KERNEL)?;
        let registration = irq::ThreadedRegistration::new(request,
            Flags::NO_AUTOEN | Flags::ONESHOT,
            c_str!("egisfp"), Ok(Handler { events: irq_events }));
        KBox::try_pin_init(try_pin_init!(Self {
            shared,
            _irq <- registration,
            misc <- MiscDeviceRegistration::register(MiscDeviceOptions { name: c_str!("egisfp0") }),
        }), GFP_KERNEL)
    }

    fn unbind(_pdev: &platform::Device<Core>, this: Pin<&Self>) {
        // Serialize against ioctl/release, drain IRQs, then free the GPIOs.
        // Open handles retain only Shared and return ENODEV from now on.
        let mut state = this.shared.state.lock();
        drop(state.hardware.take());
        let old = this.shared.events.target.lock().take();
        drop(old);
    }
}

kernel::module_platform_driver! {
    type: Egis,
    name: "egisfp",
    authors: ["Bruno Gregorio"],
    description: "Egis EC617 TrustZone sensor hardware control",
    license: "GPL v2",
}
