# Milestone 7 – Reduced GA Parameter Screening

**Trạng thái: STOPPED AT PREFLIGHT.** Ma trận 5 independent runs vượt giới hạn
projected runtime của Protocol v1. Theo điều kiện A của yêu cầu hiện tại, không
chạy bất kỳ subset, GA selection, control hoặc final evaluation nào của screen.
Không tăng ngân sách, giảm safety factor/repetitions, thay R hoặc thay levels
để làm ma trận vừa giới hạn. Đây chưa phải kết quả thực nghiệm Reduced Screen.

Artifacts: [docs/milestone_7_reduced_screen](docs/milestone_7_reduced_screen).
Request config: [milestone_7_reduced_screen.json](experiments/configs/milestone_7_reduced_screen.json).
Protocol gốc được đọc trực tiếp, kiểm tra checksum/frozen design và giữ nguyên:
[experiment_protocol_v1.json](experiments/configs/experiment_protocol_v1.json).
Quyền chạy có điều kiện đến từ yêu cầu mới; lý do dừng là **budget**, không
phải authorization flag lịch sử còn false trong file v1.

## 1. Xác nhận 9 cấu hình và Reduced subset

Các cột không liệt kê giữ nguyên: tournament=3, elite=1, cache=True.

| Profile ID | Population | Generations | Crossover | Mutation | Trong Reduced? |
|---|---:|---:|---:|---:|---|
| reference | 10 | 10 | 0.8 | 0.1 | Có |
| population_size_20 | 20 | 10 | 0.8 | 0.1 | Có |
| population_size_40 | 40 | 10 | 0.8 | 0.1 | Không |
| max_generations_20 | 10 | 20 | 0.8 | 0.1 | Có |
| max_generations_40 | 10 | 40 | 0.8 | 0.1 | Không |
| crossover_rate_0p6 | 10 | 10 | 0.6 | 0.1 | Có |
| crossover_rate_1 | 10 | 10 | 1.0 | 0.1 | Không |
| mutation_rate_0p05 | 10 | 10 | 0.8 | 0.05 | Không |
| mutation_rate_0p2 | 10 | 10 | 0.8 | 0.2 | Có |

9 profiles được xuất trực tiếp từ `reference_ga`/`factor_levels`; Reduced lấy
đúng 5 IDs trong `reduced_profiles`, không tự chọn theo quality. Reference
thuộc **cả bốn panel**. Full panels có 12 rows; Reduced có hai levels mỗi
panel, nhưng chỉ 5 physical profiles nhờ dùng chung baseline.

`OFAT_panel_membership.csv` chứng minh membership; `OFAT_comparisons.csv/json`
chứa 60 planned paired comparisons: 4 panels × 3 scenarios × 5 repetitions.
Mỗi comparison chỉ baseline-vs-one-factor, cùng scenario/repetition/seed labels;
không so trực tiếp N20 với G20 hoặc các cặp đổi nhiều biến.

## 2. 45 runs là tổng hay mỗi scenario?

- Protocol v1 ban đầu: **5 profiles × 3 scenarios × 3 repetitions =45 tổng**,
  tức **15 mỗi dataset/scenario**, không phải 45 cho mỗi dataset.
- Yêu cầu mới dùng 5 independent runs: **5×3×5=75 tổng**, tức **25 mỗi
  dataset/scenario**, 5 runs mỗi profile trong mỗi scenario.
- Không diễn giải 45 thành 9×5 rồi bỏ qua dataset/scenario. Chạy 9 profiles
  trên 3 scenarios với 5 repeats sẽ là 135 runs và không phải Reduced subset.

Giữ reference cùng R qua bốn panels nhưng chỉ có 15 planned physical baseline
runs (3×5), không đếm lại baseline thành 60 independent runs.

| Dataset | R cố định | k | p | S_opt | S_eval mỗi batch | Final batches | Planned GA runs |
|---|---|---:|---:|---:|---:|---:|---:|
| email-Eu-core | [926] | 5 | 0.03 | 100 | 6.000 | 2 | 25 |
| ego-Facebook | [1180] | 5 | 0.03 | 100 | 2.500 | 2 | 25 |
| Wiki-Vote | [1210] | 5 | 0.03 | 100 | 2.500 | 2 | 25 |

Tie rule=protector-priority. R/node IDs lấy từ frozen manifest, không dùng
range(n). Không thay R/p/S khi thấy GA chưa tốt hơn baseline. Các validation
R858/1555/2110 và low/legacy scenarios của Protocol v1 được giữ nguyên.

`run_matrix.csv/json` có **75 rows**, đầy đủ dataset/R/k/p/tie/S_opt/S_eval/B,
population/generations/crossover/mutation/tournament/elite/cache, repetition
index, GA input seed/actual operator seed, fitness interval và hai final bases.
Không có quality values vì chưa chạy. Mỗi planned run có JSON riêng ở `runs/`.

## 3. Computational preflight và điều kiện dừng

Dùng nguyên `design_budget`: tối đa 120 GA runs, 3.000.000 CIC và **10.800 s
projected runtime**, safety factor=1.5. Không đổi rate model đã dùng Protocol v1:
Pilot-2 worst measured GA fitness/final/control rates ở p=.03, tách non-MC
overhead. Projection không phải số đo Reduced Screen hoặc hard runtime bound.

Fitness calls upper của reference/N20/G20/crossover.6/mutation.2 lần lượt
100/210/190/100/100, tổng 700 mỗi scenario/repetition. Công thức
`U=N+G*(N-E)` trước cache; S_opt=100. Actual cache hits sau này chỉ có thể
giảm calls, không được giả định trước để vượt qua admission rule.

| Thành phần cho 75 runs | Evaluator calls | CIC simulations |
|---|---:|---:|
| Fitness, uncached upper | 10.500 | 1.050.000 |
| GA final, 75×2 batches | 150 | 550.000 |
| Shared control, 3×5×2 | 30 | 110.000 |
| **Tổng upper** | **10.680** | **1.710.000** |

Control dùng chung mỗi scenario/repetition/batch, không nhân lại theo 5
profiles. S_eval là mỗi batch, tổng final observations/P là 12.000 email và
5.000 Facebook/Wiki; không bỏ sót batch thứ hai trong chi phí.

| Dataset / p=.03 | Planned GA runs | Calls upper | CIC upper | Projected seconds gồm safety |
|---|---:|---:|---:|---:|
| email | 25 | 3.560 | 710.000 | 1.237,642 |
| Facebook | 25 | 3.560 | 500.000 | 7.341,443 |
| Wiki | 25 | 3.560 | 500.000 | 2.406,079 |
| **Tổng** | **75** | **10.680** | **1.710.000** | **10.985,164** |

Run count và simulations fit budget. Tuy nhiên **10.985,164 >10.800 s**, vượt
**185,164 s (1,71%)**. Không làm tròn 3,051 giờ thành 3 giờ để cho qua.
Projection chưa safety=7.323,443 s; không tự bỏ factor1.5 đã chốt. Exclusions
loading/export/setup cũng không được coi là chi phí âm để giảm projection.

**Quyết định:** dừng toàn bộ ma trận tại preflight. Không chạy riêng dataset
rẻ hơn hoặc tự dùng lại 3 repeats. 75 planned runs đều có status
`skipped_global_preflight`, reason=`Pilot2_rate_projection_exceeds_budget`.
Đây là admission failure trước execution, không phải đã chạy hết 3 giờ hay
GA bị lỗi/timeout. Không có measured optimizer runtime cho Reduced Screen.

## 4. Seed protection và OFAT fairness

Không sửa master seed của bản Protocol v1 đã đóng băng. Derived screen request
ghi override master **2026111108**, khác pilot v1=2026111107; namespace main
dự kiến được reserve **2026111109**, chưa cấp quyền main execution.

Giữ width=1.000.000, scenario ordinal theo full manifest và index
`scenario_index*100+repetition`. Mỗi scenario/repetition có block riêng; cùng
block giữa profiles để paired comparisons. Fitness dùng nửa đầu; final batch0/
1 dùng nửa sau nối tiếp theo S_eval. Các intervals optimization/final độc lập;
screen/main master khác nhau cho blocks tách biệt với cùng width.

Seed labels chung không bảo đảm identical operator consumption khi N/G thay
đổi hoặc common edge outcomes trong CIC. Fitness cache vẫn cục bộ mỗi GA call,
không chia sẻ giữa profiles. `validate_ofat_pair()` từ chối cặp khác R/k/p/tie/
S/rep/seed labels, hoặc khác quá một GA factor. Không có so sánh thực nghiệm
nào được thực hiện khi preflight không đạt.

Không tái dùng 8 pilot runs cũ như các repetitions của screen. Không dùng dữ
liệu screen để làm main evidence; main seeds và algorithm-outcome-validation
scenarios vẫn được reserve trong `main_evaluation_reservation.json`.

## 5. Trạng thái đầu ra và phân tích

| Output | Trạng thái |
|---|---|
| 9 unique configurations và membership bốn panels | Đã xuất, kiểm tra |
| 75-row run matrix và 60 planned OFAT pairs | Đã xuất, kiểm tra |
| Per-run JSON + `run_results.csv/json` | 75 explicit skipped rows |
| `summary_by_configuration.csv/json` | 15 groups, completed runs=0, quality fields=null |
| Mean/std/CI, MC-versus-GA variance, quality–cost effects | Chưa ước lượng vì không có completed screen runs |
| Bốn nhóm parameter-effect plots | Không tạo; lý do trong `figure_status.csv/json` |
| Reference convergence / quality–cost plots | Không tạo vì chưa có screen observations |

Không gán zero cho rumor mean, fitness, CI, cache hits hoặc runtime chưa đo;
JSON để `null`, CSV để trống. Actual screen evaluator calls/CIC=0 là số đếm
thực tế vì executor không được gọi. Unit-test simulations không nằm trong
screen counters. Không dựng placeholder plots như thể có experimental data,
không lấy lại pilot convergence dưới tên Reduced Screen.

Khi budget được xác nhận trong bước tiếp theo: đơn vị phân tích parameter
effect là **independent GA run**, paired theo repetition trong mỗi scenario.
MC observations/B=2 chỉ xác định conditional uncertainty của P. Báo mean và
dispersion qua GA runs, MC SE riêng, fitness-validation gaps, actual calls/
CIC/cache/runtime. Dùng independent final result, không training fitness.
Không ép strict ranking khi CI còn chứa 0; practical-equivalence margin và
multiplicity policy của Protocol v1 vẫn cần chốt. Không chọn theo một R/run.

## 6. Cấu hình GA đề xuất và phương án tiếp theo

**Không có screen evidence mới để chọn GA configuration.** Giữ reference
N10/G10/crossover.8/mutation.1/tournament3/elite1/cache=True để tái lập; đây
không phải xác nhận tối ưu hoặc vượt trội. Các khoảng bất định của pilot v1
không được coi là bằng chứng hoàn tất Reduced Screen.

Các phương án sau chỉ là **đề xuất, chưa chọn/chưa chạy**:

| Phương án | GA runs | Calls upper | CIC upper | Projected seconds | Thay đổi cần xác nhận |
|---|---:|---:|---:|---:|---|
| Đúng 5 repeats/levels v1 hiện tại | 75 | 10.680 | 1.710.000 | 10.985,164 | Time budget ít nhất 10.986 s theo mô hình hiện tại |
| Quay về 3 repeats v1 gốc | 45 | 6.408 | 1.026.000 | 6.591,098 | Không đáp ứng yêu cầu 5 repeats mới nếu chưa được đồng ý |
| 5 repeats, N15/G15 thay N20/G20 | 75 | 9.180 | 1.560.000 | 9.936,198 | Levels mới không thuộc Reduced v1; cần protocol revision |

Phương án N15/G15 vẫn đổi một tham số mỗi panel nhưng khoảng thay đổi nhỏ
hơn; không có bảo đảm power hoặc quality. Không chọn nó chỉ để tuyên bố đã
chạy đúng v1. Mức 10.986 s chỉ là threshold dự tính tối thiểu, không bảo đảm
actual runtime nằm trong đó; không tự nâng ngân sách hiện tại.

## 7. Tests, checksum và giới hạn

**389/389 tests pass** (379 cũ +10 mới), gồm count45/75, 9/5 profiles, reference
membership, budget stop, 60 OFAT pair guards, exact work counts, seed
separation, per-run null metrics và không gọi simulator khi export preflight.

Kiểm tra SHA-256 sau tests: **44 existing protected files**, gồm **14 data
files**, Protocol-v1 JSON, requirements/main và source cores đều không đổi.
Không thêm/xóa data files; topology ba processed graphs giữ nguyên. Semantics
IC/CIC/MC/GA/Greedy/runner không đổi. Earlier Pilot-2/v1 evidence giữ nguyên.

Code mới chỉ phục vụ request/preflight export:
`experiments/preflight_reduced_screen.py`, request JSON và
`tests/test_reduced_screen_preflight.py`. Chưa triển khai/run Full Design270
hoặc main experiments. Không cần dùng đủ ngân sách để vẫn tuân điều kiện
stop-at-preflight của người dùng.

```sh
.venv/bin/python -B -m experiments.preflight_reduced_screen --output-dir docs/reduced_screen_preflight_repeat
.venv/bin/python -B -m unittest discover -s tests
```

CLI chỉ xuất planning artifacts, không có execution path. Summary/status là
nguồn machine-readable để nhận biết `stopped_at_preflight`; exit success chỉ
nghĩa là export thành công, không phải screen đã chạy.
