#!/usr/bin/env python3
"""
Simple bundler for Contortion Fighter.
Strips ES module import/export syntax and concatenates JS files in dependency
order into a single self-contained bundle.html.
No npm, no bundler, no dependencies.
"""
import os, re, sys

SRC = 'src'

# Dependency order — each file is included exactly once.
MODULES = [
    'engine/stateMachine',
    'engine/physics',
    'engine/collision',
    'engine/loop',
    'input/motionBuffer',
    'input/keyboard',
    'game/stage',
    'game/round',
    'characters/backbender',
    'characters/characterBase',
    'render/postfx',
    'render/fighterRenderer',
    'render/ui',
    'render/renderer',
    'main',
]

HTML_HEAD = '''<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Contortion Fighter</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      background: #0a0010;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      overflow: hidden;
      font-family: monospace;
    }
    #wrapper {
      box-shadow:
        0 0 0 2px #1a0030,
        0 0 30px 8px rgba(120, 0, 200, 0.4),
        0 0 80px 20px rgba(80, 0, 150, 0.2);
      border-radius: 4px;
    }
    #game {
      display: block;
      width: 1280px;
      height: 720px;
      image-rendering: pixelated;
      image-rendering: crisp-edges;
      border-radius: 4px;
    }
    #controls {
      margin-top: 12px;
      color: rgba(180, 120, 255, 0.6);
      font-size: 11px;
      text-align: center;
      letter-spacing: 0.5px;
    }
    #controls span { color: rgba(255, 200, 80, 0.7); }
  </style>
</head>
<body>
  <div id="wrapper">
    <canvas id="game"></canvas>
  </div>
  <div id="controls">
    P1: <span>WASD</span> move &nbsp;|&nbsp;
    <span>F G H</span> LP/MP/HP &nbsp;|&nbsp; <span>R T Y</span> LK/MK/HK
    &nbsp;&nbsp;&nbsp;
    P2: <span>ARROWS</span> move &nbsp;|&nbsp;
    <span>J K L</span> LP/MP/HP &nbsp;|&nbsp; <span>U I O</span> LK/MK/HK
    &nbsp;&nbsp;&nbsp;
    <span>`</span> hitboxes &nbsp;|&nbsp; <span>ESC</span> pause
  </div>
<script>
// Contortion Fighter — single-file bundle
// Built by build.py from src/ — do not edit directly.
// =====================================================================
'''

HTML_FOOT = '''
// =====================================================================
</script>
</body>
</html>
'''


def strip_module(path):
    """Remove import/export ES module boilerplate, keep the logic."""
    with open(path, encoding='utf-8') as f:
        lines = f.readlines()

    result = []
    skip_until_semi = False   # inside a multi-line import or re-export block

    for line in lines:
        stripped = line.strip()

        # Close multi-line skip on the line containing the semicolon
        if skip_until_semi:
            if ';' in line:
                skip_until_semi = False
            continue

        # Multi-line import: starts with 'import ' but no ';' on same line
        if re.match(r'^\s*import\s', line) and ';' not in line:
            skip_until_semi = True
            continue

        # Single-line import
        if re.match(r'^\s*import\s.*;\s*$', line):
            continue

        # Multi-line re-export: export { ... (no ; yet)
        if re.match(r'^\s*export\s*\{', line) and ';' not in line:
            skip_until_semi = True
            continue

        # Single-line re-export: export { X, Y };
        if re.match(r'^\s*export\s*\{[^}]*\};\s*$', line):
            continue

        # 'export default X' → 'const _defaultExport = X'  (edge case guard)
        if re.match(r'^\s*export\s+default\s', line):
            line = re.sub(r'export\s+default\s', 'const _defaultExport = ', line, count=1)
            result.append(line)
            continue

        # 'export function/class/const/let/var' → strip 'export '
        if re.match(r'^\s*export\s+(function|class|const|let|var|async)', line):
            line = re.sub(r'export\s+', '', line, count=1)
            result.append(line)
            continue

        result.append(line)

    return ''.join(result)


def deduplicate_consts(content):
    """
    When modules are concatenated, same-named top-level const/let/var declarations
    from different files collide. Keep the first occurrence, strip subsequent ones.
    """
    seen = set()
    lines = content.split('\n')
    result = []
    for line in lines:
        stripped = line.strip()
        m = re.match(r'^(?:const|let|var)\s+([A-Za-z_$]\w*)', stripped)
        if m:
            name = m.group(1)
            if name in seen:
                result.append('// [bundled: ' + stripped + ']')
                continue
            seen.add(name)
        result.append(line)
    return '\n'.join(result)


def build(out_path='bundle.html'):
    parts = [HTML_HEAD]

    for mod in MODULES:
        path = os.path.join(SRC, mod + '.js')
        if not os.path.exists(path):
            print(f'WARNING: {path} not found, skipping', file=sys.stderr)
            continue
        parts.append(f'\n// ═══ {mod}.js ═══════════════════════════════════\n')
        parts.append(strip_module(path))

    parts.append(HTML_FOOT)

    # Deduplicate const/let/var clashes from same-named module-level declarations
    combined = ''.join(parts)
    combined = deduplicate_consts(combined)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(combined)

    size = os.path.getsize(out_path)
    print(f'Built {out_path} ({size:,} bytes)')


if __name__ == '__main__':
    build()
