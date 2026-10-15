#!/bin/sh
# Run as root ON the pdx246, with no camera app capturing. Requires
# libcamera-tools, v4l-utils and python3. Sensor-generated bars let an
# unattended run check real CSI/Bayer/RGB output without an illuminated scene.
# Results stay in /tmp/pdx246-camera-check; normal sensor mode is restored.
set -eu
[ "$(id -u)" = 0 ] || { echo 'Run on the phone as root' >&2; exit 1; }
grep -aq 'sony,pdx246' /proc/device-tree/compatible || exit 1
dir=/tmp/pdx246-camera-check
install -d -m700 -o user "$dir"
sensor=
capture=
cleanup() {
    if [ -n "$capture" ]; then
        kill "$capture" 2>/dev/null || true
        wait "$capture" 2>/dev/null || true
    fi
    test -z "$sensor" || v4l2-ctl -d "$sensor" -c test_pattern=0
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
# Probe order changes across kernel builds. Match the stable DT camera
# address to the media entity, never assume camera or I2C bus numbers.
su -s /bin/sh user -c 'LIBCAMERA_LOG_NO_COLOR=1 cam -l' > "$dir/cameras.txt"
media-ctl -d /dev/media0 -p > "$dir/media.txt"
python3 -I - "$dir" <<'PY' > "$dir/map.txt"
import re, sys
from pathlib import Path
p = Path(sys.argv[1])
cameras = re.findall(r'^\d+: .* \((/base/[^)]+)\)$',
                     (p / 'cameras.txt').read_text(), re.M)
entities = re.findall(r'entity \d+: ((?:hi846|imx582) \d+-[0-9a-f]+) \(',
                      (p / 'media.txt').read_text())
for label, addr, model in [('front', '20', 'hi846'),
                           ('wide', '21', 'hi846'),
                           ('main', '1a', 'imx582')]:
    ids = [x for x in cameras if x.endswith('/camera@' + addr)]
    names = [x for x in entities if x.startswith(model + ' ') and
             x.endswith('-' + addr.zfill(4))]
    assert len(ids) == len(names) == 1, (label, ids, names)
    print(label, ids[0], names[0], sep='|')
PY
while IFS='|' read -r n camera entity; do
    sensor=$(media-ctl -d /dev/media0 -e "$entity")
    test -n "$sensor"
    su -s /bin/sh user -c "LIBCAMERA_LOG_NO_COLOR=1 timeout 30 cam -c '$camera' -s role=viewfinder,width=1280,height=720 --capture=180 --file=$dir/camera-$n.ppm" > "$dir/camera-$n.log" 2>&1 &
    capture=$!
    # CameraSensor resets controls during initialization. Set bars only
    # after streaming starts, and do not alter a sensor if acquisition failed.
    sleep 2
    kill -0 "$capture"
    v4l2-ctl -d "$sensor" -c test_pattern=2 -C test_pattern
    if ! wait "$capture"; then
        tail -20 "$dir/camera-$n.log"
        exit 1
    fi
    capture=
    cleanup
    sensor=
    python3 -I - "$dir/camera-$n.ppm" "$n" "$dir/camera-$n.log" <<'PY'
import sys, re
from pathlib import Path

path = Path(sys.argv[1])
with path.open('rb') as f:
    assert f.readline().strip() == b'P6', 'Expected cam PPM output'
    width, height = map(int, f.readline().split())
    assert f.readline().strip() == b'255'
    pixels = f.read()
assert len(pixels) == width * height * 3, 'Incomplete frame'
expected = [(1,1,1), (1,1,0), (0,1,1), (0,1,0),
            (1,0,1), (1,0,0), (0,0,1), (0,0,0)]
# The wide's stock 2304 mode crops 480 pixels from each side of the
# 3264-wide pattern. White and black lie outside that crop. The front's
# binned mode generates its pattern across the output width.
input_width = int(re.search(r'Input (\d+)x\d+-', Path(sys.argv[3]).read_text()).group(1))
full, left, crop = (3264, 480, 2304) if sys.argv[2] == 'wide' and input_width == 2304 else (width, 0, width)
checked = 0
for bar, channels in enumerate(expected):
    start = max(left, bar * full / 8)
    end = min(left + crop, (bar + 1) * full / 8)
    if end <= start:
        continue
    x = int(((start + end) / 2 - left) * width / crop)
    y = height // 2
    samples = [pixels[(yy * width + xx) * 3:(yy * width + xx) * 3 + 3]
               for yy in range(y-4, y+5) for xx in range(x-4, x+5)]
    mean = [sum(p[c] for p in samples) / len(samples) for c in range(3)]
    # These are processed RGB frames: the module CCM and gamma can lift an
    # otherwise absent channel (wide blue red=104..131 with changing AWB).
    # Keep at least a 32-code gap between high/low bands, not ideal
    # pre-ISP 0/255 values. Separate shader tests check exact Bayer phases.
    assert all(value > 192 if high else value < 160
               for value, high in zip(mean, channels)), (bar, mean, channels)
    checked += 1
print(f'{path.name}: PASS, {checked} expected RGB bars in {width}x{height}')
PY
done < "$dir/map.txt"
echo 'All three camera pipelines passed their visible bars; patterns restored to disabled'
