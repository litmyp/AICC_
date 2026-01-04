# Repository Guidelines

## Project Structure & Module Organization
The simulator tracks HPCC, HPCC-PINT, DCQCN, TIMELY, DCTCP, and ECN behaviors on top of ns-3 3.17. Core protocol logic lives under `src/` and `core/`, with corresponding ns-3 module overrides (for example `src/point-to-point/model/qbb-net-device.cc`). Scenario entry points go in `scratch/`, while ready-made topologies and traffic mixes live under `mix/` (see `mix/config.txt` and `mix/config_doc.txt`). Python utilities for config generation, automation, and testing are under `utils/` and `run.py`. Generated traces or checkpoints should be kept in `output/`-style folders or `temp*.txt` to avoid polluting the source tree.

## Build, Test, and Development Commands
- `./waf configure` (or `CC='gcc-5' CXX='g++-5' ./waf configure` on hosts where gcc>5) prepares the ns-3 build with project modules enabled.
- `./waf build` compiles the C++ components; re-run whenever `src/` changes.
- `./waf --run "scratch/third mix/config.txt"` (swap scenario + config) executes a single experiment with waf’s runner.
- `python run.py --cc hp --trace flow --bw 100 --topo topology --hpai 50` generates configs and launches simulations; start with `python run.py -h` to review flags.

## Coding Style & Naming Conventions
C++ follows the ns-3 GNU style (`indent-tabs-mode:nil`, two-space indentation, braces on new lines). Keep TypeIds and classes in CamelCase (`ns3::RdmaEgressQueue`) and members/methods in lower camel case. Prefer descriptive namespace-level constants instead of macros unless mimicking upstream ns-3. Python helpers honor pep8/pep257 with snake_case functions, four-space indents, and module-level docstrings. When adding configs, keep filenames kebab or snake case (e.g., `mix/hpcc-fat.txt`) and document semantics inside `config_doc.txt`.

## Testing Guidelines
Use `./waf --run` for targeted validation and `./waf --run "scratch/<scenario> --test_mode=1"` when adding regression flags. Continuous suites live in `test.py`; run `./test.py --suite core` for sanity or `./test.py --valgrind` when touching queueing logic. Add config-specific smoke tests to `mix/` and reference them in merge discussions. Collect flow completion time or congestion metrics in `temp.txt`/`output.txt` and attach key excerpts to reviews whenever behavior changes.

## Commit & Pull Request Guidelines
Follow the existing short, imperative summary style (`add timestamp to state`, `archive before using codex`). Group related changes together and describe experiment knobs or affected modules in the body if needed. Each PR should include: scope overview, commands/configs used for testing, notable metrics/regressions, and any new files under `mix/` or `scratch/`. Link to tracking issues, and provide screenshots or plots when telemetry changes user-visible behavior.

## Configuration & Environment Tips
The waf build inherits the host compiler; pin to GCC 5 when required for legacy ns-3 format parsing. Export deterministic seeds via `NS_GLOBAL_VALUE='RngSeed=...'` before runs. Keep long simulations in dedicated directories (e.g., `output/hpccPint/`) and add `.gitignore` entries for large trace dumps.

## Agent 专项要求
- 默认以中文回复所有需求，除非用户明确要求使用其他语言。
- 该项目仍在开发中，目标是通过强化学习训练模型替代传统拥塞控制算法调节节点发送速率，模型与通信仿真通过共享内存交互，请在撰写文档和代码时凸显这一背景。
- 在直接修改任何代码前，先列出计划调整的所有文件和修改点，确认无误后再动手，避免误操作导致仿真崩溃。
- 每处新增或修改的代码需及时补充注释，并在注释中注明 `lty added` 以便审计与追踪。
- 执行不修改代码的命令式不需要获得许可，直接执行即可；只要不改动代码，可以自由进行检索、筛选等操作。
- 若命令涉及 `rg`（如 `rg`, `rg --files` 等）可直接执行，无需额外询问或许可。
