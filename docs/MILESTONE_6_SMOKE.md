# Milestone 6 – Experiment Runner: kiểm chứng triển khai

Chỉ smoke tests/pilot nhẹ, không phải kết quả Chương 3 hoặc bằng chứng xếp hạng
chất lượng thuật toán. Các giá trị dưới đây được đo thực tế trên môi trường
hiện tại; S_opt/S_eval/N/G trong file smoke chưa được chốt cho nghiên cứu.

## API và kiến trúc

```python
from src.experiments import load_experiment_config, run_experiment

config = load_experiment_config("experiments/configs/runner_smoke_email.json")
result = run_experiment(config)
# result.output_directory, .rows, .summary, .metadata
```

`ExperimentConfig.from_dict()` nhận cấu hình trong Python. Runner JSON không
thêm thư viện, không sửa evaluator/simulator/algorithms cũ.

| Thành phần | Trách nhiệm |
|---|---|
| `src/experiments/config.py` | Validate/normalize JSON, explicit parameters và output identity |
| `seeds.py` | Seed plan có version, optimization/final blocks tách nhau |
| `metrics.py` | Final means, population/sample std, SE, reduction |
| `metadata.py` | Python/libraries/OS/hardware/Git/source provenance |
| `runner.py` | Load, preflight, dispatch bảy phương pháp, final evaluation, atomic export |
| `experiments/run_experiment.py`, `main.py` | CLI một independent run index |

Config dùng `algorithm` hoặc `algorithms`; luôn thêm No Intervention. Mọi P
được chốt trước khi đánh giá final/control. Config đầy đủ và hướng dẫn schemas,
seed formula, null metrics, cost limits và output có trong README.

## Kiểm thử

```sh
.venv/bin/python -B -m unittest discover -s tests
```

**317/317 tests pass**: 260 tests cũ và 57 tests mới. Tests mới bao gồm strict
config/research parameters, seed blocks, metrics, đủ bảy phương pháp trên
processed fixtures, input errors/limits trước selection, cùng R/k/p/tie/final
seed schedule, final độc lập sau selection, replay và đảo thứ tự phương pháp,
k=0, graph directed/undirected và sparse IDs, graph/processed bytes bất biến,
CSV/JSON/convergence/raw export, atomic failure/no overwrite, CLI từ thư mục khác
với đường dẫn Unicode/khoảng trắng. Test đọc raw observations để tính lại
mean/std trong results.

Graph kiểm chứng bằng tay: directed edges `10→20→30→50`, `40→30`, node 90 cô
lập, R={10}, k=1, p=1, protector-priority. Control có 4 rumor nodes. Degree,
Full Greedy và Candidate-Restricted (degree top 3) chọn P={20}: rumor_count=1,
protector_count=3, inactive_count=2, reduction=75%, std=SE=0. Đổi sang undirected
thì control có 5 rumor nodes. p=0 giữ rumor_count=1 cho mọi phương pháp.

Full Greedy m=5, k=2, S_opt=2 có đúng 9 evaluator calls/18 CIC simulations;
chi phí được kiểm tra độc lập với runtime. Tests kiểm tra giới hạn calls và
simulations riêng, không có fallback ngầm sang Candidate-Restricted.

## Pilot email-Eu-core

Cấu hình: [runner_smoke_email.json](../experiments/configs/runner_smoke_email.json).

- Graph processed: 1.005 nodes, 24.929 directed edges, 19 isolated nodes.
- R=[0], k=2, p=0.05, protector-priority, S_opt=3, S_eval=20.
- Master seed=2026, independent_run_index=0, block width=1.000.000.
- GA: N=4, G=2, crossover=0.8, mutation=0.3, tournament=2, elite=1, cache=True.
- Candidate-Restricted pool: 5 nodes theo out-degree; chọn P gồm 2 nodes.
- PageRank: alpha=0.85, tol=1e-12, max_iter=1000.
- Giới hạn mỗi optimizer: 50 evaluator calls/500 CIC simulations.
- Full Greedy không thuộc pilot; explicit Full limits=0. Full được kiểm thử
  đầy đủ trên graph nhỏ. Nếu thêm Full vào config email này thì preflight chặn
  2.007 calls/6.021 CIC simulations trước khi bất kỳ phương pháp nào chạy.

Lệnh đã chạy:

```sh
.venv/bin/python -B main.py experiment --config experiments/configs/runner_smoke_email.json
.venv/bin/python -B -m experiments.run_experiment --config experiments/configs/runner_smoke_email.json --output-dir results/experiment_runner_smoke_replay
```

Kết quả gốc:
`results/experiment_runner_smoke/email-Eu-core/run_0000_f612221a6a70/`.
Replay nằm ở output root `results/experiment_runner_smoke_replay/` với cùng
dataset/run basename. Thư mục results được gitignore; file config và báo cáo
này giữ trong repository. Chạy lại cần output root khác vì runner từ chối ghi đè.

Seed optimization thực dùng: 2.053.351.000.000 tới 2.053.351.000.002.
Seed final thực dùng: 2.053.351.500.000 tới 2.053.351.500.019.
Random Selection seed=4276356825679270820; GA input seed=7408161665915440489.
GA RNG operators được suy ra tiếp bằng chính sách Milestone 5; seed đầy đủ
được lưu trong selection_details. Cùng final schedule cho mọi method/control,
không phải cam kết cùng outcome cho từng cạnh.

Thống kê dưới đây chỉ để kiểm tra file xuất, **không dùng so sánh chất lượng**:

| Method | P | Rumor mean | Population std | SE | Selection/optimization (s) | Final MC (s) | Optimization calls |
|---|---|---:|---:|---:|---:|---:|---:|
| No Intervention | [] | 316.85 | 205.8119 | 47.2165 | 0 | 0.024415 | 0 |
| Random | [723,757] | 296.50 | 195.1916 | 44.7800 | 0.000253 | 0.025652 | 0 |
| Degree | [82,160] | 15.10 | 13.3413 | 3.0607 | 0.000471 | 0.032927 | 0 |
| PageRank | [62,160] | 21.80 | 24.1818 | 5.5477 | 0.151477 | 0.032475 | 0 |
| Candidate-Restricted Greedy | [107,121] | 13.75 | 11.9033 | 2.7308 | 0.045533 | 0.032801 | 9 |
| GA | [292,611] | 169.15 | 159.2857 | 36.5426 | 0.027345 | 0.032697 | 5 |

Optimization: 14 actual evaluator calls × S_opt=3 = 42 CIC simulations.
Final: 6 calls × S_eval=20 = 120 CIC simulations. **Tổng 162**, không đếm cache
hits thành mô phỏng mới. Preflight GA upper bound=10 calls/30 simulations;
thực tế 5 calls/15 simulations, 5 cache hits. Restricted có đúng 9 calls/27
simulations. Evaluator calls khác số lần mô phỏng CIC.

Convergence CSV của GA ghi generation 0, 1, 2:

| Generation | Best training fitness | Mean training fitness | Actual calls cộng dồn |
|---|---:|---:|---:|
| 0 | 22.0 | 185.25 | 4 |
| 1 | 22.0 | 26.8333 | 5 |
| 2 | 22.0 | 23.6667 | 5 |

Best training fitness=22.0 và independent final mean=169.15 được lưu riêng.
Pilot rất nhỏ/nhiễu; history chỉ kiểm tra logging, cache và việc giữ elite,
không chứng minh hội tụ về tối ưu hoặc độ chính xác của fitness.

Timing lần đầu: loading=0.025807 s; preprocessing=0; selection/optimization
tổng=0.225079 s; final MC tổng=0.180967 s; primary writes=0.001201 s;
orchestration/provenance/integrity/serialization khác=0.134495 s;
**total=0.567548 s**. Replay total=0.616170 s. Total từ API entry tới xong
primary artifact writes, không gồm config parsing và ghi final manifests/rename;
runtime không bao gồm khởi động Python/import trước API. PageRank lần đầu có
chi phí import trong selection. Timing không được dùng làm benchmark.

Môi trường được ghi tự động: CPython 3.15.2, Darwin arm64, 10 logical CPUs,
17.179.869.184 bytes physical memory; phiên bản mọi installed libraries nằm
trong metadata. Hardware model không đọc được trong môi trường hiện tại nên
để null, không điền giả. Git commit lúc chạy:
`2b12bc1e7695b9d5d30a0bb6c43f1a27ada2fe80`, working tree dirty; metadata có
source SHA-256 để phân biệt code chưa commit.

## Reproducibility và bảo toàn dữ liệu

- Replay khớp mọi non-timing field của summary, gồm R/P/seed/metrics/counters.
  120 raw final observations byte-identical; kiểm tra SHA-256 primary artifacts
  khớp manifest của cả hai run.
- Đối chiếu snapshot trước/sau: **32/32 files không đổi**: toàn bộ 14 data
  files, source data pipeline/IC/CIC/MC/algorithms cũ và requirements.txt.
- Không thêm hoặc xóa data files. Processed topology/checksum giữ nguyên:
  email 1.005/24.929 directed; Facebook 4.039/88.234 undirected;
  Wiki-Vote 7.115/103.689 directed. Full test suite có integration checks dữ liệu.
- Không benchmark Facebook/Wiki-Vote, không chạy study hoặc main experiments.

Các file mới thuộc Milestone 6: `src/experiments/*.py`,
`experiments/run_experiment.py`, `experiments/configs/runner_smoke_email.json`,
`tests/experiment_helpers.py`, `tests/test_experiment_config.py`,
`tests/test_experiment_metrics.py`, `tests/test_experiment_runner.py` và báo cáo
này. Sửa `main.py`, `README.md`, `PROJECT_CONTEXT.md`, `EXPERIMENT_PLAN.md`.
Các thay đổi chưa commit từ milestone trước được giữ nguyên.

## Cần chốt trước main experiments

R explicit/policy (fixed hay per_run), kích thước R, k/p grid, S_opt/S_eval,
số independent runs, master seeds/fixed block width; GA N/G/rates/tournament/
elitism/cache; candidate pool rule/size và computational limits, đặc biệt Full
Greedy; môi trường đo runtime thống nhất và output root chính thức. Các tham
số nghiên cứu này vẫn là cấu hình thay đổi được, không bị chốt bởi file smoke.
