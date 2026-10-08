#!/usr/bin/env python3
"""Raise each RPMh regulator's floor to the stock tree's qcom,init-voltage.

The board takes its regulator windows from the stock tree, but few mainline
consumers set a voltage, and for a rail it cannot read back the regulator
core picks the bottom of the window. Stock's vendor driver starts each rail
at its qcom,init-voltage instead. This rewrites a decompiled (numeric) board
tree so every floor below that voltage is raised to it, and nothing else.

    scripts/vreg-floors.py live.dts ours.dts > ours-vreg.dts

live.dts is the decompiled /proc/device-tree of stock Android. One line per
change goes to stderr.
"""
import re
import sys

live = open(sys.argv[1]).read()
dts = open(sys.argv[2]).read()

# rpmh-regulator-ldob13 { ... regulator-pm6450-l13 { qcom,init-voltage } }
init = {}
for m in re.finditer(r'rpmh-regulator-(\w+) \{(.*?)\n\t\t\t\};', live, re.S):
    mm = re.search(r'qcom,init-voltage = <(0x[0-9a-f]+)>;', m.group(2))
    if mm:
        init[m.group(1)] = int(mm.group(1), 16)

# Ours: regulators-N { qcom,pmic-id = "b"; ldo13 { ... } }, so the RPMh
# resource is the node's type, the PMIC id and the node's number.
kind = {'smps': 'smp', 'ldo': 'ldo', 'bob': 'bob'}
out, changes = [], []
pid = None
cur = None
for line in dts.split('\n'):
    if re.match(r'^\t+regulators-\d \{$', line):
        pid = None
    m = re.match(r'^\t+qcom,pmic-id = "(\w)";$', line)
    if m:
        pid = m.group(1)
    m = re.match(r'^\t+((smps|ldo|bob)(\d*)) \{$', line)
    if m:
        cur = (m.group(1), kind[m.group(2)] + '%s' + m.group(3))
    m = re.match(r'^(\t+)regulator-min-microvolt = <(0x[0-9a-f]+)>;$', line)
    if m and cur:
        if pid is None:
            sys.exit('pmic-id after the regulator nodes; cannot map %s' % cur[0])
        res = cur[1] % pid
        lo = int(m.group(2), 16)
        if res in init and init[res] > lo:
            line = '%sregulator-min-microvolt = <0x%x>;' % (m.group(1), init[res])
            changes.append('%s (%s): %d -> %d' % (res, cur[0], lo, init[res]))
    out.append(line)
print('\n'.join(out), end='')
for c in changes:
    print(c, file=sys.stderr)
