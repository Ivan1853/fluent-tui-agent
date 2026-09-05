# Fluent 2022 R1 compatibility notes

Author: Manuel Sun

Authority order: running v221 menu/prompt and observed command results → installed 22.1 version metadata/documentation → version-matched external documentation → model-generated candidate. No PyFluent or Python Solver API is used.

The creation workstation exposed `AWP_ROOT221` and `ANSYS221_DIR` pointing to a local v221 installation, executable file version 22.1.0, and runtime `Welcome to ANSYS Fluent 2022 R1`, Build Time Nov 29 2021, Build Id 10213. These are local observations, not assumptions about every installation.

Verified on that installation:

- `fluent.exe 3ddp -g -t1`: one-rank Solver, console via ordinary subprocess PIPE, v221 root prompt after license/node startup.
- `/report/system/sys-stats`: actual Hostname/CPU/System Mem output and root prompt.
- Empty line in a menu: menu listing. `/report/system` followed by empty line: `gpgpu-stats`, `proc-stats`, `sys-stats`, `time-stats`. `q` returned to root.
- `?`: `[help-mode]>`, not a menu list. This mode explicitly describes `q` as return to command mode.
- `/file/start-transcript`, `/file/stop-transcript`, `-i`: actual journal/transcript run.
- `(display "unique-marker")` followed by `(newline)`: independent output marker. In this v221 journal reader, `\n` inside a display string was printed literally, so the wrapper does not depend on C/Python-style string escape behavior.
- `/file/read-case` read the included ASCII `.msh` test fixture. Menu availability changed after loading a mesh: write-case/data commands need appropriate solver state.
- `/file/write-case-data "unique-path/state.cas.h5"` produced actual `.cas.h5` and `.dat.h5` files.
- `/solve/patch` produced case-specific prompts. On the simple pressure fixture, after `pressure` it directly showed `Value (constant or expresssion) (in [Pa]) [0]`; the extra custom-field-function yes/no prompt in the requested simulated test did not appear.

Do not force these observations onto another model configuration. The simulated CFF prompt remains covered in unit tests. The real prompt spelling `expresssion` is intentional and should not break the parser.

An invalid symbolic zone produced `Invalid cell zone.` followed by `Error: eval: unbound variable`, without a fresh final prompt. The driver conservatively reported an unverified state and stopped. It did not claim a successful automatic repair of that stalled reader.

The included one-cell cube is an interaction fixture with positive volume. A mesh check warns that the single cell has only wall faces; it is not a validated engineering flow domain and is not used for long iterative CFD validation.

The closed-wall fixture returned 0 Pa after uniform pressure patching even though the input completed. Ansys describes subtraction of reference pressure after patching in closed incompressible/steady domains; see the [gauge-pressure patching note](https://innovationspace.ansys.com/courses/courses/topics-in-convective-heat-transfer-simulations/lessons/guage-pressure-patching-issues-in-ansys-fluent-natural-convection-modeling/). The reference-pressure explanation was a physical hypothesis, not a reason to alter a user's model automatically. A separate `unit_cube_open.msh` test fixture with one pressure-outlet face passed mesh/check and returned **486540 Pa** in a real volume-weighted Static Pressure report after patching. Restoring its checkpoint returned **0 Pa**. These observations are summarized in [TEST_REPORT.md](../TEST_REPORT.md); raw local evidence is not published.

ConPTY was actually attempted on this workstation. The native API created the process, but only terminal control sequences arrived and no Fluent prompt appeared before timeout. It is **unavailable on this tested setup**; the verified Interactive transport is PIPE. The automatic transport selector records this failure and exposes Journal as fallback; it never marks ConPTY available without its probe passing.

No automatic `set-tui-version` is injected. Its presence in a menu is not proof of accepted argument syntax. Record/test the v221 syntax before adding it to a journal. Do not import newer PyFluent-generated TUI paths as authoritative v221 commands.

Public documentation search during creation mostly returned newer Ansys releases; those pages were not used as proof of v221 compatibility. Retained private test logs are the direct evidence for the commands listed above; the public report states their scope and limits. Windows ConPTY API reference: [Microsoft pseudoconsole sessions](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session).
