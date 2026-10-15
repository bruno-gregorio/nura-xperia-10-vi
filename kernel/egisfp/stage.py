#!/usr/bin/env python3
"""Stage the experimental Rust driver in an isolated 6.18 kernel source tree.

Run inside pmport. Does not modify the kernel aport or production config.
"""
import argparse
from pathlib import Path
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('tree', type=Path)
args = parser.parse_args()
tree = args.tree.resolve()
source = Path(__file__).resolve().parent
assert (tree / 'rust/kernel/miscdevice.rs').is_file(), 'Not our Rust-capable kernel tree'

def append_once(path, text):
    current = path.read_text()
    if text not in current:
        path.write_text(current + '\n' + text)

target = tree / 'drivers/misc/egisfp'
target.mkdir(exist_ok=True)
for name in ('egisfp.rs', 'eventfd.rs', 'egisfp.h', 'Kconfig', 'Makefile'):
    shutil.copyfile(source / name, target / name)
shutil.copyfile(source / 'gpio.rs', tree / 'rust/kernel/egis_gpio.rs')
append_once(tree / 'rust/kernel/lib.rs', '#[cfg(CONFIG_EGISFP)]\npub mod egis_gpio;\n')
append_once(tree / 'rust/bindings/bindings_helper.h',
            '#ifdef CONFIG_EGISFP\n#include <linux/eventfd.h>\n'
            '#include <linux/gpio/consumer.h>\n'
            '#include <linux/pinctrl/pinconf-generic.h>\n#endif\n')
append_once(tree / 'rust/bindings/bindings_helper.h',
            '#ifdef CONFIG_EGISFP\n#include <linux/pinctrl/consumer.h>\n#endif\n')
append_once(tree / 'drivers/misc/Kconfig', 'source "drivers/misc/egisfp/Kconfig"\n')
append_once(tree / 'drivers/misc/Makefile', 'obj-$(CONFIG_EGISFP) += egisfp/\n')
dts = tree / 'arch/arm64/boot/dts/qcom'
shutil.copyfile(source / 'pdx246.dtsi', dts / 'pdx246-egisfp.dtsi')
append_once(dts / 'sm6450-sony-xperia-columbia-pdx246.dts', '#include "pdx246-egisfp.dtsi"\n')
print(f'Staged experimental driver in {tree}')
