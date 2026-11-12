"""Prepare capture commands and validate actual standalone HUD screenshots/logs.

Use --prepare to create Unreal console exec files in Saved/Codex/ResponsiveHUD.
For each case, resize the standalone game with r.SetRes, wait for layout, then
execute the generated capture file in the Unreal game console. Run without
arguments to inspect the resulting PNG sizes and logged HUD scale/geometry.
"""
import argparse
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'Saved' / 'Codex' / 'ResponsiveHUD'
CASES = [
    ('window_1280x720', 1280, 720, 'w'),
    ('window_800x600', 800, 600, 'w'),
    ('window_1280x800', 1280, 800, 'w'),
    ('window_2560x1080', 2560, 1080, 'w'),
    ('window_3840x2160', 3840, 2160, 'w'),
    ('fullscreen_1920x1080', 1920, 1080, 'f'),
    ('borderless_1920x1200', 1920, 1200, 'wf'),
    ('window_return_1280x720', 1280, 720, 'w'),
]


def prepare():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, width, height, mode in CASES:
        image = OUTPUT / (name + '.png')
        command = OUTPUT / ('capture_' + name + '.txt')
        command.write_text('\n'.join([
            'getall WBP_WeaponHUD_C ResponsiveScale',
            'getall WBP_WeaponHUD_C ResponsiveCanvasSize',
            'getall WBP_WeaponHUD_C ResponsiveDPIScale',
            'getall CanvasPanel RenderTransform',
            'shot showui filename="' + image.as_posix() + '" -nosuffix',
            '',
        ]), encoding='utf-8')
        manifest.append({'name': name, 'width': width, 'height': height, 'mode': mode,
                         'resize': f'r.SetRes {width}x{height}{mode}',
                         'capture': 'exec "' + command.as_posix() + '"'})
    (OUTPUT / 'cases.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))


def png_size(path):
    with path.open('rb') as source:
        header = source.read(24)
    assert header[:8] == b'\x89PNG\r\n\x1a\n', str(path)
    return struct.unpack('>II', header[16:24])


def validate():
    log = (OUTPUT / 'Standalone.log').read_text(encoding='utf-8', errors='replace')
    lines = log.splitlines()
    results = []
    for name, width, height, mode in CASES:
        image = OUTPUT / (name + '.png')
        if not image.exists():
            results.append({'name': name, 'passed': False, 'error': 'capture missing'})
            continue
        actual = png_size(image)
        # Screenshot dimensions report the actual game window; unsupported exclusive
        # modes may be clamped by the monitor and must be reported rather than assumed.
        result = {'name': name, 'requested': [width, height], 'actual': list(actual),
                  'mode': mode, 'passed': actual == (width, height)}
        occurrences = [i for i, line in enumerate(lines) if name + '.txt' in line]
        if occurrences:
            start = occurrences[-1]
            section = '\n'.join(lines[start:start + 1000])
            for prop in ['ResponsiveScale', 'ResponsiveDPIScale']:
                values = re.findall(r'(?m)^.*WBP_WeaponHUD_C_\d+.*' + prop + r'\s*=\s*([0-9.eE+-]+)', section)
                if values:result[prop] = float(values[0])
            sizes = re.findall(r'ResponsiveCanvasSize\s*=\s*\(X=([0-9.eE+-]+),Y=([0-9.eE+-]+)\)', section)
            if sizes:
                logical_width, logical_height = map(float, sizes[0])
                result['logicalSize'] = [logical_width, logical_height]
                scale = result.get('ResponsiveScale', 0.0)
                left_right_edge = 88.0 + 328.0 * scale
                right_left_edge = logical_width - 24.0 - 500.0 * scale
                result['gapLogical'] = right_left_edge - left_right_edge
                result['layoutFits'] = (scale > 0 and result['gapLogical'] > 0 and
                                        logical_height - 24 - 260 * scale >= 0 and
                                        logical_height - 48 - 170 * scale >= 0)
                result['passed'] &= result['layoutFits']
        results.append(result)
    report = {'passed': all(r['passed'] for r in results), 'cases': results}
    (OUTPUT / 'validation.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prepare', action='store_true')
    options = parser.parse_args()
    if options.prepare:
        prepare()
    else:
        raise SystemExit(validate())
