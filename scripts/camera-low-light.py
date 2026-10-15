#!/usr/bin/env python3
"""Import Hi846 exposure-dependent CCM, shading and luma targets from stock.

Run in pmport after the private Chromatix decoder/summarizer. This uses only
module tuning, never sensor identity. Applied exposure provides an index;
the proprietary scene estimator and HDR/flash processing are not replicated.
"""
import argparse
import csv
import json
from pathlib import Path
import yaml


class TuningDumper(yaml.SafeDumper):
    # libcamera supports plain mappings/sequences, not YAML aliases.
    def ignore_aliases(self, data):
        return True


def sequence(dumper, values):
    return dumper.represent_sequence('tag:yaml.org,2002:seq', values,
                                    flow_style=all(isinstance(v, (float, int)) for v in values))


TuningDumper.add_representer(list, sequence)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--decoded', type=Path, default=Path('out/dl-tuned'))
    p.add_argument('--tuning', type=Path, default=Path('aports/main/pdx246-camera-calibration'))
    p.add_argument('--reference', type=Path, default=Path('aports/main/pdx246-camera-calibration'))
    a = p.parse_args()
    for sensor, name in [('front', 'hi846-front'), ('back', 'hi846')]:
        summary = json.loads((a.decoded / 'summary' / ('le_hi846_' + sensor + '.json')).read_text())
        path = a.tuning / (name + '.yaml')
        tuning = yaml.safe_load(path.read_text())
        algorithms = {k: v for item in tuning['algorithms'] for k, v in item.items()}
        lsc, ccm, agc = (algorithms[k] for k in ['LensShading', 'Ccm', 'Agc'])
        knee = next(t for t in summary['aec']['exposure_tables'] if t['name'] == 'DefaultExpTable')['knees_raw'][0]
        reference_time = knee[1] * knee[2] / 1000
        assert reference_time == 13.195
        for item in [lsc, ccm, agc]:
            item['referenceExposureTime'] = reference_time

        ccm['luxBands'] = []
        for band in summary['ccm']['all_lux_bands']:
            tables = {}
            for entry in band['ccms']:
                assert entry['k'] == [0, 0, 0]
                for ct in entry['cct_trigger']:
                    tables[int(ct)] = entry['ccm']
            ccm['luxBands'].append(dict(start=band['lux_idx'][0], end=band['lux_idx'][1],
                ccms=[dict(ct=ct, ccm=value) for ct, value in sorted(tables.items())]))

        bands = {}
        for leaf in summary['lsc']['lsc35_tfe_v2']['leaves']:
            triggers = {t['var_name']: (t['start'], t['end']) for t in leaf['triggers']}
            key = triggers['lux_idx']
            rows = list(csv.reader(line for line in (a.decoded / leaf['file']).read_text().splitlines()
                                   if line and not line.startswith('#')))
            rows = [list(map(float, row)) for row in rows if row]
            assert len(rows) == 52 and all(len(row) == 17 for row in rows)
            planes = [[v for row in rows[c*13:(c+1)*13] for v in row] for c in range(4)]
            gains, weights = [], []
            for i in range(221):
                gains.extend([planes[0][i], (planes[1][i]+planes[2][i])/2, planes[3][i]])
                weights.append(planes[1][i] / (planes[1][i]+planes[2][i]))
            for ct in triggers['cct']:
                bands.setdefault(key, {})[int(ct)] = (gains, weights)
        lsc['luxBands'] = []
        weights = []
        for (start, end), tables in sorted(bands.items()):
            lsc['luxBands'].append(dict(start=start, end=end,
                tables=[dict(ct=ct, gains=g) for ct, (g, _) in sorted(tables.items())]))
            weights.append({str(ct): w for ct, (_, w) in tables.items()})
        refpath = a.reference / (name + '.json')
        ref = json.loads(refpath.read_text())
        ref['lux_green_fraction'] = weights
        tmp = refpath.with_suffix('.tmp'); tmp.write_text(json.dumps(ref, separators=(',', ':'))+'\n'); tmp.replace(refpath)

        targets = {}
        for start, end, low, high in summary['aec']['FrameSA_Luma'][0]:
            assert low == high
            targets[int(start)] = low / 255
            targets[int(end)] = high / 255
        agc['exposureTargets'] = [dict(lux=lux, target=value) for lux, value in sorted(targets.items())]
        tmp = path.with_suffix('.tmp')
        tmp.write_text('# SPDX-License-Identifier: CC0-1.0\n# Module calibration from Sony Chromatix; see scripts/camera-low-light.py.\n'+
                       yaml.dump(tuning, Dumper=TuningDumper, sort_keys=False, width=120))
        tmp.replace(path)
        print(name + ': stock low-light CCM, LSC and linear-luma targets imported')


if __name__ == '__main__':
    main()
