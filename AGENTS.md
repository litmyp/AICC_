# Repository Guidelines

## Project Structure & Module Organization
- Primary simulator code lives in `simulation/`, derived from ns-3 3.17 with HPCC/HPCC-PINT, DCQCN, TIMELY, DCTCP, PFC, ECN, and Broadcom switch models.
- Core C++ modules are under `simulation/src/`; experiment entrypoints and prototypes live in `simulation/scratch/`.
- Experiment configurations are in `simulation/mix/` (e.g., `config.txt`, `config_doc.txt`, `fat.txt`). Outputs and builds land in `simulation/build/`.
- Utility scripts include `simulation/run.py` for config generation and execution, plus `simulation/utils.py` helpers. Additional examples sit in `simulation/examples/`.
- A lightweight shared-memory test stub sits in `AICC/test_shm.py`; keep it isolated from ns-3 builds unless you extend it.

## Build, Test, and Development Commands
- Configure and compile from `simulation/`: `./waf configure` (use `CC='gcc-5' CXX='g++-5' ./waf configure` if gcc > 5), then `./waf build` (or simply `./waf`).
- Run a canned scenario: `./waf --run 'scratch/third mix/config.txt'`.
- Generate and run experiments via helper: `python run.py --cc hp --trace flow --bw 100 --topo topology --hpai 50` (add `--pint_log_base`/`--pint_prob` for PINT).
- Clean build artifacts when switching toolchains: `./waf distclean`.

## Coding Style & Naming Conventions
- C++ follows ns-3 GNU style (`indent-tabs-mode:nil`, 2-space indents, header banner `c-file-style:"gnu"`). Classes and types use CamelCase; methods/variables are lowerCamelCase; constants favor ALL_CAPS.
- Keep headers minimal; prefer forward declarations in `*.h` and include-order similar to existing files (`ns3/...`, local headers, then stdlib).
- Python helpers target PEP8-ish style with 4-space indents and `snake_case` for functions/variables. Config files in `mix/` should stay consistent with the documented patterns in `mix/config_doc.txt`.

## Testing Guidelines
- Run the ns-3 test suite from `simulation/`: `./test.py -c core` for core checks, or list suites with `./test.py --list` and target with `./test.py --suite <name>`.
- For scenario-level verification, prefer reproducible commands (`./waf --run 'scratch/<scenario> mix/<config>'`) and document any custom flags in your PR.
- No formal coverage target exists; add regression scenarios in `scratch/` when fixing bugs and keep configs small so CI/local runs stay fast.

## Commit & Pull Request Guidelines
- Git history currently uses short descriptive subjects (e.g., “new code of MI_AICC, not finished yet”). Continue with a concise imperative line plus a brief body when needed; reference issues if applicable.
- Before raising a PR, ensure `./waf configure`, `./waf build`, and relevant `./test.py` suites pass; include exact commands and notable configs in the PR description.
- PRs should mention the scenario/config touched, expected outputs or traces, and any new dependencies (e.g., specific gcc version). Add screenshots or log snippets only when they clarify behavior changes.

## Agent-Specific Instructions
- 默认以中文回答，除非用户明确要求使用其他语言。
