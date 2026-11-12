# Main Experiments Protocol — Design Freeze & Computational Preflight

**Trạng thái: BLOCKED AT PREFLIGHT.** Đã khóa GA theo yêu cầu người dùng; ma trận và phân
tích main là thiết kế reviewable, chưa được xác nhận để thực thi. Đã chạy
**0 main evaluator calls, 0 main CIC simulations**. Không có số đo chất lượng
main, không gọi GA/baseline/evaluator trên sáu R main. Projection không được
trình bày như runtime thực đo hoặc hard upper bound.

## 1. Các thông số khóa và lựa chọn còn cần xác nhận

GA **N10/G10, crossover0.8, mutation0.1, tournament3, elitism1, cache=True**;
S_opt100, p=.03, k5, protector-priority. Không tiếp tục điều chỉnh GA sau khi
thấy main outcomes. Khóa theo yêu cầu hiện tại, không tuyên bố đây là cấu hình
tối ưu/tương đương từ các CI chứa0 của confirmation. Frozen Protocol-v1 JSON
và các báo cáo trước giữ nguyên; file main specification là phiên bản riêng.

S_eval email6.000/batch; Facebook/Wiki2.500/batch, B=2; pooled final S12.000/
5.000 mỗi P. Candidate-Restricted Greedy top10 out-degree với directed graph,
degree với undirected, ngoài R; score ties ascending actual integer ID.
Degree ranking cũng theo out-degree/degree. PageRank alpha=.85,tol=1e-12,
max_iter1000, weight=None như Pilot2. Random chọn đúng5 distinct nodes ngoàiR
bằng seed đã reserve, không giả định ID liên tục. Mọi method giữ semantics cũ.

**Đề xuất 5 independent runs/scenario/method**, chưa xác nhận. Request
nêu rationale cho lựa chọn này; không tuyên bố đã có power analysis. 10 slots
reserve trước đây chưa phải main repeat count đã duyệt. Ma trận đề xuất bị chặn nếu admission fail;
không tự đổi thành4/3 rồi gọi đó là thiết kế đã chốt.

## 2. Kiểm tra sáu rumor scenarios bảo lưu

Đã tái tạo đúng sampling SHA256/Random master2026111112 của confirmation:
uniform actual IDs trong high stratum (>2/3 reachable maximum), hoặc constant
cho Facebook, loại mọi R trong Pilot2 manifest. Đối chiếu thêm R tuning/
confirmation, Protocol Validation R577/2162/4341 và email smoke R0: không trùng.
Không dùng GA/baseline quality để chọn lại, không đổi R hoặc sinh lại sample.
Source JSON/CSV và sampling seed/hash được lưu nguyên ở scenarios.json.

| Dataset | R | Stratum | Reachable (gồm R) | Out-degree/degree | In-degree | SCC/component | WCC/component | Analytic NI no-growth |
|---|---|---|---:|---:|---:|---:|---:|---:|
| email-Eu-core | [485] | high | 965 | 19 | 26 | 803 | 986 | 56.06% |
| email-Eu-core | [374] | high | 965 | 17 | 8 | 803 | 986 | 59.58% |
| ego-Facebook | [714] | constant | 4039 | 14 | — | 4039 | 4039 | 65.28% |
| ego-Facebook | [2733] | constant | 4039 | 24 | — | 4039 | 4039 | 48.14% |
| Wiki-Vote | [1961] | high | 2316 | 5 | 18 | 1300 | 7066 | 85.87% |
| Wiki-Vote | [1795] | high | 2317 | 44 | 0 | 1 | 7066 | 26.18% |

Reachability tính chính xác theo hướng cạnh, giữ node/edge gốc. CSV còn có
degree rank/ties, local clustering và expected first-layer size=p*d.
**P(No Intervention không lan khỏi seed)=(1−p)^d** vì processed graph đơn,
không self-loop, một source và các attempts tới distinct neighbors độc lập.
Đây là phân tích toán học, **không phải MC observation**, cũng không là công
thức no-growth của CIC khi có protector seeds.

Sáu scenarios bao phủ degree/first-step risk khác nhau trong high/constant
strata: đặc biệt Wiki1961 d5/no-growth85.87% so với Wiki1795 d44/26.18%.
Reachable cao không bảo đảm mean spread lớn. Hai email cùng reachable965
nhưng degree khác; Facebook cùng connected graph vẫn có source degree14/24.
Không phân loại main rumor mean/saturation khi chưa có outcomes. Giữ nguyên
Wiki1961 và mọi main outcome ít/không spread; không áp gate dựa trên GA score.

Coverage chỉ có hai fixed R/graph, p=.03/k5, không đại diện uniform toàn V,
không đo p/k sensitivity hoặc interactions. Medium strata của email/Wiki rỗng;
main holdouts chưa có low-reach sources. Giữ low/legacy R761/767,5288/6009/4341
trong supplementary manifest. Chúng đã dùng calibration, nên appendix phải
ghi exploratory/prior-data, không gán lại thành official main holdouts. Thêm
low-reach main scenarios mới cần revision/sampling/preflight riêng, không âm
thầm bổ sung hoặc loại R hiện có theo kết quả.

## 3. Ma trận phương pháp và chính sách seed

6 methods: No Intervention, Random, Degree, PageRank, Candidate-Restricted
Greedy, GA. **6R×5runs×6methods=180 primary rows**, thêm30 Full-Greedy rows
với status/reason riêng; matrix.csv tổng210rows. 30 scenario/repeat blocks,
mỗi block có **12 final calls** (6methods×2batches), trong đó control chỉ2
calls, không nhân control thêm một lần cho từng comparator.

Mọi method cùng R, budget k5 (NI có P rỗng là mốc), p, tie và final schedule
trong block. Degree/PageRank được chọn lại theo cùng deterministic rule ở mỗi
repeat để runtime selection nhất quán; P giống nhau không là nhiều independent
algorithm draws. Không cache fitness qua phương pháp hoặc runs. Restricted
Greedy là biến thể riêng, không đổi tên thành Full Greedy.

| Dataset | Full Greedy calls mỗi selection | CIC ở S_opt100 | Trạng thái |
|---|---:|---:|---|
| email-Eu-core | 5010 | 501000 | skipped: vượt calls100 và CIC2000 |
| ego-Facebook | 20180 | 2018000 | skipped: vượt calls100 và CIC2000 |
| Wiki-Vote | 35560 | 3556000 | skipped: vượt calls100 và CIC2000 |

Những bound Full vẫn được ghi dù bị skipped; budgeted work của skipped method
=0, không giả rumor mean=0. Eligibility 6methods không đồng nghĩa đã qua global
admission. Primary rows có status blocked_global_preflight khi vượt tổng
budget; tất cả execution_status=not_executed_design_only, P/quality/runtime=null.

Main master2026111109; giữ đúng60 seed slots đã reserve, dùng5slots đầu mỗiR,
5slots còn lại không tự kích hoạt. Index=scenario_index*100+repeat, ordinal
11..16; block width1.000.000 theo Cantor-pair helper cũ. GA input/operator và
Random Selection seeds có domain separation. GA và Greedy cùng fixed100 opt
seed labels trong block để so sánh công bằng; cache cục bộ. Final dùng nửa sau
block, batch b=final_base+b*S_eval; cùng lịch giữa tất cả methods, độc lập opt,
khác repeats/R và các namespace pilot/confirmation. Cùng seed không bảo đảm
common random edge outcomes khi valid attempts phụ thuộc P. Không đổi master,
R, N/G/rates hoặc S sau khi xem main outcomes.

## 4. Computational preflight — counts và runtime proxies

GA U=N+G(N−E)=100 evaluator calls/run trước cache. Restricted pool10,k5 cần
10+9+8+7+6=40calls/run. 30GA +30restricted selections; deterministic baselines
không gọi fitness MC. Final2batches được tính đủ cho mọi P.

| Phase | Calls upper | CIC upper |
|---|---:|---:|
| Optimization | 4200 | 420000 |
| Final của cả6methods, gồm control | 360 | 1320000 |
| Tổng | 4560 | 1740000 |

Giới hạn đề xuất giữ bảo thủ capGA120/CIC3.000.000/time10.800s/safety1.5 của
v1. **V1 ghi rõ cap đó cho sensitivity, chưa tự cấp ngân sách main**: main
allocation vẫn cần xác nhận; không tự nâng cap để admission pass.

Rates đo tại p=.03/k5 từ Pilot2, pilot-v1, Reduced V2 và Cross-Scenario,
tách method/optimization/final/non-MC. Lấy accuracy prefix2500, không coi các
nested prefixes nhỏ hơn là independent records. Có nhiều R/P/timings, nhưng
chưa có rate đo trên sáu mainR. Nearest topology proxy dùng khoảng cách
|log(1+d_main)−log(1+d_old)|+|reachable_fraction difference| để chọn reference
R cho **nominal heuristic**, chưa được chứng minh là mô hình runtime nhân quả.

Admission dùng **max observed rate trong toàn cohort cùng dataset/method/phase**,
không dùng best timing hoặc giả final rate của GA là rate của mọi baseline.
Proxy min/max và nearest reference R từng phase được lưu. Actual runtime/main-R
point estimate=null. Hai scenarios có thể chung conservative planning ceiling;
đó không phải khẳng định chúng tốn thời gian bằng nhau. Unknown variation trên
R/P/hardware mới được ghi rõ, factor1.5 không là bảo đảm hard bound.

| Dataset | R | Calls upper | CIC upper | Nearest proxy raw s | Observed-rate envelope raw s | Planning ceiling×1.5 s |
|---|---|---:|---:|---:|---|---:|
| Wiki-Vote | [1961] | 760 | 220000 | 709.57 | [605.17, 788.73] | 1183.10 |
| Wiki-Vote | [1795] | 760 | 220000 | 788.73 | [605.17, 788.73] | 1183.10 |
| ego-Facebook | [714] | 760 | 220000 | 2153.46 | [1863.70, 2265.11] | 3397.66 |
| ego-Facebook | [2733] | 760 | 220000 | 2153.46 | [1863.70, 2265.11] | 3397.66 |
| email-Eu-core | [485] | 760 | 430000 | 525.13 | [400.76, 525.13] | 787.70 |
| email-Eu-core | [374] | 760 | 430000 | 525.13 | [400.76, 525.13] | 787.70 |

| Dataset,2R×5runs | Calls upper | CIC upper | Planning ceiling s trước shared overhead |
|---|---:|---:|---:|
| Wiki-Vote | 1520 | 440000 | 2366.20 |
| ego-Facebook | 1520 | 440000 | 6795.32 |
| email-Eu-core | 1520 | 860000 | 1575.40 |

Sum max-rate proxy trước safety=7157.948s;
×1.5 +overhead300s = **11036.921s**.
Runtime headroom=-236.921s. Admission reasons:
**runtime_proxy_envelope_with_safety_and_overhead_exceeds_budget**. Đây là budget rejection
trước execution, không phải đã dùng hết3h hoặc algorithms bị lỗi.

Không thay repeats để vượt gate. Các phương án dưới là tính toán, **chưa chọn**:

| Repeats | Primary rows | Calls upper | CIC upper | Projected safety+overhead s | Admission | Quyền chạy |
|---|---:|---:|---:|---:|---|---|
| 3 | 108 | 2736 | 1044000 | 6742.15 | fit proxy budget | chưa chọn/cần xác nhận |
| 4 | 144 | 3648 | 1392000 | 8889.54 | fit proxy budget | chưa chọn/cần xác nhận |
| 5 | 180 | 4560 | 1740000 | 11036.92 | vượt budget | chưa chọn/cần xác nhận |
| 10 | 360 | 9120 | 3480000 | 21773.84 | vượt budget | chưa chọn/cần xác nhận |

Nếu giữ5repeats, cần xác nhận main time allocation ít nhất
11036.921s theo proxy này,
cộng thêm headroom phù hợp; con số đó không bảo đảm actual fit. Nếu không
tăng budget, chọn repeat count khác phải là quyết định revision được xác nhận,
giữ mọi R/method/S và đánh giá ảnh hưởng đến độ chính xác. Không tự dùng cache
hits dự kiến để biến counts upper thành actual thấp hơn nhằm qua admission.

## 5. RAM, timeout và checkpoint/resume dự kiến

Concurrency1; worker RSS cap2GiB, parent allowance512MiB. Historical graph+
deepcopy peak probes (không diffusion) cho memory proxy
2×max probe+256MiB=578.8MiB;
đây chưa là RAM main đo thực, PageRank/Greedy/P khác cần guard. Selection
timeout900s/method; final timeout120s/batch, luôn giới hạn theo remaining
active global budget. RSS watchdog ru_maxrss/heartbeat0.5s như confirmation;
không là instantaneous memory ceiling hoặc virtual-address-space limit.

Kế hoạch state machine: pending→selected→selection barrier→final_batch0/1→
complete→analyzed. Khóa toàn bộ P trong matrix trước any final outcomes.
Mỗi selection/batch publish JSON atomic+SHA256; GA lưu full parameters/seeds,
fitness/cache/calls/CIC/generation history. Lưu raw final counts/seed indices
cho paired covariance. Controls perblock/batch được gọi một lần, downstream
metrics reference control IDs thay vì rerun. Selection timing tách fitnessMC,
final timing tách control, loading/import/guard/export và total active ledger.

Resume phải match config/scenario/graph/core/P/seed fingerprints, không chạy
lại completed units, không reset active time/CIC budget. Unknown interrupted
work charge CIC upper +timeout, giữ failed attempt logs, không ghi unknown=0.
Không reselect P sau final outcome; retry cùng seed/params nếu được resource
gate cho phép. Không thay input để "cứu" phương pháp kém.

**Stage này chỉ xuất design, chưa triển khai execution adapter**. Existing
Milestone6 runner là one-batch; gọi hai lần để tạo B2 sẽ re-optimize hoặc đổi
context, không được xem là một run/P. Bounded V2 bridge chỉ hỗ trợ GA. Cần
adapter all-methods two-batch được kiểm thử lại trước main, dùng nguyên API
selection/evaluate_cic, không đổi semantics. CLI thiết kế không có --run.

## 6. Statistical analysis plan cố định trước kết quả

Primary per-scenario metric: pooled mean rumor count từ B2 batches **cho P
cố định của từng independent algorithm run**. Estimate μ_s,a=mean_r(μhat_s,a,r).
Report sampleSD giữa run means, conditional MC SD/SE/CI từngP/batch/pooled,
min/max/no-growth fraction và training−final gap riêng cho optimizer.
Training fitness không làm final quality; thế hệ và MC observations không
được đếm thành thêm independent GA runs.

Primary comparisons: GA−NI/Random/Degree/PageRank/Restricted trong mỗi6R,
30contrasts. Pair bằng cùngR/repeat/final seed schedule; δ_r=μhat_GA−μhat_cmp.
Pointwise descriptive CI95=t_(n−1,.975)*SD(δ_r)/sqrt(n) quanh meanδ. Dùng
**one predeclared family45 effects**:30scenario +15within-dataset contrasts
(3datasets×5comparators), Bonferroni approximate simultaneous95% t intervals
với quantile1−.05/(2×45), df=n−1. Multiplicity không tạo pooled global rank.
Không thêm baseline-vs-baseline hypothesis sau khi xem plots. Confidence
coverage xấp xỉ với n=5/rare cascades, không tuyên bố power đã đủ.

Trong mỗi dataset, hai fixed R có weight1/2. Với repeat r, bundle contrast=
(δ_s0,r+δ_s1,r)/2; CI qua5 independent bundles, conditional trên hai R đã
chọn, **không gọi đó là10 independent scenario draws**. Vẫn báo từng scenario,
range/direction consistency; không suy rộng CI thành population of all rumor
sources. Không gộp node counts/weighted winner giữa ba datasets; chỉ bảng
riêng, cùng cách phân tích. Như vậy heterogeneity không bị giấu bởi average.

Spread reduction s,a =1−μ_s,a/μ_s,NI (**ratio of across-run means**, không tự
đổi sang mean of ratios). Dataset summary là equal mean của hai scenario
reductions, tránh ngầm weight theo control spread. Report absolute reduction
và percent points. Paired **Fieller ratio CI mô tả** sử dụng covariance giữa
paired run means; nếu interval unbounded/disjoint/denominator uncertainty lớn,
báo nguyên dạng, không clip hoặc ép finite. Spread-ratio CIs không là extra
primary significance tests trong family45; winner statements chỉ dựa trên
primary rumor contrasts. Nếu cần inference riêng về ratio, xác nhận family
mở rộng trước main. NI≥1 vì |R|1, nhưng approximate denominator CI vẫn có thể
chạm0 trong low-spread/noisy cases; không thay R để né vấn đề đó.

Conditional MC SE của paired difference tính trên aligned individual CIC
counts (shared seed labels không đảm bảo edge coupling). Between-run variance
chứa selection randomness +MC noise. Giữ raw Var(run means)−mean(MC SE²), kể
cả âm, display nonnegative riêng; không suy "GA hoàn toàn ổn định" từ giá trị
âm. Deterministic NI/Degree/PageRank có cùngP, nên selection variability bằng0
theo cấu trúc; những final repeats chủ yếu đoMC, không phải stochastic algorithm
draws. Random/Greedy-MC/GA có selection variability. Bundle MC variance với
independent scenario seed blocks là sum(w_s²×conditional variance_s).

CI family chứa0: **chưa đủ bằng chứng khác biệt**, không equivalence. Mean
gần nhau hoặc rounding ties ghi unresolved/descriptive tie, không ép strict
ranking. Practical-equivalence margin hiện null, chưa có meaningful-effect
threshold; không tự đặt ngưỡng thuận lợi cho GA. Mean ordering/pointwise plots
chỉ mô tả, không là primary winner selection khi family CI chưa phân biệt.
Không optional stopping/repeats tăng giảm sau significance, không bỏ low/no-
spread scenarios, không retune GA theo bất kỳ main data nào.

## 7. Điều kiện chưa xác nhận, tests và provenance

| Điều kiện | Trạng thái | Yêu cầu |
|---|---|---|
| main_design_confirmation | pending | user confirms this concrete design before any execution |
| admission | blocked | ['runtime_proxy_envelope_with_safety_and_overhead_exceeds_budget'] |
| repeats | proposed_not_confirmed | five independent runs proposed; do not auto-reduce on budget failure |
| main_budget | conservative_proposal | v1 budget was sensitivity-specific; confirm dedicated main allocation rather than assume its availability |
| new_R_timing | unmeasured | proxy envelopes and nearest-topology heuristic are not a calibrated new-R runtime model; no official observations generated |
| coverage | limited | two fixed high/constant R per graph, no medium/low holdout; keep existing low/legacy appendix and all low-spread main outcomes |
| main_adapter | not_implemented_not_authorized_here | validate all-method selection barrier, two batches per locked P, paired raw export and checkpoint ledger; old one-batch runner cannot be invoked twice and called one run |
| equivalence_margin | unconfirmed | no equivalence/practical-effect claims without a prespecified margin |
| power | not_established | five proposed runs do not guarantee power; no adaptive stopping based on significance |
| new_R_spread | unobserved_by_design | do not reroll R, retune GA or filter official low/no-spread outcomes |

**461/461 tests pass**; 64 existing files giữ checksum, gồm 14 data files. Không thêm/xóa file dữ liệu.
Semantics IC/CIC/MC/GA/Greedy/baseline, raw/processed và các experiments cũ
giữ nguyên. Root .DS_Store/zip và các thay đổi đã có trong workspace được giữ.
Mọi cost là upper counts hoặc proxy có provenance, không có fake main results.

Artifacts ở [docs/main_experiments_protocol](docs/main_experiments_protocol):
matrix.csv/json, scenarios.csv/json, preflight.json, preflight_by_scenario/
dataset/method_scenario, runtime_rate_provenance.csv/json, source hashes,
repeat_alternatives_not_selected, memory_plan, analysis_policy và
unconfirmed_conditions.csv/json. Request:
[main_experiments_protocol.json](experiments/configs/main_experiments_protocol.json).

```sh
.venv/bin/python -B -m experiments.design_main_experiments --output-dir docs/main_design_repeat
.venv/bin/python -B -m unittest discover -s tests -q
```
Lệnh trên chỉ xuất planning artifacts vào folder mới. Exit0 chỉ có nghĩa
export thành công; summary.status/admission quyết định preflight, không phải
đã cấp quyền chạy. Main execution tiếp tục bị chặn tới khi cả budget/design/
adapter đều hợp lệ và được xác nhận.
