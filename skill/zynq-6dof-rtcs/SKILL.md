---
name: zynq-6dof-rtcs
description: Work on this AX7020 Zynq-7020 PS-PL six-axis robot controller only when the user says “使用skill修改” or “使用skill解释”; use the requested edit or read-only explanation workflow.
metadata:
  short-description: AX7020 六轴机械臂修改与讲解流程
---

# Zynq-6DoF RTCS

Use this project-specific skill only after one of the following user phrases appears:

- `使用skill修改` — make the requested repository change.
- `使用skill解释` — explain the requested design or implementation without changing files.

If neither phrase appears, do not enter either workflow. Ask for the missing trigger only when the user explicitly wants this skill's workflow.

This repository targets the ALINX AX7020 (XC7Z020), with PS/Linux handling vision and planning, and PL RTL handling deterministic six-axis HX-30HM bus control. Treat the active repository as the implementation source of truth. Read [repository-guidance.md](references/repository-guidance.md) before using `Material_Library/` as a reference.

## File-path rendering

Whenever naming a repository file in an answer, report, explanation, plan, or code-review note, use its repository-relative path and retain at least the two immediate parent directories when they exist. Never use a basename alone.

- Write `src/pl/rtl/rtcs_top.sv`, not `rtcs_top.sv`.
- Keep additional leading directories when they identify the repository area: write `Material_Library/mycpu--/rtl/...`, not a shortened `rtl/...`.
- Group file lists by their parent directories, but preserve the full repository-relative path for every individual file. Use an absolute clickable link as well when the response format supports it.

## 修改 workflow

1. Restate the requested outcome and inspect the smallest relevant set of source, configuration, simulation, build, and documentation files. Check the working tree first; preserve unrelated existing edits.
2. Follow the architectural partition and register contract. Keep physical outputs disabled unless the user explicitly requests an authorized safety-gate change backed by the required evidence. Never invent mechanical calibration, pin, voltage, servo-ID, timing, or safety-limit values.
3. Make only changes necessary for the request. When a change crosses PS/PL boundaries, update every affected contract endpoint together (register documentation, RTL, PS header/application, and verification material as applicable).
4. Run the narrowest safe verification available and report what was run, what could not be run, and why. Do not represent unrun board, timing, or servo tests as passed.
5. Finish with: (a) files modified, grouped by their repository paths and rendered according to **File-path rendering**; (b) a concise modification summary; (c) verification evidence and remaining risks; and (d) a `未来展望` section with the next technically justified steps.

## 解释 workflow

This is strictly read-only: do not edit source, configuration, build files, documentation, generated artifacts, or reference projects.

1. Inspect the relevant implementation and its direct contracts first.
2. Start the answer with `相关文件` and list the relevant files grouped by path. Render every file according to **File-path rendering**. Include only files that materially participate in the question, plus any direct build/test or contract files needed to understand them.
3. Give a top-down `总体流程` before discussing individual files. Describe the PS-to-PL-to-servo data/control flow, safety gating, and return/interrupt path when they are relevant.
4. Then provide `模块逐一说明`: explain each relevant source file/module, its inputs and outputs, state/algorithm, ownership, and how it collaborates with the adjacent modules. Trace the requested signal, command, or data through the modules in execution order.
5. Clearly distinguish implemented behavior from placeholders, planned work, and reference-only examples. Include concrete limitations or safety gates that affect the answer.

## Engineering boundaries

- Preserve the command lifecycle: validate on PS, write all descriptor fields, then use `COMMAND.ENQUEUE` as the final atomic commit. A partial six-joint vector must never reach a servo.
- PS owns vision, calibration, FK/IK, task policy, deadlines, and logs. PL owns timing-critical trajectory/bus/protocol parsing, watchdogs, limits, E-stop, and deterministic scheduling.
- AXI4-Lite is the current command/status interface. Do not add DMA, HLS, ROS, or a new hardware protocol merely because a reference project uses it; require measured need and user scope.
- Do not add `Material_Library/` to build scripts, source lists, include paths, or deliverables. It is read-only reference material, and copied code requires a separate provenance/license review.
- Any request that would enable `servo_tx_en` must stop at the applicable red-line gate unless the user supplies the required measured evidence and expressly authorizes that gate change. The stage set is G0–G6 (see `docs/0.1hardware_bringup.md` to `docs/6.G6-final-delivery.md`).

## 双轨制（Dual-track gates）— 最高优先级流程约定

This repository runs **two tracks**, defined in `docs/0.1hardware_bringup.md`. Apply them whenever you gate, sequence, or review work.

- **竞赛轨（fast）** — produces a demonstrable increment every week. **Only the red-line gates apply.** All process gates are switched off.
- **归档轨（slow）** — satisfies documentation, review, and reproducibility. **Red-line + all process gates apply.**

**Red-line gates（any track, never bypassed）**: independent servo power; physical transmit-inhibit strap; PL compile-time target/speed/deadline/bus-exclusion checks; an E-stop independent of Linux/PS/PL; measured-only calibration values; at most one frame per commit; no automatic retry of an errored motion command.

**Process gates（archival track only）**: per-step `operator_confirmed` and evidence references in `config/g3_station_plan.template.json` validated by `scripts/g3_offline_plan.py`; full raw-output archiving per command; the "position feedback alone cannot prove a grasp" judgement chain; 100-cycle full logging; P99 statistics; long-run statistics.

**Rule**: **任何流程性门禁不得阻塞竞赛轨的运动路径** — no process gate may block the fast track's motion path. If a check produces only an evidence requirement and does not prevent an irreversible action, it must not be a precondition for motion on the fast track. Conversely, **red-line gates are never relaxed to make a deadline**; relieve schedule pressure by cutting feature scope, never by removing independent power, the inhibit strap, or the E-stop.

**Current stage entry conditions** (measured, 2026-10-12): board ABI `0x5254000E` flashed and verified; ID 1–5 are joints and **ID 6 is the gripper**; ID 5's narrow internal angle window is resolved. Use `docs/7.sprint-plan-daily-tasks.md` for the day-by-day plan.

## Reusable AXI peripheral bring-up baseline

These rules were merged from the repository's former generic `skill/README.md`. Apply them whenever the requested change integrates PS/Linux with a custom AXI4-Lite PL peripheral that controls physical hardware; they cover motors, sensors, and buses, not only this robot.

1. Define and version the register map before RTL and host software diverge.
2. Keep physical outputs disabled by reset and an independent safety gate.
3. Prove bus/protocol behavior with one device and a logic analyzer before multi-device operation.
4. Require an atomic descriptor commit register; never act on a partially written vector.
5. Measure and log nominal latency/jitter as well as timeout and fault paths.
6. Preserve a host-only baseline to quantify the benefit of moving work into PL.

Required inputs are the device protocol, board schematic, AXI clock, safety requirements, and a host-access method such as UIO or a driver. Expected evidence is a register-map header, RTL register bank, host smoke test, waveform capture, safety-test table, and reproducible build command.

Do not use this workflow when IO voltage or direction control is unverified, safe limits are not measured, or no independent output-disable mechanism exists. AXI register access alone is not proof that a physical interface is safe.

This baseline originated from separating Linux vision/planning from deterministic servo-bus logic in a Zynq robot. Keep it hardware-agnostic, and broaden it only after the workflow succeeds on another peripheral class.
