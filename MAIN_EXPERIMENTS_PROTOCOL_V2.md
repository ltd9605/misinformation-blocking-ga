# Main Experiments Protocol V2 — Four Independent Runs

User xác nhận ngày12/11/2026: giảm repetitions5→4/scenario để giữ cap10.800s.
Đây là revision trước bất kỳ main observation nào, không phải adaptive stopping.
Giữ nguyên [protocol5runs](MAIN_EXPERIMENTS_PROTOCOL.md) và JSON/artifacts cũ.

## Frozen design

6R nguyên trạng: email485/374,Facebook714/2733,Wiki1961/1795;3 processed graphs,
k5/p.03/protector-priority. GA N10/G10/crossover.8/mutation.1/tournament3/elite1/
cacheTrue/S_opt100. Candidate-Restricted pool10 theo out-degree/degree ngoàiR;
Degree cùng ranking rule;PageRank alpha.85/tol1e-12/max_iter1000;Random có seed.
S_eval6000/batch email,2500/batch Facebook/Wiki,B2, cùng final schedules giữa6
methods mỗi comparison. 6R×4×6=144 result rows. Full Greedy24 rows skipped theo
calls100/CIC2000, không thay tên Restricted. Không reselect R hoặc retune GA.

## Preflight

Selection upper3360 evaluator calls/336.000CIC; final288calls/1.056.000CIC,
gồm48 shared NI calls; tổng**3648calls/1.392.000CIC**. Projection theo đúng rate
evidence v1, không update bằng main results: **8889.537s**
(safety1.5+overhead300), headroom**1910.463s** so với10800.
Runtime là proxy, không là hard bound. RAM worker2GiB/parent512MiB/concurrency1,
selection timeout900s,final120s/batch, tất cả bị giới hạn bởi active budget còn lại.

| Dataset | R | Calls upper | CIC upper | Proxy safety1.5 s, chưa shared overhead |
|---|---|---:|---:|---:|
| Wiki-Vote | [1961] | 608 | 176000 | 946.48 |
| Wiki-Vote | [1795] | 608 | 176000 | 946.48 |
| ego-Facebook | [714] | 608 | 176000 | 2718.13 |
| ego-Facebook | [2733] | 608 | 176000 | 2718.13 |
| email-Eu-core | [485] | 608 | 344000 | 630.16 |
| email-Eu-core | [374] | 608 | 344000 | 630.16 |

## Seeds, checkpoints and analysis

Giữ main master2026111109,ordinal11..16,index=scenario_index*100+repeat0..3;
dùng4 trong10 slots đã reserve, không tiêu thụ6 slots còn lại. Optimization
100seed đầu block;final nửa sau với hai batch bases. GA/Greedy chia sẻ opt
schedule trong comparison; mọi method cùng final schedule. Kiểm tra interval
không trùng calibration/M7/confirmation và không giao opt/final, bảng JSON kèm.

Adapter mới gọi nguyên `_select()` Milestone6 và `evaluate_cic()`, không gọi
one-batch runner hai lần. Toàn bộ144P được checkpoint/hash và seal trước final.
288final batches checkpoint riêng, controls một lần/batch, raw counts giữ đủ.
Resume xác minh config/core/graph/P/seed hashes, bỏ qua completed units, charge
upper CIC/timeout cho unknown partial work; không reset budget. Runtime tách
selection/fitness-subset/final/loading/import/guard/export/total active.

Statistical policy v1 giữ nguyên:30scenario contrasts GA−5comparators +15
equal-weight within-dataset contrasts, approximate Bonferroni family45; nay
CI qua4 paired runs/bundles,df3. Không pool effects giữa datasets. Spread
reduction là1−ratio-of-means, không clip số âm; descriptive paired Fieller
sets có thể bounded/unbounded/disjoint. Dataset average của hai scenario
ratios dùng conservative sum của hai97.5%Fieller sets (descriptive95% coverage
xấp xỉ). Chưa có equivalence margin; CI chứa0 là chưa đủ bằng chứng, không
equivalence. Tách conditional MC variance, algorithm-run variability và
scenario heterogeneity; deterministic NI/Degree/PageRank không tạo thêm
selection randomness. n4 có uncertainty/power yếu hơn n5; không đổi repeats
hoặc lọc low/no-spread R sau outcomes. Training fitness chỉ diagnostic.

Các file: [configV2](experiments/configs/main_experiments_protocol_v2.json),
[matrixCSV](docs/main_experiments_protocol_v2/matrix.csv),
[preflightJSON](docs/main_experiments_protocol_v2/preflight.json),
[seed audit](docs/main_experiments_protocol_v2/seed_separation_audit.json).
Main results xuất riêng MAIN_EXPERIMENTS_RESULTS.md và docs/main_experiments_results.
