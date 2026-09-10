# Eight-week execution plan

The scope lock is a deliverable: later weeks refine measurement and demonstration rather than replace the architecture.

| Week | Deliverable | Owner | Acceptance evidence |
| --- | --- | --- | --- |
| 1 | G0 board/bus evidence, PS7/AXI project, one-servo protocol capture | Chen + Yuan + system | ID/electrical table, waveform, bitstream build log |
| 2 | PING/READ RTL simulation and one-servo PL test; UIO register round trip | Yuan + system | packet tests, AXI test, measured response log |
| 3 | six-servo `SYNC WRITE`, calibration table, safety gates | Yuan + Chen | low-speed home/pose demo and fault tests |
| 4 | profile baseline, static pick/place, Linux-only baseline | system + Yuan | 100-cycle table, latency and jitter measurements |
| 5 | camera calibration, OK/NG classifier, fixed-position correction | system + Chen | repeatable coordinate and classification metrics |
| 6 | conveyor timing/target prediction and dynamic catch | system + Chen | deadline-hit rate and end-to-end latency |
| 7 | stress, failure injection, benchmark scripts and report data | all | long-run record, P99 jitter, resources/timing |
| 8 | scope freeze, demo script, reproducibility clean-room run, poster/report | all | tagged release and rehearsal |

The MVP ends at week 4: safe six-axis static pick/place with measured PS–PL benefit versus a Linux-only control baseline. Dynamic correction, S-curve and SYNC READ are enhancements only after that gate.
