# Vendored libraries — upgrade procedure

The Be Civic dossier renderer depends on two pure-Python libraries and four font families. They are vendored into the plugin so the renderer works **with zero install steps** on the user's machine (no `pip install`, no `npm install`, no system libraries beyond `python3`).

This file documents the pinned versions, the smoke-test procedure, and the upgrade ritual.

## Pinned versions (last verified 2026-05-19)

| Component | Version | License | Source |
|---|---|---|---|
| **fpdf2** | 2.8.7 | LGPL-3.0 | https://pypi.org/project/fpdf2/ |
| **pypdf** | 6.11.0 | BSD-3-Clause | https://pypi.org/project/pypdf/ |
| **Inter** | 4.1 | SIL OFL 1.1 | https://github.com/rsms/inter/releases/tag/v4.1 |
| **Source Sans 3** | 3.052R | SIL OFL 1.1 | https://github.com/adobe-fonts/source-sans/releases/tag/3.052R |
| **Noto Sans Arabic** | v2.013 | SIL OFL 1.1 | https://github.com/notofonts/arabic/releases/tag/NotoSansArabic-v2.013 |
| **Noto Sans** (Latin + Cyrillic + Greek) | v2.015 | SIL OFL 1.1 | https://github.com/notofonts/latin-greek-cyrillic/releases/tag/NotoSans-v2.015 |

## License posture

- **fpdf2 is LGPL-3.0.** We vendor an unmodified copy and call it as a library. Under LGPL §5, this is permitted without our code becoming LGPL. If you ever **modify** the vendored fpdf2 source, the modifications themselves are LGPL — keep modifications upstream-bound to avoid this.
- **pypdf is BSD-3-Clause.** Permissive; no obligations beyond preserving the copyright notice (in `vendor/pypdf-6.11.0.dist-info/licenses/LICENSE`).
- **All fonts are SIL OFL 1.1.** Embedding in PDFs is explicitly permitted. Don't sell the fonts as fonts (we don't).

Each vendored directory carries its own LICENSE file alongside the binaries.

## Directory layout

```
vendor/
├── fpdf/                          # fpdf2 source tree, importable as `import fpdf`
├── fpdf2-2.8.7.dist-info/         # pip metadata for fpdf2 (RECORD, METADATA, LICENSE)
├── pypdf/                         # pypdf source tree, importable as `import pypdf`
├── pypdf-6.11.0.dist-info/        # pip metadata for pypdf
├── fonts/                         # all flat — paths baked into Stream B templates
│   ├── Inter-Regular.ttf          # Inter (UI / headers)
│   ├── Inter-Bold.ttf
│   ├── Inter-Italic.ttf
│   ├── Inter-BoldItalic.ttf
│   ├── SourceSansPro-Regular.ttf  # Source Sans 3, renamed to legacy "SourceSansPro"
│   ├── SourceSansPro-Bold.ttf     #   alias so Stream B templates resolve.
│   ├── SourceSansPro-Italic.ttf   #   (Adobe renamed the project from Source
│   ├── SourceSansPro-BoldItalic.ttf #   Sans Pro -> Source Sans in 2024; the
│   │                              #   file content is the current 3.052R release.)
│   ├── NotoSansArabic-Regular.ttf # Arabic conversation language
│   ├── NotoSansArabic-Bold.ttf
│   ├── NotoSans-Regular.ttf       # Latin + Cyrillic + Greek (Ukrainian = Cyrillic)
│   ├── NotoSans-Bold.ttf
│   └── LICENSES/                  # OFL / license files for every font above
│       ├── Inter-LICENSE.txt
│       ├── SourceSans-LICENSE.md
│       ├── NotoSansArabic-OFL.txt
│       └── NotoSans-OFL.txt
└── UPGRADING.md                   # this file
```

**Import convention.** `render.py` adds `<plugin>/vendor/` to `sys.path`. From there, `import fpdf` and `import pypdf` both resolve. The dist-info directories sit alongside but are not imported; they exist for future-you to read the version when debugging.

**Font path convention.** Flat. Both the Python renderer (`be_civic_dossier`) and the HTML templates Stream B authored (`skills/bc-dossier-compilation/templates/*.html`) reference fonts at `vendor/fonts/<FamilyName>-<Weight>.ttf` — no per-family subdirectories. The Source Sans 3 files are renamed to the legacy `SourceSansPro-*` naming because that's what Stream B's `@font-face` rules declare; the underlying file content is the current 2024 3.052R release.

## Smoke test — run this before bumping any version

The vendoring constraint is **pure Python, zero C extensions, runs on any Python 3 platform with no compile step**. Test with:

```bash
mkdir -p /tmp/W25-smoke-test
pip download fpdf2 pypdf -d /tmp/W25-smoke-test/ --no-deps
ls /tmp/W25-smoke-test/
# Both files must end with `py3-none-any.whl` (universal pure-Python tag).
# If you see `cp312-cp312-linux_x86_64.whl` or similar, that's a C-extension
# wheel — STOP and investigate. We do NOT vendor anything with native code.

python3 - <<'EOF'
import zipfile
for w in ['/tmp/W25-smoke-test/fpdf2-2.8.7-py3-none-any.whl',
          '/tmp/W25-smoke-test/pypdf-6.11.0-py3-none-any.whl']:
    z = zipfile.ZipFile(w)
    names = z.namelist()
    native = [n for n in names if n.endswith(('.so','.pyd','.dll','.c','.h','.cpp','.pyx'))]
    print(w, 'native_files:', native or 'none')
EOF
# Both must report `native_files: none`.
```

**Do not use `pip download --no-binary :all:`.** That flag forces source-only for every transitive dependency, which makes pip pull `cmake`, `ninja`, `pybind11` — build-system requirements for *other* packages. Those tools are not part of fpdf2 or pypdf themselves; the wheel-tag check is the right signal.

After the smoke test passes, run the **round-trip test** to confirm the vendored layout still works end-to-end:

```bash
cd be-civic-plugin/vendor && python3 -c "
import sys
sys.path.insert(0, '.')
import fpdf, pypdf
p = fpdf.FPDF(); p.add_page(); p.set_font('helvetica', size=12)
p.cell(0, 10, 'smoke test')
print('fpdf bytes:', len(bytes(p.output())))
print('fpdf version:', fpdf.FPDF_VERSION)
print('pypdf version:', pypdf.__version__)
"
```

Both versions must print, and `fpdf bytes` must be a positive integer.

## Upgrade ritual

When a new release of fpdf2 or pypdf lands and you want to bump:

1. **Smoke test the new version against the procedure above.** If either wheel is no longer `py3-none-any`, HALT. The Be Civic constraint is no C extensions ever; if upstream regresses to a native build, we pin to the last pure-Python version and stay there.
2. **Download the wheel** and extract its contents.

   ```bash
   pip download fpdf2==<new-version> -d /tmp/upgrade-stage --no-deps
   unzip -q /tmp/upgrade-stage/fpdf2-<new-version>-py3-none-any.whl -d /tmp/upgrade-stage/fpdf2-extracted
   ```

3. **Replace the package directory.** The extracted `fpdf/` (or `pypdf/`) replaces the existing `vendor/fpdf/` (or `vendor/pypdf/`). The matching `<name>-<version>.dist-info/` replaces the old dist-info.

   ```bash
   rm -rf be-civic-plugin/vendor/fpdf be-civic-plugin/vendor/fpdf2-*.dist-info
   cp -r /tmp/upgrade-stage/fpdf2-extracted/fpdf be-civic-plugin/vendor/fpdf
   cp -r /tmp/upgrade-stage/fpdf2-extracted/fpdf2-<new-version>.dist-info be-civic-plugin/vendor/
   ```

4. **Run the round-trip smoke test** (above). It must still pass.
5. **Run the dossier renderer's golden-file test** (`scripts/be_civic_dossier/tests/test_golden.py`, once it exists). Re-runs must produce byte-identical PDFs against the recorded fixtures. If a version bump changes output bytes, treat as a design decision: either re-record the fixtures (with a CHANGELOG note) or pin to the prior version.
6. **Update this file:** bump the pinned-versions table, update the `last verified` date in the section header, note any user-visible changes from upstream's CHANGELOG.
7. **Commit as a single change** named `vendor: bump fpdf2 to <version>` (or pypdf). Don't bundle a vendor bump with logic changes — keep the diff easy to audit.

## Upgrade ritual — fonts

Fonts change rarely. When they do (operator request, glyph coverage gap, foundry release):

1. Download the new release from the official source listed in the pinned-versions table.
2. Replace only the TTFs we use (Regular / Bold / Italic / BoldItalic for Latin; Regular / Bold for Noto). Do not bundle more weights — every byte ships to the user.
3. Replace the LICENSE/OFL file in the same directory.
4. Render a one-page test that includes a sample of every script the font covers (Latin + accented Latin for Inter/Source Sans; Cyrillic for Noto Sans; Arabic RTL for Noto Sans Arabic). Eyeball the rendering.
5. Update the pinned-versions table.

**Why we don't use system fonts.** Be Civic targets reproducible PDF rendering. System font availability varies by OS, distro, and user install; the same input must produce the same output. Bundling our font set is the only way to guarantee that — and it adds ~5 MB to the plugin, which is acceptable.

## Why fpdf2 + pypdf and not something else

Decision recorded in `docs/agent-ux/dossier-rebuild-design.md` §7. Summary:

- **fpdf2** generates new pages (cover, checklist, dividers, placeholders, filled forms). Pure Python, mature, decent Unicode support via `add_font()`.
- **pypdf** handles existing PDFs (merge, rotate, watermark overlay). Pure Python; the official pypdf2 successor.
- **NOT** `weasyprint` (needs `cairo` / `pango` system libs), `reportlab` (optional C-extension performance path, Unicode regressions without it), `Pillow` (C extensions for image ops; we use `pypdf.Page.rotate()` instead), `pandoc` / `xelatex` (was W24's render path, source of the determinism issues this rebuild fixes).

The day this trade-off changes — e.g. weasyprint ships with a pure-Python rendering fallback, or fpdf2 regresses to needing a C build — revisit by editing `docs/agent-ux/dossier-rebuild-design.md` §7 first, then this file.
