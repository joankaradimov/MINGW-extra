---
name: msys2-licensing
description: The license() field and license file installation for MSYS2 / MinGW-w64 packages — SPDX expressions and the "spdx" prefix, combining licenses with AND/OR, custom LicenseRef identifiers, and the required share/licenses path. Use when setting or correcting the license field of a PKGBUILD, or when a package ships no license file.
---

# Licensing an MSYS2 package

## The `license=()` field

MSYS2 prefers SPDX expressions, prefixed with `spdx:`. 3015 of 3361 upstream PKGBUILDs use
this form. Use it for all new packages in this repo.

```bash
license=('spdx:MIT')
license=('spdx:GPL-2.0-or-later')
license=('spdx:LGPL-2.1-only')
license=('spdx:Apache-2.0')
license=('spdx:BSD-3-Clause')
```

Do not use bare Arch-style values (`'GPL'`, `'GPLv2+'`, `'LGPL'`, `'MIT'`). Values not
prefixed with `spdx:` fall back to Arch Linux conventions, and **mixing SPDX and non-SPDX
values in the same array is not recommended**.

### Combining licenses

Within a single `spdx:` string, use SPDX operators:

```bash
# package contains Apache-2.0 source, a vendored MIT library, and CC-BY-4.0 docs
license=('spdx:Apache-2.0 AND MIT AND CC-BY-4.0')

# dual-licensed, licensee chooses
license=('spdx:MIT OR Apache-2.0')
```

Multiple separate `spdx:` array entries are combined with **OR**:

```bash
license=('spdx:LGPL-2.1-only' 'spdx:MPL-1.1')   # means LGPL-2.1-only OR MPL-1.1
```

That is a common mistake: if the package is genuinely *both*, use one entry with `AND`.

### Common mappings from old-style values

| Old | SPDX |
|---|---|
| `GPL`, `GPLv2` | `spdx:GPL-2.0-only` |
| `GPLv2+` | `spdx:GPL-2.0-or-later` |
| `GPL3` | `spdx:GPL-3.0-only` |
| `LGPL`, `LGPL2.1` | `spdx:LGPL-2.1-only` |
| `LGPL2.1+` | `spdx:LGPL-2.1-or-later` |
| `BSD` | `spdx:BSD-2-Clause` or `spdx:BSD-3-Clause` — read the file, they differ |
| `MIT` | `spdx:MIT` |
| `custom` | see below |

Never guess between `-only` and `-or-later`, or between BSD variants. Read the actual license
header in the source.

### Custom or unlisted licenses

```bash
license=('spdx:LicenseRef-my-special-license')
```

The idstring after `LicenseRef-` may contain `[A-Za-z0-9.-]`. Use this when the project's terms
have no SPDX identifier. The license text must be installed (see below) — for a
`LicenseRef-`, that installed file is the only authoritative statement of the terms.

### Advertised vs actual

If a project advertises a single license (say GPL-2.0-or-later) while containing incidental
code under other terms, using only the advertised license is acceptable. Do not audit the whole
tree; follow what upstream states.

### Split packages

Components may declare different licenses. Set `license=()` inside the relevant
`package_<name>()` function to override the top-level value.

## Installing the license file

Required path:

```
${MINGW_PREFIX}/share/licenses/<real-package-name>/<file>
```

`<real-package-name>` has **no environment prefix**. For `mingw-w64-ucrt-x86_64-aubio` the real
name is `aubio`, giving `/ucrt64/share/licenses/aubio/COPYING`.

```bash
package() {
  ...
  install -Dm644 "${_realname}-${pkgver}/COPYING" \
    "${pkgdir}${MINGW_PREFIX}/share/licenses/${_realname}/COPYING"
}
```

Using `${_realname}` gets this right automatically. Using `${pkgname}` does not — it would
embed the environment prefix in the path.

For Python packages the real name conventionally includes the `python-` part:
`share/licenses/python-${_realname}/LICENSE`.

Install every distinct license file the project ships (`COPYING`, `COPYING.LESSER`, `LICENSE`,
`NOTICE`, per-component licenses). If the project ships none — which happens — record that in
the PKGBUILD as a comment rather than inventing a file.

## Checklist

- [ ] `license=()` uses `spdx:` values only
- [ ] `AND` vs `OR` reflects reality; separate array entries mean OR
- [ ] `-only` vs `-or-later` verified against the source headers
- [ ] license file installed to `share/licenses/${_realname}/`, no environment prefix in the path
- [ ] all distinct license files shipped

## Sources

<https://www.msys2.org/dev/package-licensing/>.
