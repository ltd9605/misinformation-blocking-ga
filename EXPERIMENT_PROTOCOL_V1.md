# Experimental Protocol v1 và thiết kế Milestone 7

**Trạng thái:** cố định cấu hình tham chiếu v1 để tái lập và đối chiếu mục 3.3/
3.5. Đây không phải tuyên bố tham số tối ưu hoặc cho phép tự chạy main/full
sweep. Chỉ pilot nhỏ được phép thực thi trong giai đoạn này. Mỗi giá trị có
evidence scope; lựa chọn nghiên cứu chưa đủ xác nhận vẫn được liệt kê riêng.

Specification JSON: [experiment_protocol_v1.json](experiments/configs/experiment_protocol_v1.json).
Bảng/ma trận/preflight: [docs/experiment_protocol_v1](docs/experiment_protocol_v1).
JSON này là protocol specification cho design/pilot wrapper, không phải schema
một-batch của `load_experiment_config()`. Các API GA/evaluator cũ không đổi.

## 1. Bảng tham chiếu cho mục 3.3

| Thành phần | Reference v1 | Evidence / giới hạn |
|---|---|---|
| Datasets | email-Eu-core, ego-Facebook, Wiki-Vote processed | Topology và checksums Milestone 1 giữ nguyên |
| Model / tie | CIC, protector-priority | Semantics đã kiểm chứng; không thay biến thể |
| Rumor count / budget | 1 node/scenario / k=5 | Đã chạy trong Pilot 2 |
| Probability | **p=0.03** reference candidate | Chọn bằng No Intervention trước optimizer; chưa gọi là p tối ưu |
| Fitness MC | **S_opt=100** | Có dữ liệu cả ba; sampling noise/gap, nhất là Wiki, chưa được xem là giải quyết |
| Final MC email | **S_eval=6.000 mỗi batch** | Ngoại suy từ Pilot 2, trước bounded pilot v1 chưa đo tại 6.000 |
| Final MC Facebook/Wiki | **S_eval=2.500 mỗi batch** | Pilot 2 đã đo hai batches trên fixed P của một R mỗi dataset |
| Final batches | **2 độc lập mỗi P** | Mỗi P có tổng 12.000 email / 5.000 Facebook/Wiki observations |
| GA reference | N10, G10, crossover=.8, mutation=.1, tournament3, elite1, cache=True | Cấu hình khả thi đã đo, không là hyperparameters tối ưu |
| Full design independent GA runs | 10/scenario/config | Lựa chọn thiết kế; chưa có power analysis hoặc full execution |
| Reduced screen independent runs | 3/scenario/config | Screening ít mẫu, không đủ kết luận ổn định mạnh |
| Pilot independent runs | 2/scenario/config | Chỉ kiểm tra hệ thống, chi phí và logging |
| Restricted Greedy | Top 10 out-degree trên DiGraph / degree trên Graph, ngoài R | Tie ascending actual integer ID; không đổi graph |
| Full Greedy | Tối đa 100 evaluator calls và 2.000 CIC | Vượt limit thì explicit skipped; không gán kết quả Restricted cho Full |

`reference_configuration.csv/json` chứa bản số liệu theo dataset. S_eval luôn
nghĩa là **mỗi batch**; mean/std/CI pooled phải đi kèm `total_final_simulations`
và B=2. Không trình bày CI của 12.000 observations như CI của một batch 6.000.
Lưu cả từng batch và pooled statistics để so sánh với Pilot 2.

## 2. Rumor policy, reachability và scenarios cố định

Kế thừa manifest Pilot 2 có checksum, không lấy mẫu lại theo quality. Pilot 2
lấy mẫu đều actual IDs trong strata theo relative reachable maximum: low≤max/3,
medium≤2max/3, high phần còn lại; ties không bị chia nhóm giả. Mọi node nguồn
đều được tính reachability theo hướng cạnh, gồm source. Facebook homogeneous
được ghi `constant`, không ép thành ba nhóm.

| Dataset | Development R cho sensitivity | Algorithm-outcome validation R | Supplemental |
|---|---|---|---|
| email-Eu-core | [926], reachable=965 (`high`) | [858], reachable=966 (`high`) | [761], [767], reachable=1 |
| ego-Facebook | [1180], reachable=4.039 (`constant`) | [1555], reachable=4.039 (`constant`) | Không có low/medium thật |
| Wiki-Vote | [1210], reachable=2.317 (`high` tương đối) | [2110], reachable=2.317 | [5288], [6009], reachable=1; legacy [4341], reachable=2 |

Medium strata của email/Wiki rỗng; không tạo dữ liệu hoặc rumor group để lấp
khoảng trống. Max reachable của Wiki chỉ 2.320/7.115, nên high không có nghĩa
là toàn graph. Low/legacy luôn giữ làm phân tích bổ sung, không âm thầm loại.

Development scenarios đã được hiệu chỉnh thuật toán/MC trong Pilot 2.
Validation scenarios đã có No Intervention scan nên không mù về topology/
spread, nhưng **chưa dùng GA outcomes để chọn hyperparameters**. Giữ chúng
ngoài sensitivity development và bounded pilot v1. Sau khi cố định một lựa
chọn trên development, kiểm tra validation trong một bước được xác nhận riêng;
không quay lại chọn lại cấu hình theo validation score.

Mọi cấu hình được so sánh dùng cùng danh sách development R; không chọn cấu
hình chỉ vì tốt trên một R. Phân tích riêng dataset/scenario, effect direction
và cost. Nếu cần tổng hợp, công bố normalized metric và trọng số cố định;
không gộp raw node counts giữa các graph hoặc coi stratified sample là uniform
node population. Chưa có practical-equivalence margin để tuyên bố tương đương.

## 3. Random seeds và final evaluation thống nhất

Giữ R explicit trong manifest. Master seed v1=2026111107, khác các pilot cũ;
seed block width=1.000.000. Scenario ordinal cố định theo toàn manifest 11
scenarios, không đánh số lại sau khi lọc pilot. `index=scenario_index*100+run`;
run phải <100. Dùng `make_experiment_seed_plan()` đã kiểm chứng:

- Nửa đầu block dành cho optimization, simulation i dùng opt_base+i.
- GA operators dùng domain-separated GA input seed; GA tiếp tục suy ra local
  operators RNG theo API cũ. Cache chỉ sống trong từng GA call/context.
- Nửa sau dành cho final. Batch b dùng `final_base+b*S_eval`, đủ chỗ cho B=2,
  không giao fitness hoặc block của scenario/run khác.
- Cùng scenario/run chia sẻ seed labels giữa cấu hình; final seeds chia sẻ
  thêm theo batch. Đây là paired design, không phải bảo đảm identical RNG
  consumption khi N/G/rates khác hoặc common edge outcomes trong CIC.
- Giữa independent GA runs và giữa final batches dùng block/interval độc lập.
  Không chia sẻ fitness cache giữa profiles hoặc runs.

Chốt toàn bộ P trong bounded pilot trước khi lộ final/control results. Mỗi
evaluation gọi trực tiếp `evaluate_cic()` cũ. Control P rỗng chỉ tính một lần
cho scenario/run/batch rồi dùng chung giữa profiles; lặp lại control hoặc
baseline trong nhiều panel không tạo thêm independent evidence.

Final result gồm independent mean/population std/sample SE/pointwise 95% t CI,
R/P, spread-reduction point estimate, từng batch và pooled records. CI là
approximation có điều kiện trên P; không là CI đồng thời cho mọi comparisons.
Không dùng training fitness làm kết quả cuối. GA API có suggested held-out
seed nhưng wrapper dùng final half-block v1, ghi rõ metadata.

## 4. Kế hoạch OFAT cho mục 3.5

Thứ tự khảo sát **population → generations → crossover → mutation**. Mỗi panel
chỉ đổi một tham số so với **cùng reference ban đầu**, không tự cập nhật “best”
từ panel trước để đổi baseline panel sau. k/R/p/S_opt/S_eval/tie/run labels và
các tham số GA còn lại giữ nguyên.

| Panel | Levels đề xuất | Reference | Cận fitness calls mỗi GA run |
|---|---|---|---|
| 1 Population | 10, 20, 40 | 10 | 100, 210, 430 |
| 2 Generations | 10, 20, 40 | 10 | 100, 190, 370 |
| 3 Crossover | 0.6, 0.8, 1.0 | 0.8 | 100 ở mọi level |
| 4 Mutation | 0.05, 0.1, 0.2 | 0.1 | 100 ở mọi level |

Có **12 panel rows nhưng chỉ 9 unique configurations**, do reference dùng
chung. Mỗi scenario/run chỉ chạy physical baseline một lần, tái sử dụng cho
bốn panel, không gọi đó là bốn GA runs độc lập. `parameter_matrix.csv` và
`unique_configurations.json/csv` lưu mapping rõ ràng.

Cận calls `U=N+G*(N-E)` trước cache; fitness CIC=U*S_opt. N/G tăng làm tăng cả
search effort và evaluation budget, nên phải báo quality–cost curves/evaluator
calls, không diễn giải khác biệt như so sánh cùng compute. OFAT không đo
interactions; ghép các levels có vẻ tốt riêng lẻ không chứng minh kết hợp tốt.

Mỗi run lưu config/R/P/seeds, G+1 convergence rows (generation 0 riêng), best/
mean training fitness, actual fitness calls/CIC, cache hits/elite carries,
independent final batches/pooled mean/std/SE/CI, runtime loading/selection/
evaluation/export/total và environment/Git/source hashes. Không automatic
winner selection trong code hoặc pilot.

## 5. Computational preflight và ma trận nhỏ hơn

Preflight được xuất trước execution. Calls optimization là uncached upper
bound, final/control là số calls theo protocol; runtime là **ngoại suy**, không
là thời gian đã chạy hay hard upper bound. Mô hình dùng worst observed Pilot-2
GA fitness/final/control s/CIC tại p=.03/S_opt100, tách non-MC overhead, scale
history theo N*(G+1), safety factor=1,5. Evidence chỉ có một R mỗi dataset;
new genotype/levels/R/hardware load có thể thay đổi tốc độ.

Ngân sách thiết kế: tối đa 120 GA runs, 3.000.000 CIC, 10.800 s projected
(3 giờ). Việc fit ngân sách **không tự cấp quyền** chạy screen/sweep.
Đây là ngân sách sensitivity GA + No Intervention; một comparative main run
với các baseline khác cần preflight riêng, không coi chúng đã được tính vào đây.

| Scope | Unique configs × scenarios × repeats | GA runs | Max evaluator calls, gồm final/control | Max CIC | Runtime ngoại suy | Trạng thái |
|---|---|---:|---:|---:|---|---|
| Full design | 9 × 3 × 10 | 270 | 51.600 | 7.300.000 | 48.166,9 s ≈13,38 h | Vượt cả ba giới hạn; không chạy |
| Reduced screen | 5 × 3 × 3 | 45 | 6.408 | 1.026.000 | 6.591,1 s ≈1,83 h | Fit design budget; **chưa được phép chạy** |
| Bounded pilot v1 | 2 × 2 × 2 | 8 | 1.264 | 226.000 | 654,0 s ≈10,90 min | Được phép nếu guard trước execution còn đạt |

Reduced screen dùng reference + N20 + G20 + crossover0.6 + mutation0.2. Nó
giữ cả bốn factors, hai levels/panel và ba development scenarios, nhưng chỉ
cho screening direction; không đủ mô tả curvature/non-monotonicity/optimal
level. Ba runs vẫn có khoảng bất định lớn. Bảng số config/scenario/calls và
runtime từng profile nằm trong `preflight_full_design.*`, `preflight_reduced_screen.*`.

Full tối đa 51.000 fitness calls + 540 final calls + 60 shared-control calls.
Reduced tối đa 6.300 + 90 + 18 calls. Pilot tối đa 1.240 + 16 + 8 calls. Hai
final batches đã được nhân vào số simulations; không bỏ sót chi phí control.

Full Greedy với k5/S_opt100 cần email 5.010 calls/501.000 CIC; Facebook
20.180/2.018.000; Wiki 35.560/3.556.000. Cả ba skipped theo limits riêng, không
phải zero-spread results. Restricted pool=10 cần đúng 40 calls/4.000 CIC khi
được chạy; sensitivity pilot chỉ chạy GA/control, không rerun baseline matrix.

## 6. Bounded pilot v1 được thiết kế trước execution

Pilot chỉ so reference và N20, G/rates/tournament/elitism/S/R/p giữ nguyên.
Scenarios: email R926 và Wiki R1210, 2 independent GA runs mỗi profile/scenario.
Chọn trước theo scope/cost, không chọn theo GA outcomes; validation Rs và
Facebook nằm ngoài pilot. Đây không phải chạy full/reduced sweep.

Hard pilot caps: 8 GA runs, 300.000 CIC, 900 s tổng, 150 s mỗi selection.
Worker selection có timeout; all P trước all final evaluation; profile order
counterbalanced theo run parity, seeds không phụ thuộc execution order. Giữ
S_eval reference, không âm thầm giảm S để vừa ngân sách. Nếu guard không đạt,
ghi skipped/failed/timed_out và không tạo số đo chất lượng giả.

**Tại thời điểm xuất thiết kế:** 8 runs chưa được thực thi, nên 654 s chỉ là
projection. Kết quả thực tế sau execution sẽ ghi riêng ở
`docs/experiment_protocol_v1/pilot/` và phần bổ sung cuối tài liệu; không sửa
preflight thành số đo đã biết trước.

## 7. Phân biệt MC noise và GA-run variability

Mỗi P cố định có B=2 final batches: đo MC SE/CI/no-spread, disagreement giữa
batches. Sau đó lấy **một pooled final estimate mỗi independent GA run** để
phân tích biến động GA. Không dùng 12.000 MC observations như 12.000 GA runs.

Lưu mô tả variance: variance giữa các final means chứa GA randomness và MC;
mean squared conditional MC SE; phần chênh variance. Nếu chênh âm, giữ raw
negative value và ghi riêng zero-clipped display, không che thành bằng chứng
GA ổn định tuyệt đối. Với chỉ hai pilot runs, decomposition/CI giữa runs rất
không chắc chắn; không là power/coverage analysis.

Comparisons cấu hình dùng paired run labels trong từng scenario; main effect
unit là GA run. Confidence intervals trên MC chỉ mô tả uncertainty của P
đã chọn. Không suy ra sensitivity mạnh chỉ từ training convergence hoặc chỉ
một R. Báo effect direction/CI từng scenario; không tự chọn profile từ một
pooled raw-count average. Cặp chưa phân biệt được giữ uncertain; overlap
không chứng minh equivalence, không-overlap không tự xác nhận global ranking.

## 8. Điều kiện còn chưa xác nhận

Danh sách machine-readable: `unconfirmed_conditions.csv/json`.

1. S_opt100 còn fitness-selection bias/gap; nhất là Wiki. S_opt250 chưa đo
   trên Facebook/Wiki trong Pilot 2; không gọi mức reference là tối ưu.
2. Email S_eval6000 trước pilot v1 là extrapolation; pilot mới chỉ kiểm tra
   một số P/R/levels, không bảo đảm mọi genotype hoặc R validation.
3. R validation chỉ có control scan; giữ chúng ngoài tuning. p=.05/.10 không
   thuộc reference sensitivity v1 và cần calibration riêng nếu thêm vào main.
4. Factor levels và 10/3/2 repeats là choices của thiết kế, chưa được chứng
   minh tối ưu/powered; OFAT chưa giải quyết interactions hoặc global optimum.
5. Practical equivalence margin chưa chốt; multiplicity/CI family policy cần
   xác nhận trước inferential study. Pilot chỉ exploratory pointwise intervals.
6. Rates/cost projections không bảo đảm cho N/G/R khác; full sweep/main luôn
   disabled. Reduced screen fit budget vẫn cần user authorization riêng.
7. Không đổi cấu hình tham chiếu sau khi xem pilot score thuận lợi. Thay đổi
   nghiên cứu sau này cần protocol version mới và ghi lý do.

## 9. Mapping với mục 3.3 và 3.5

**Mục 3.3:** bảng reference/scenario roles, graph checksums, CIC timing/tie rule,
S_opt và S_eval-per-batch/B, independent GA runs, seed policy, Full/Restricted
rules và budget. Dẫn evidence tags để phân biệt measured/reference/extrapolated.

**Mục 3.5:** bốn panels OFAT theo thứ tự, shared baseline, convergence G+1,
training–validation gap, independent final mean/std/CI, cache/evaluator work,
quality–cost curves và paired effects across GA runs/scenarios. Không lấy
training fitness làm quality cuối, không kết luận winner khi uncertainty lớn.

Design có thể tái tạo bằng `python -B -m experiments.design_protocol_v1` với
output directory mới. Không có dispatcher cho phép tự chạy full/reduced matrix.
Các thay đổi trước Pilot v1 trong working tree được giữ nguyên.

## 10. Bounded pilot v1 — số liệu thực đo sau khi xuất thiết kế

**8/8 GA runs thành công**, không skipped/failed/timeout. Chỉ N10 và N20 được
thực thi; generations/crossover/mutation panels vẫn là thiết kế, chưa chạy
screen hoặc sweep. Đúng hai development R926/R1210; không dùng validation R.

| R / profile | GA run | Training fitness | Independent pooled mean | Conditional MC 95% CI | Fitness calls / cache hits |
|---|---:|---:|---:|---|---|
| email926 / N10 | 0 | 2,55 | 6,3869 | [5,9702; 6,8037] | 27 / 73 |
| email926 / N10 | 1 | 1,49 | 7,6035 | [7,0903; 8,1167] | 39 / 61 |
| email926 / N20 | 0 | 2,20 | 8,1198 | [7,5796; 8,6599] | 108 / 102 |
| email926 / N20 | 1 | 2,84 | 4,6987 | [4,3740; 5,0234] | 102 / 108 |
| Wiki1210 / N10 | 0 | 184,54 | 196,9156 | [191,7029; 202,1283] | 39 / 61 |
| Wiki1210 / N10 | 1 | 124,78 | 161,5484 | [156,9296; 166,1672] | 29 / 71 |
| Wiki1210 / N20 | 0 | 140,08 | 161,6924 | [157,0774; 166,3074] | 100 / 110 |
| Wiki1210 / N20 | 1 | 73,35 | 118,0180 | [114,3256; 121,7104] | 78 / 132 |

Pooled means ở email dùng **2×6.000=12.000**, Wiki **2×2.500=5.000** final
observations mỗi P. Các CI trong bảng là conditional MC intervals của một P,
không phải CI của GA parameter effect. Từng batch vẫn được lưu độc lập.

Chi phí thực tế: **522 fitness calls ×100 = 52.200 CIC**, **16 GA final calls
=68.000 CIC**, **8 shared-control calls =34.000 CIC**. Tổng **546 evaluator
calls, 154.200 CIC**, thấp hơn cận 1.264 calls/226.000 CIC. 718 cache hits
không được đếm thành calls mới; lưu 88 convergence rows (8×11 generations).

Thực đo wall=**280,701 s** (4,68 phút), gồm workers/imports/loading/control/
final/logging/exports đến trước summary cuối. Selection cộng=109,324 s, trong
đó fitness MC=107,591 s; final GA MC=128,965 s; shared-control MC=35,337 s;
phần còn lại khoảng 7,075 s. Không cộng fitness MC một lần nữa vào selection.
Projection 654,0 s trước khi chạy được giữ nguyên, không sửa thành số đo mới.

S_eval6000 email **nay đã được thực thi** trên bốn P (N10/N20 × hai runs) của
R926/p=.03, hai batches mỗi P. Điều này xác nhận khả năng thực thi và logging
ở scope này, không chứng minh đủ độ chính xác cho mọi P/R hoặc là S tối ưu.
Max conditional batch CI half-width/mean khoảng **10,08%**; không tuyên bố
mọi batch đã đạt target đề xuất 10% chỉ vì S tăng lên 6.000.
Evidence bổ sung nằm ở `evidence_after_pilot.csv/json`, không ghi đè evidence
snapshot hay preflight đã xuất trước execution.

Tách variation ở Wiki/N10: variance giữa hai pooled run means≈625,419,
mean conditional MC variance≈6,310. Đây chỉ là variance-component description
với hai runs, không là một ước lượng ổn định về GA population performance.

CI parameter effect dùng **hai paired GA-run differences** N10−N20:

| Scenario | Mean difference | Approximate 95% CI qua GA runs |
|---|---:|---|
| email R926 | 0,5860 | [−28,8776; 30,0496] |
| Wiki R1210 | 39,3768 | [−13,3997; 92,1533] |

Cả hai chứa 0. Không kết luận N20 tốt hơn, không chọn winner từ pilot, không
coi các conditional MC intervals hẹp là thay thế cho independent GA runs.
Training–final gaps vẫn tồn tại. Reference v1 giữ nguyên sau khi xem pilot.

**379/379 tests pass** (361 trước đó +18 mới), bao gồm OFAT-only changes,
baseline dedup/work counts, Full limits, seed separation, scope guards,
MC-versus-GA units và worker bridge trên processed fixture tạm. Audit kiểm
tra 1.320 population individuals, 88 convergence rows, 102.000 final/control
observations, counters và CI tính lại từ raw. Toàn bộ **42 existing code/data
files và 14 data files** không đổi checksum; 55 Pilot-2 evidence files giữ
nguyên. Không sửa dependencies hoặc semantics IC/CIC/MC/GA/Greedy/runner.

Artifacts pilot compact: [docs/experiment_protocol_v1/pilot](docs/experiment_protocol_v1/pilot).
Raw và complete per-run selection payloads:
`results/milestone_7_pilot_v1/`. Tái chạy dùng output root mới:

```sh
python -B -m experiments.pilot_milestone_7 --output-dir results/milestone_7_pilot_v1_repeat
python -B -m unittest discover -s tests
```

Full design, reduced screen và main experiments vẫn **chưa thực thi**. Cấu
hình ở mục 1 và ma trận ở mục 4 là các cấu hình để đối chiếu 3.3/3.5; mọi
quality claim hoặc bước thực nghiệm tiếp theo phải giữ đúng evidence scope.
