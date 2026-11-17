# EXPERIMENT_PLAN.md

## Mục tiêu

Xây dựng hệ thống thực nghiệm phục vụ Chương 3 của đồ án theo từng giai đoạn. Không triển khai tất cả thành phần cùng lúc.

---

## Milestone 1 – Dataset pipeline

Mục tiêu:

Có thể đọc, kiểm tra và tiền xử lý ba dataset.

Cần thực hiện:

- Xây dựng dataset loader.
- Hỗ trợ đọc file .gz trực tiếp khi phù hợp.
- Hỗ trợ directed và undirected graph.
- Bỏ qua comment/header khi cần.
- Kiểm tra node count.
- Kiểm tra edge count.
- Kiểm tra duplicate edges.
- Kiểm tra self-loops.
- Loại self-loop theo cấu hình preprocessing.
- Không giả định node ID liên tục.
- Lưu metadata của dataset sau preprocessing.

Dataset:

- email-Eu-core.
- ego-Facebook.
- Wiki-Vote.

Kiểm thử:

- Số node đọc được phải khớp dữ liệu gốc.
- Số edge phải được báo cáo trước và sau preprocessing.
- Không làm thay đổi file trong data/raw.

Điều kiện hoàn thành:

Có thể chạy một command để load từng dataset và in ra thống kê của graph.

---

## Milestone 2 – Independent Cascade simulator

Mục tiêu:

Xây dựng simulator Independent Cascade.

Cần thực hiện:

- Input graph.
- Seed nodes.
- Propagation probability.
- Random seed.
- Trả về tập node cuối cùng được kích hoạt.
- Hỗ trợ directed và undirected graph.

Kiểm thử:

- p = 0 phải không lan truyền khỏi seed.
- Các graph nhỏ có kết quả xác định cần có unit test.
- Random seed giống nhau phải tạo kết quả tái lập được.

---

## Milestone 3 – Competitive Independent Cascade simulator

Mục tiêu:

Xây dựng CIC simulator cho rumor và corrective information.

Cần thực hiện:

- rumor seeds R.
- protector seeds P.
- propagation model.
- tie-breaking rule.
- random seed.
- số node cuối cùng bị misinformation ảnh hưởng.
- số node được bảo vệ.

Không tự chọn tie-breaking rule nếu PROJECT_CONTEXT.md chưa định nghĩa rõ.

Quy tắc Milestone 3 đã được chốt trong mục 3 của PROJECT_CONTEXT.md: lan truyền
đồng bộ, thu thập thành công của cả hai cascade trước khi giải quyết xung đột,
trạng thái không đổi sau activation. Tie rule phải được truyền rõ ràng;
`protector-priority` là cấu hình chính, có thêm `rumor-priority` để kiểm tra.
Thứ tự lấy mẫu CIC phải được chuẩn hóa độc lập với thứ tự chèn graph/seeds.

Kiểm thử bổ sung:

- Chỉ có một cascade, hai cascade tách biệt và cả hai tập seeds rỗng.
- Đến trước, đến đồng thời, hai tie rules và trạng thái không bị đổi về sau.
- Directed/undirected, isolated seeds, seeds không hợp lệ, `p=0/1`.
- Tái lập khi đổi thứ tự chèn nodes/edges, seed input và `PYTHONHASHSEED`.
- Giữ nguyên toàn bộ tests IC và dataset pipeline.
- Sau unit tests, chạy pilot email-Eu-core với cấu hình/kết quả lưu riêng,
  đánh dấu chỉ kiểm tra triển khai, không phải kết quả chính thức.
- So sánh SHA-256 toàn bộ raw/processed trước và sau kiểm tra.

Điều kiện hoàn thành:

Có unit tests cho các graph nhỏ mà kết quả lan truyền có thể kiểm tra bằng tay.

---

## Milestone 3.5 – Monte Carlo evaluator

- Dùng nguyên vẹn `simulate_cic()` làm lõi cho S simulation, không đổi IC/CIC.
- Sinh seed xác định bằng `base_random_seed + i`, i từ 0 đến S-1.
- Xuất mean rumor/protector/inactive, population std rumor (`ddof=0`), min/max,
  số lần mô phỏng, runtime và raw counts/seeds/steps cho từng lần.
- Kiểm thử tái lập, S=1, p=0/1, cấu hình protector tính tay, input validation,
  không sửa graph và đối chiếu raw observations với CIC trực tiếp.
- Chạy toàn bộ tests cũ/mới và pilot email-Eu-core nhỏ; lưu riêng cấu hình,
  raw results, môi trường và runtime. Pilot không dùng làm kết quả chính thức.

---

## Milestone 4A – Baseline algorithms và Monte Carlo stability

Triển khai:

- Random Selection.
- Degree Centrality.
- PageRank.

Quy tắc được ghi tại mục 6 của PROJECT_CONTEXT.md. Dùng out-degree trên graph
có hướng; PageRank trên toàn bộ graph rồi loại R khỏi candidate list. Kết quả
phải đúng k node hợp lệ, có tie-break và random seed cho Random Selection.

Kiểm tra độ ổn định trên email-Eu-core:

- Cấu hình lưu tại experiments/configs/mc_stability_email.json.
- R=[0], k=5, p=0.05, protector-priority; P rỗng và ba P baseline cố định.
- S=50,100,250,500,1000, 10 batch với các block seed không giao nhau.
- Xuất CSV/JSON cho cấu hình, P, raw observations, mean/std/SE, batch-mean SD,
  runtime Monte Carlo, selection runtime và đề xuất S có điều kiện.
- Chạy toàn bộ tests; fingerprint raw/processed và các simulator/evaluator.
- Pilot không dùng làm kết quả chính thức; chưa triển khai Greedy hoặc GA.

Mọi baseline trả về một tập gồm đúng k protector nodes.

## Milestone 4B – Greedy/Monte-Carlo

- Full Greedy đánh giá toàn bộ candidate hợp lệ tại từng bước bằng evaluate_cic,
  chọn minimum mean rumor count; tie label chuẩn hóa, chọn đủ k.
- API Candidate-Restricted Greedy riêng, pool được truyền rõ ràng; không gọi
  biến thể giới hạn candidate là Full Greedy, không thay topology graph.
- Ước lượng số calls/simulations trước khi chạy: E=k*m-k*(k-1)/2 và E*S.
  Phân biệt công thức khối lượng công việc với runtime thực đo.
- Lưu lịch sử P từng bước, mọi candidate score, số evaluations và runtime.
- Test Full Greedy trước trên graph nhỏ: k=0/đủ k/quá budget, sparse IDs,
  loại R, directed/undirected, tie, seed reproducibility và exhaustive next-step oracle.
- Pilot Full trên graph tính tay; email chỉ Candidate-Restricted top-10 degree,
  R=[0], k=2, S=20. Config: experiments/configs/greedy_email.json.
- Chạy toàn bộ tests, fingerprint raw/processed và simulator/evaluator cũ.
- Không benchmark toàn diện Facebook/Wiki-Vote; chưa triển khai GA.

---

## Milestone 5 – Genetic Algorithm

Triển khai GA gồm:

- representation;
- initialization;
- fitness;
- selection;
- crossover;
- mutation;
- elitism;
- stopping condition.

Cần kiểm tra invariant sau mỗi phép toán:

- đúng k nodes;
- không trùng node;
- node tồn tại;
- không chọn rumor seed.

Fitness sử dụng CIC simulator và Monte Carlo.

Thiết kế Milestone 5 được chốt tại mục 5 PROJECT_CONTEXT.md:

- Fitness seed cố định, cache cục bộ có thể bật/tắt; elite giữ nguyên fitness.
- Khởi tạo/random operators dùng RNG riêng, tách domain seed khỏi fitness.
- Independent final evaluation dùng seed interval mới, chỉ sau khi chốt P,
  không dùng score trong tối ưu làm kết quả cuối hay đưa hold-out vào selection.
- Tournament, intersection/union Set Crossover, one-node mutation, repair,
  elitism và đúng G generation transitions; generation 0 được log riêng.
- Hỗ trợ k=0, không ép genotype giữa các slot phải khác nhau; giữ N slot.
- Ghi convergence CSV/JSON, evaluation ledger, cache/elite reuse counters,
  tham số/seeds/runtime. Không thêm dependency hay đổi simulator/evaluator.
- Unit tests từng toán tử, invariants mỗi generation, cache/re-evaluation policy,
  elite preservation, seed replay và graph nhỏ kiểm chứng bằng tay.
- Pilot nhẹ cố định: experiments/configs/ga_pilot_email.json và
  experiments/pilot_genetic_algorithm.py; synthetic nhỏ và email-Eu-core.
- Chạy toàn bộ tests và đối chiếu SHA-256 raw/processed cùng các lõi cũ.
  Không chuyển sang Milestone 6 hoặc thực nghiệm/so sánh chính thức.

---

## Milestone 6 – Experiment runner

Xây dựng `src/experiments` và CLI `python -m experiments.run_experiment` hoặc
`python main.py experiment --config ...`. JSON khai báo rõ dataset/R policy,
k/p/tie, S_opt/S_eval, algorithm(s), GA/PageRank parameters, seed, independent
index, candidate pool, chi phí tối đa và output root. Không chọn mặc định nghiên cứu.

Quy trình: load processed graph/checksum → resolve R một lần → preflight mọi
optimizer → chọn P của mọi phương pháp → independent final evaluation cùng
S_eval/lịch seed và control P rỗng → metrics/provenance → publish output.

- Hỗ trợ đủ No Intervention/Random/Degree/PageRank/Full Greedy/Restricted/GA.
- Full Greedy exact cost `k*m-k*(k-1)//2` evaluator calls, nhân S_opt ra CIC
  count; kiểm tra explicit limits trước khi chạy, không tự thay restricted.
  GA dùng cận trên calls theo N/G/E/cache. Không coi cận calls là runtime đo được.
- Seed plan Cantor-pair (master,index), width cố định trong study, nửa block
  tối ưu/nửa final. SHA-256 domain cho R/Random/GA input. Final không feedback
  vào selection; fitness/cache/elite và toàn bộ IC/CIC/MC semantics giữ nguyên.
- Export results.csv/config.json/metadata.json/summary.json, preflight và
  selection details, convergence.csv cho GA, tùy chọn raw final observations.
  Mỗi run có directory riêng, atomic publish và từ chối overwrite/data output.
- Tách selection runtime với loading/final/total; lưu software/hardware/Git,
  R/P thực tế, seed intervals và source/artifact fingerprints.
- Unit/integration tests kiểm tra config, metrics, fairness, seed separation,
  reproducibility, k=0, giới hạn Full, graph bất biến, export và CLI.
- Chỉ smoke trên graph nhỏ và email-Eu-core; file config
  `experiments/configs/runner_smoke_email.json`, báo cáo
  `docs/MILESTONE_6_SMOKE.md`. Không main experiments/benchmark Facebook/Wiki.

Trước Milestone 7/main experiments cần xác nhận R strategy, k/p grid,
S_opt/S_eval, N/G/rates/tournament/elite/cache, candidate pools/cost limits,
số independent runs và master seeds. Các giá trị smoke không chốt thiết kế nghiên cứu.

---

## Milestone 7 – Parameter study

**Main Experiments V2 — 4 independent runs:** người dùng đã xác nhận giảm
repetitions từ 5 xuống 4 trước khi thu thập kết quả Main. Giữ nguyên sáu R,
GA reference, k=5, p=0.03, S_opt=100 và final evaluation hai batch của Protocol
v1. Ma trận có 144 primary result rows và 24 Full Greedy rows skipped theo
giới hạn chi phí. Upper bound 3.648 evaluator calls/1.392.000 CIC; runtime
projection 8.889,537 s, trong ngân sách 10.800 s. Adapter checkpoint từng
selection/batch, khóa toàn bộ P trước final evaluation và không chạy lại unit
đã hoàn tất khi resume. Đã hoàn thành 144/144 primary rows, 0 failed; actual
2.058 calls/1.233.000 CIC, active 4.436,312 s; 493/493 tests pass, checksum
67 protected files/14 data files và topology không đổi. Báo cáo và verification
ở `MAIN_EXPERIMENTS_RESULTS.md`. Protocol 5 runs dưới đây là lịch
sử, giữ nguyên để đối chiếu.

**Main Design Freeze & Preflight:** user khóa reference GA/k5/p.03/S_opt100/
protector-priority; giữ6 main R và v1 S_eval/B2. Proposal5 repeats cho6methods
=180 primary rows +30 Full Greedy skipped. Upper4.560 calls/1.740.000CIC;
runtime envelope×safety+overhead11.036,921s >cap10.800s nên STOPPED AT PREFLIGHT,
không tự giảm repeats. Main calls/CIC=0. Paired family45/within-dataset weights
đã đề xuất trước outcomes, main allocation/repeats/design vẫn cần xác nhận.
Chưa all-method B2 adapter hoặc main execution. 461 tests pass,64 existing
hashes/14 data files không đổi. Xem `MAIN_EXPERIMENTS_PROTOCOL.md`; phần dưới
ghi lịch sử screening/confirmation, không phải đang chạy thêm GA search.

**Cross-Scenario Confirmation đã hoàn thành:** 3 frozen profiles N10/N20/N40
×3 validation scenarios R858/1555/2110 ×3 repeats =27/27 GA runs. Giữ các GA
params còn lại/S/k/p/tie của v1, independent final B2. 593.000 CIC, active
2.163,03s, peak worker177,8MiB <2GiB;443 tests pass/core/data hashes không đổi.
Sáu family CIs chứa0, giữ reference làm practical candidate, không equivalence
hoặc pooled quality ranking. Các validation R đã consumed; main R mới được
reserve topology-only và main master2026111109 chưa dùng. Chi tiết
`CROSS_SCENARIO_GA_CONFIRMATION.md`; main protocol vẫn là proposal cần chốt,
không chạy Main Experiments/Full Design. Các mục dưới là lịch sử từng giai đoạn.

**Reduced Screen V2 đã thực thi theo yêu cầu mới:** 9 unique OFAT profiles ×
1 email R926 scenario ×5 repeats=45/45 GA runs, đủ ba mức mỗi panel với shared
reference. Giữ toàn bộ reference S/k/p/tie/GA params còn lại; không là Full
Design. Preflight 2.898,246 s gồm safety/overhead <10.800 s; thực đo khoảng
1.116,95 s, 914.300 CIC. CI family cả 8 contrasts chứa0 nên không winner;
reference vẫn là ứng viên tham chiếu. 415 tests pass, core/data hashes không
đổi. CSV/JSON/plots/checkpoint và báo cáo `MILESTONE_7_REDUCED_SCREEN_V2.md`.
Các trạng thái v1 dưới đây là lịch sử; Full Design/main vẫn chưa được chạy.

**Reduced Screen request mới:** user yêu cầu 5 repeats. Protocol v1 reduced
5 profiles × 3 scenarios tạo 75 runs (45 cũ là 3 repeats toàn bộ). Đã export
ma trận, 9-profile list/4-panel membership và 60 planned OFAT pairs. Projection
10.985,164 s vượt cap 10.800 s nên dừng preflight theo điều kiện A: không chạy
subset hoặc giảm repeats để vượt gate. Báo cáo `MILESTONE_7_REDUCED_SCREEN.md`,
389 tests pass, core/data checksum không đổi. Cần quyết định budget/matrix ở
bước riêng trước execution; không tự chạy Full Design 270 hoặc main experiments.

**Trạng thái sau đợt Protocol v1 trước đó:** đã xuất Experimental Protocol v1 và hoàn thành pilot
kỹ thuật Milestone 7, chưa chạy full sensitivity screen/sweep hoặc main.
Thiết kế OFAT dùng chung reference, lần lượt N/G/crossover/mutation, same R và
independent final evaluation. 9 unique profiles/12 panel rows; full270 runs/
7,3 triệu CIC vượt budget, reduced45 runs/1,026 triệu CIC chỉ là đề xuất.
Pilot được phép chỉ N10/N20 trên R926/R1210, 2 repeats: 8/8 runs, 154.200 CIC,
280,701 s, 379 tests pass; core/data/checksums giữ nguyên. Mục 3.3/3.5 xem
`EXPERIMENT_PROTOCOL_V1.md`, các bảng `docs/experiment_protocol_v1/`.

Trước milestone này đã chạy thêm **Pilot 2 – Calibration** theo yêu cầu riêng:
phân bố reachable trên mọi node; 11 fixed rumor scenarios (giữ low/legacy),
No Intervention p=.01/.03/.05/.10; S_opt calibration và independent accuracy
500/1000/2500. Báo cáo `PILOT_2_CALIBRATION.md`, 361 tests pass, core/data không
đổi. Protocol Chương 3 chỉ là draft có phân biệt đo/ngoại suy/đề xuất. Chưa
khởi động parameter study hoặc main experiments; cần xác nhận protocol trước.

Điều kiện hiện tại trước milestone này: đã hoàn thành Pilot Protocol Validation
theo yêu cầu riêng sau Milestone 6; chưa bắt đầu parameter study. Ba datasets,
hai p, ba independent algorithm/MC runs với cùng R đã lưu: 18/18 pilots và
3/3 smokes thành công; Full Greedy skipped do explicit cost limits. Cấu hình
pilot k5/S_opt20/S_eval200/GA N10 G10 không chốt thành main settings. Cần xử lý
R ít reachable của Wiki và variance p0.05 email/Facebook trước khi xác nhận
main protocol. Báo cáo `PILOT_PROTOCOL_VALIDATION.md`, 337 tests pass.

Khảo sát:

- population size;
- generations;
- mutation rate;
- crossover rate;
- protector budget k;
- propagation probability.

Mỗi lần chỉ thay đổi biến cần khảo sát trong khi giữ các biến còn lại cố định.

---

## Milestone 8 – Algorithm comparison

So sánh:

- Random.
- Degree Centrality.
- PageRank.
- Greedy/Monte-Carlo.
- Genetic Algorithm.

Các phương pháp phải chạy trong cùng điều kiện.

Các chỉ tiêu:

- misinformation spread;
- spread reduction;
- protected nodes;
- runtime;
- stability.

---

## Milestone 9 – Results export

Tạo:

- CSV tổng hợp.
- Bảng kết quả.
- Dữ liệu convergence.
- Dữ liệu parameter study.
- Các biểu đồ cần cho Chương 3.

Không tự tạo hoặc giả lập kết quả nếu experiment chưa được thực thi.
