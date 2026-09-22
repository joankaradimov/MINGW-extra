---
name: msys2-nodejs
description: Packaging Node.js applications — npm CLIs, servers, TypeScript monorepos — as MSYS2 MinGW packages in the MINGW-extra repo. Covers building from the source tag with upstream's lockfile (npm, Yarn or pnpm), bundling every npm module into the application including native addons, compiling those addons with the MinGW nodejs's node-gyp against libnode.dll and the shared MinGW libraries, pruning the installed tree, writing the command launchers, and testing the result. Use whenever the thing being packaged has a package.json or is published on npm, needs node-gyp or ships a .node addon, or when a Node addon fails to load or aborts on MSYS2. Node.js applications are the one exception to the repo's no-vendoring rule, so read this before applying that rule to anything Node.
---

# Packaging Node.js applications

Node ships software as an application plus every npm module it loads, at the versions its
authors tested, in one directory. A Node.js application in this repo is packaged the same way:
its npm modules are bundled into it, even though everything else here follows "one library, one
package". The two philosophies meet at the native boundary — npm modules are duplicated per
application, but native code inside them links the shared MinGW libraries. In Joan's words:
"The node philosophy is to duplicate. The pacman philosophy is to deduplicate."

`claude-code-router/` is a complete worked example of everything below.

"nodejs" here always means the MinGW package (`${MINGW_PACKAGE_PREFIX}-nodejs`); MSYS2 ships
no nodejs for the MSYS environment.

## Principles

**1. Build from the source tag, not the registry tarball.** A package published to npm is a
build artefact: prebuilt, often minified, usually without a lockfile, and not verifiably tied
to any commit. Build it yourself from the tagged source, the way every other package here is
built.

**2. Install exactly the lockfile upstream committed.** npm never publishes `package-lock.json`
and ignores one inside an installed package, so installing a tarball resolves every version
range on the day of the build. The same `pkgver-pkgrel` would then contain different code from
one rebuild or environment to the next. `npm ci` installs the locked tree and checks every
module against its recorded hash: the combination upstream tested, reproducibly. Yarn and pnpm
lockfiles serve the same purpose with their own tools (Phase 1).

**3. Bundle every npm module into the application — native addons too.** Node resolves
modules next to the code that loads them, and npm gives each global package its own tree. So
there are no shared `nodejs-*` library packages: each application carries its own copies, and
a second application needing the same addon carries its own copy, patches included.

**4. Native code links the shared MinGW libraries.** Deduplication happens one level down. An
addon that compiles in its own copy of a C library is rebuilt against that library's MinGW
package instead, with the bundled sources deleted so the build cannot quietly fall back to
them. For C and C++ code, the no-vendoring rule of `msys2-dependencies` applies in full.

**5. Ship only what runs.** No addon sources, build intermediates, install-time-only modules,
tests or dotfiles, and no module that a bundler has already compiled into the application's
output.

**6. Keep the build reproducible.** Upstream build scripts sometimes refresh data from the
network — catalogs, generated option lists. Skip those steps and use what the tag commits.
The one network access the build needs is the frozen install from the lockfile, and that is
hash-checked.

**7. Prebuilt tools may run at build time; nothing prebuilt ships.** For now (Joan, 2026-09-22)
the build may use prebuilt executables that upstream's toolchain expects, pinned by version and
checksum, tied to the version the lockfile names, and explained in the PKGBUILD.

MSYS2's own Node packages mostly `npm install -g` a registry tarball. That is simpler, but it
breaks principles 1, 2 and 4; do not copy those recipes.

## Native code on the MinGW nodejs

MSYS2 builds nodejs as a shared library: V8 and Node-API live in `libnode.dll`, and `node.exe`
exports neither. The Windows binaries that npm distributes are built with MSVC for the official
`node.exe`, which exports both, so none of them work here:

| What npm delivers | What happens on the MinGW nodejs |
|---|---|
| Rust (napi-rs) addon, `*-win32-x64-msvc` package | loads, prints `Node-API symbol napi_… has not been loaded`, exports nothing |
| C/C++ Node-API addon, prebuilt | `A dynamic link library (DLL) initialization routine failed`, then exit `0xC0000005` |
| C++ addon against the V8/NAN API, prebuilt | cannot load: MSVC C++ ABI against a GCC-built `libnode.dll` |
| Standalone executable (e.g. a Go or Rust binary run as a subprocess) | works — it is not an addon |

Two consequences:

- Every native addon the application loads at run time is compiled here, from source.
- A build tool that is itself a native addon cannot run on this nodejs. Use its standalone
  executable or a WebAssembly build, if it has one (principle 7).

MSYS2 could fix the first row for everyone by re-exporting Node-API from `node.exe`; that is
their package, not this repo's.

### Compiling an addon

The node-gyp bundled with the MinGW nodejs is patched for MinGW: it generates Makefiles and
links `-lnode`, but only when it runs under the MinGW python (it checks for "MINGW" in Python's
version string). Build each addon in its own directory:

```bash
pushd node_modules/<addon> >/dev/null
"${MINGW_PREFIX}"/bin/node-gyp rebuild --release --nodedir="${MINGW_PREFIX}"
popd >/dev/null
```

- `makedepends`: `${MINGW_PACKAGE_PREFIX}-cc`, `${MINGW_PACKAGE_PREFIX}-python` and the msys
  `make`.
- `--nodedir` points at the installed headers and import library. Without it, node-gyp
  downloads a headers tarball.
- Leave the result where the addon's own loader looks for it, normally
  `build/Release/<name>.node`.
- An addon is built for one `NODE_MODULE_VERSION`. When nodejs moves to a new major version,
  the package needs a `pkgrel` bump and a rebuild; say so in a comment above `depends`.

### Linking the shared library instead of a bundled copy

Add a build option instead of a hard switch, so that the patch stays upstreamable. In gyp, a
condition can turn the bundled library's target into `'type': 'none'`, remove its pieces with
the exclusion lists (`'dependencies!'`, `'sources!'`, `'include_dirs!'`), and add
`'link_settings': {'libraries': ['-l<lib>']}`. Pass it to node-gyp as `--<variable>=true`, and
delete the bundled sources in `prepare()`.

Then establish what the switch changed:

- **Defaults.** A bundled copy is often compiled with options of its own that change behaviour.
  Restore what the addon can set at run time, write down what it cannot, and check that the
  application does not rely on it.
- **Test failures.** Run the addon's own test suite. Run it again against a reference build
  that keeps the bundled copy, and treat only the failures unique to your build as yours.

### nodejs 24.19 and later abort `node::ObjectWrap` addons

From 24.19, the header-only `node::ObjectWrap` registers environment cleanup hooks, but the 24.x
runtime lacks the registry that makes removing them safe (nodejs/node#65446). Garbage
collection then aborts the process with `Assertion failed: (env) != nullptr` in
`node::RemoveEnvironmentCleanupHook`. Every addon that includes `node_object_wrap.h` and is
compiled against these headers is affected, however it is built. Compile the wrapper as it was
before 24.19:

```cpp
#include <node.h>
#define AddEnvironmentCleanupHook(isolate, fun, arg) static_cast<void>(0)
#define RemoveEnvironmentCleanupHook(isolate, fun, arg) static_cast<void>(0)
#include <node_object_wrap.h>
#undef AddEnvironmentCleanupHook
#undef RemoveEnvironmentCleanupHook
```

This is safe for addons that already close their resources on environment teardown. Check
that first. Drop the patch once the MinGW nodejs carries the fix: a 24.x release with
nodejs/node#65943, or 26.4 and later.

## Phase 0 — survey

This runs alongside `msys2-new-package` Phase 0, whose existence checks still apply.

1. **nodejs per environment.** MSYS2 builds nodejs for ucrt64, clang64, clangarm64 and mingw64,
   but not mingw32. Compare the application's `engines.node` with what the environment has.
2. **Modules that need a decision.** Install with scripts disabled (Phase 1), then look in
   `node_modules` for packages with an `install`, `preinstall` or `postinstall` script or a
   `binding.gyp`, and for per-platform binary packages (`os`/`cpu` in their `package.json`).
   npm's lockfile records the same as `hasInstallScript` and `os`/`cpu`. Sort them into what
   the application needs at run time and what only the build uses. Every run-time native
   module must be compiled here. Every build-time one needs a plan, or proof that it is
   harmless: an install script can also be a download, or just a message.
3. **What the application loads at run time.** A bundler compiles most modules into its output,
   and what it leaves external still has to ship in `node_modules`. The bundler's `external`
   setting is the authority. Cross-check a built output by searching it for `require(` and
   `import(` of package names, reading each hit in context: minified code yields false
   positives, such as code-generation strings and optional requires inside `try`/`catch`. Also
   notice code that looks for a module by path next to itself: that module can be compiled into
   the output instead of shipped separately.
4. **Upstream's build.** Work out which steps produce what you are packaging, which belong to
   other parts of a monorepo (a desktop app, docs), which fetch from the network, and which
   tools they run.
5. **What the application writes.** Per-user locations only (`apps-must-not-write-into-prefix`).
   Note any configuration it rewrites in the user's profile: the tests must never touch the
   real one.

## Phase 1 — install and build

```bash
prepare() {
  cd "${_realname}-${pkgver}"

  "${MINGW_PREFIX}"/bin/npm ci \
    --ignore-scripts --no-audit --no-fund --no-update-notifier \
    --cache "${srcdir}/npm-cache"

  patch -Np1 -d node_modules/<addon> -i "${srcdir}/0001-<addon>-<what-it-does>.patch"
  rm -r node_modules/<addon>/<bundled-library-sources>
}
```

- `--ignore-scripts` stops anything from running before you decide what should run. Nothing
  downloads an MSVC prebuilt, compiles an addon before its patches are applied, or fetches a
  desktop runtime. Build what needs building yourself, in `build()`.
- A monorepo's lockfile covers all of its workspaces, so `npm ci` installs everything,
  including the tools of parts you do not package. That costs download time, not package size.
- Patches to modules apply inside `node_modules`. Name them after the module and state the
  locked version they target (`msys2-patch-author`).
- Never edit the repository's own `package.json`: `npm ci` refuses a lockfile that no longer
  matches it. Manifest changes belong on the staged copies (Phase 2).

### Yarn and pnpm lockfiles

`yarn.lock` and `pnpm-lock.yaml` pin versions and content hashes just as npm's lockfile does,
so install them the same way: frozen, with scripts disabled, into a cache under `${srcdir}`.
Two things differ.

- **The package manager.** Use the one upstream declares: the `packageManager` field in
  `package.json`, or a Yarn release committed under `.yarn/releases` and named by
  `.yarnrc.yml`. Pin it like any other build tool (principle 7), either as a checksummed source
  or through corepack. corepack comes with the MinGW nodejs 24, and verifies the download when
  the field carries a hash. MSYS2 packages Yarn 1 as `${MINGW_PACKAGE_PREFIX}-yarn`.
- **The layout.** Staging expects npm's flat `node_modules`. Yarn 2 and later default to
  Plug'n'Play, which creates no `node_modules` at all, and pnpm defaults to a tree of links into
  its store. Both can produce the flat tree:

```bash
# yarn.lock, Yarn 1
yarn install --frozen-lockfile --ignore-scripts --non-interactive \
  --cache-folder "${srcdir}/yarn-cache"

# yarn.lock, Yarn 2 and later
YARN_NODE_LINKER=node-modules YARN_ENABLE_SCRIPTS=false YARN_ENABLE_GLOBAL_CACHE=false \
YARN_CACHE_FOLDER="$(cygpath -w "${srcdir}/yarn-cache")" \
  yarn install --immutable

# pnpm-lock.yaml
pnpm install --frozen-lockfile --ignore-scripts --config.node-linker=hoisted \
  --store-dir "${srcdir}/pnpm-store"
```

Each also leaves its own bookkeeping in `node_modules` (`.yarn-integrity`, `.yarn-state.yml`,
`.modules.yaml`, `.pnpm/`), which the stage does not copy. These commands were checked on a
small project, not yet on a packaged application.

In `build()`, compile the addons first, then build the application:

- **Prefer upstream's build code.** Drive it selectively from a small script in the package
  directory (`build.mjs`): import upstream's build configuration, call only the steps for what
  you package, and skip the network refreshes. This keeps upstream's options without its
  unwanted parts.
- **Pin substituted tools.** Where a prebuilt tool stands in for a module the lockfile pins,
  check in `prepare()` that the two versions agree, and stop if they don't.
- **Imports of absent binaries.** A desktop runtime package installed without its binary can
  throw when imported. Electron's honours `ELECTRON_OVERRIDE_DIST_PATH`, which makes the import
  return a path instead, for build or test scripts that import it without running it.

## Phase 2 — stage and install

Assemble the exact installed tree in `build()`, so that `check()` tests what `package()` ships.
Copy in what runs, rather than deleting from what npm left behind:

```bash
  local _stage="${srcdir}/stage"
  rm -rf "${_stage}"
  mkdir -p "${_stage}/node_modules/<addon>/build/Release"
  cp -r <app>/dist "${_stage}/"
  cp <app>/{package.json,LICENSE,README.md} "${_stage}/"
  cp -r node_modules/<addon>/{lib,package.json,LICENSE} "${_stage}/node_modules/<addon>/"
  cp node_modules/<addon>/build/Release/<name>.node "${_stage}/node_modules/<addon>/build/Release/"
  tar -C node_modules -c --exclude=test --exclude='.*' <its-runtime-deps> \
    | tar -C "${_stage}/node_modules" -x
```

- Copy the run-time closure of every module you keep. The lockfile shows where each dependency
  sits, hoisted or nested.
- Edit the staged manifests with `npm pkg delete`, which leaves the rest of each file
  untouched. Remove:
  - dependencies the bundler compiled in;
  - scripts that only work inside the source repository;
  - each built addon's install-time dependencies and its `install` script.
- If the application can find a module by path next to its own code, compile that module into
  the output as an extra bundler entry. That shrinks `node_modules` towards native addons only.
  Prove it with a negative control: with the module gone, the feature must fail.

`package()` copies the stage and writes one set of launchers per `bin` entry:

```bash
package() {
  local _moddir="${pkgdir}${MINGW_PREFIX}/lib/node_modules/<name-or-@scope/name>"
  mkdir -p "${_moddir%/*}" "${pkgdir}${MINGW_PREFIX}/bin"
  cp -r "${srcdir}/stage" "${_moddir}"

  "${MINGW_PREFIX}"/bin/node -e '
    const path = require("node:path");
    const [cmdShim, moduleDir, binDir] = process.argv.slice(1);
    const { name, bin } = require(path.join(moduleDir, "package.json"));
    const bins = typeof bin === "string" ? { [name.split("/").pop()]: bin } : bin;
    Promise.all(Object.entries(bins).map(([command, target]) =>
      require(cmdShim)(path.join(moduleDir, target), path.join(binDir, command))
    )).catch((error) => { console.error(error); process.exit(1); });
  ' "$(cygpath -w "${MINGW_PREFIX}/lib/node_modules/npm/node_modules/cmd-shim")" \
    "$(cygpath -w "${_moddir}")" \
    "$(cygpath -w "${pkgdir}${MINGW_PREFIX}/bin")"

  install -Dm644 "${srcdir}/stage/LICENSE" \
    "${pkgdir}${MINGW_PREFIX}/share/licenses/${_realname}/LICENSE"
}
```

- **Why not `npm install -g <stage>`:** it repacks the directory, and a bundled dependency then
  keeps only what its own `files` list names. Compiled addon output is rarely in that list.
- **The launchers.** `cmd-shim` is the module npm itself uses for global installs. It writes
  `<command>` for sh, plus `<command>.cmd` and `<command>.ps1`: the same launchers npm writes,
  and the same trio MSYS2's own Node packages ship. They run the `node.exe` beside them, so they
  work without the prefix on `PATH`.
- **Not a violation of "fix the build system, not the artefacts".** A Node application has no
  install step of its own; npm's global install is a packaging tool. So the stage is the
  install, assembled in `build()` and copied verbatim here.
- **`depends`:** nodejs, plus whatever the addons import. That means `cc-libs` for the compiler
  runtime and the MinGW package of each shared library they link. Read the imports with
  `objdump -p <name>.node | grep 'DLL Name'`.
- **Downloaded build tools** land in the package directory, and `.gitignore` covers archives,
  not `*.exe`. Keep them out of commits.

## Phase 3 — test

**In `check()`:**
- **Upstream's test suites, where they run on Windows.** Attribute each failure with a
  reference build rather than skipping it blindly. Leave a suite out only with the reason
  written down.
- **A functional test of the staged tree** through its real entry point. For a server:
  start it, drive it, stop it through its own interface. Keep the test in the package
  directory as a source file.

**Writing the functional test:**
- **Use a throwaway profile.** Point `APPDATA`, `LOCALAPPDATA`, `USERPROFILE` and `HOME` into a
  temporary directory. Node takes `os.homedir()` from `USERPROFILE` on Windows.
- **Mock the outside world on loopback,** using free ports. Code that bypasses proxies for
  loopback needs a non-loopback name, resolved only by a mock proxy, before its proxy path
  runs at all.
- **Add a negative control** for every check that could pass vacuously.
- **Spawning a `.cmd` launcher needs a shell.** Pass it one quoted command line. An argument
  array combined with `shell: true` is deprecated on current Node (DEP0190).

**In an isolated root** (`msys2-test-isolated`):
- Everything is bundled, so no `NODE_PATH` is needed. Check that the root holds no shared copy
  of what you bundled.
- Run the sh launcher directly. Run the `.cmd` one through
  `/c/Windows/System32/cmd.exe //c "<command>.cmd …"`: a bare `cmd` is MSYS2's `/usr/bin/cmd`
  wrapper, which needs the `COMSPEC` the harness clears.
- `powershell.exe` started from the harness's cleared environment prints nothing. Test the
  `.ps1` launcher from a native PowerShell session against a `--keep` root instead. There, a
  bare `<command>` resolves to the `.ps1`. Windows' default Restricted execution policy refuses
  it, which is expected; `<command>.cmd` still works.

**Process hygiene.** `/ucrt64/bin/node` is a sh wrapper, so `timeout N node …` kills the
wrapper and orphans `node.exe`. Run `node.exe` directly, and afterwards check for leftover
processes with `Get-CimInstance Win32_Process -Filter "Name = 'node.exe'"`.

## Checklist

- [ ] Source is the tag, installed frozen from its lockfile (npm, Yarn or pnpm)
- [ ] Native and platform-specific modules found: every run-time one compiled here, every
      build-time one decided
- [ ] What the application loads at run time established; everything else pruned
- [ ] Addons built with the MinGW node-gyp and `--nodedir`, linked to shared MinGW libraries,
      bundled library sources deleted, behaviour differences written down
- [ ] `node::ObjectWrap` addons patched while the MinGW nodejs lacks the cleanup-hook registry
- [ ] Prebuilt build tools pinned by version and checksum, and checked against the lockfile
- [ ] No network refreshes in the build
- [ ] Staged tree is the installed tree; manifests match it
- [ ] Launchers written by `cmd-shim`; `depends` covers nodejs and every DLL the addons import
- [ ] `check()`: upstream suites with attributed failures, plus a functional test of the stage
- [ ] Isolated root: sh and `.cmd` launchers and the functional test pass; `.ps1` checked
      natively
- [ ] Rebuild-on-nodejs-major noted above `depends`

## Sources

The MSYS2 nodejs PKGBUILD and its `0103-node-gyp-support-mingw-toolchain.patch`. npm's
documentation for `package-lock.json`, `npm-shrinkwrap.json` and `npm ci`; Yarn's for
`--frozen-lockfile`, `--immutable` and `nodeLinker`; pnpm's for `--frozen-lockfile` and
`node-linker`. nodejs/node#65446
and #65943. The worked example, `claude-code-router/`.
