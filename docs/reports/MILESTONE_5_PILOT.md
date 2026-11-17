# Milestone 5 — Genetic Algorithm implementation pilot

**Chỉ kiểm tra triển khai, invariants, convergence cơ bản và chi phí đánh giá.**
Không phải kết quả thực nghiệm chính thức hoặc so sánh chất lượng GA/baseline.
Không chạy benchmark Facebook/Wiki-Vote và không triển khai experiment runner.

## API và biểu diễn

```python
from src.algorithms import select_genetic_algorithm
from src.evaluation import evaluate_cic

ga = select_genetic_algorithm(
    graph, rumor_seeds=[0], k=2, propagation_probability=0.05,
    number_of_simulations=20, population_size=8, max_generations=5,
    crossover_rate=0.8, mutation_rate=0.3, tournament_size=3, elitism_count=1,
    random_seed=2026, fitness_base_random_seed=100000,
    tie_breaking="protector-priority", cache_fitness=True,
)
held_out = evaluate_cic(
    graph, [0], ga.best_protector_nodes, 0.05, 100,
    base_random_seed=ga.seeds.independent_evaluation_base_random_seed,
    tie_breaking="protector-priority",
)
```

- Cá thể là frozenset đúng k node trong toàn bộ V ngoài R, không giới hạn theo
  degree. Node IDs không cần liên tục; thứ tự label dùng hợp đồng CIC.
- Mỗi cá thể initial được lấy mẫu ngẫu nhiên không hoàn lại. Genotype giữa các
  slot quần thể có thể trùng nhau; vẫn luôn đúng N slot ở k=0 hoặc k=m.
- Tournament lấy slot không hoàn lại, minimum fitness thắng; tie theo genotype
  chuẩn hóa rồi slot index. Set Crossover giữ intersection và bù từ symmetric
  difference. Mutation thay đúng một gene khi có gene ngoài cá thể để thay.
- Repair loại gene sai/trùng và trim/fill về k. Operator và từng generation đều
  kiểm tra invariants; graph/seeds không bị sửa.
- Elite là top E slot, giữ nguyên genotype cùng fitness, không chịu toán tử.
  E=0..N hợp lệ. Khi E=0, trả best-ever dù population cuối có thể kém hơn.
- Generation 0 là initial population; G transitions tạo G+1 history records,
  không early stop. k=0 vẫn chạy đúng G transitions và đánh giá P rỗng thật.

## Chính sách fitness đã được người dùng xác nhận

Fitness dùng chính evaluate_cic với S_opt, không đổi CIC hoặc objective mean rumor.
Mọi genotype trong một optimization dùng cùng graph/R/p/S_opt/tie/base seed.
Noise do Monte Carlo vẫn tồn tại nhưng objective mẫu này được cố định.

Cache là dictionary cục bộ của một lần gọi, key=frozenset genotype. Key đủ vì
mọi context còn lại giữ cố định; không cache xuyên run hoặc khi đổi seed/S/p/R.
Cache hits và elite carries không phải đánh giá mới, không tăng số simulations
hay độ chính xác của fitness. Elite giữ fitness ban đầu, không resample.

cache_fitness=False gọi lại evaluate_cic cho non-elite requests trên cùng lịch
seed, không đổi sang sample mới. Tests xác nhận evolution không đổi khi bật/tắt
cache, chỉ counters/runtime thay đổi. Report tách fitness_request_count,
evaluation_count, cache_hit_count và elite_fitness_reuse_count.

Fixed objective có thể bị overfit trong quá trình chọn P. best_estimated_fitness
chỉ là training/optimization score; kết quả độc lập được tính sau khi chốt P,
không được dùng ngược vào selection/crossover/mutation hoặc chọn lần chạy.

## Lịch seed

- Master random_seed=2026.
- Operators seed = integer 64-bit đầu SHA-256 của
  `misinformation-ga-v1:operators:2026`, bằng **16143063791218104179**.
  Một RNG local dùng cho initialization và operators, không dùng RNG toàn cục.
- Fitness base được truyền rõ là 100000. Nếu không truyền, suy ra bằng cùng
  SHA-256 scheme với domain `fitness` thay `operators`.
- Email S_opt=20: mọi fitness dùng seeds **100000..100019**.
- Independent S_eval=100: seeds **100020..100119**, không giao interval tối ưu.
- Đổi graph insertion order/seed input/PYTHONHASHSEED không đổi evolution trong
  môi trường được ghi nhận. Chung lịch seed không bảo đảm common edge outcomes
  giữa các P theo semantics evaluator hiện có.

## Pilot tổng hợp nhỏ

Cùng N=8, G=4, rates 0.8/0.3, tournament=3, E=1, S_opt=3, S_eval=5, p=1,
random_seed=2026, R=[0]. Oracle exhaustive được tính sau khi GA đã chọn P, không
tham gia initialization/selection. Chỉ oracle trên graph tối đa 6 nodes.

| Graph | k | GA P | Optimization mean | Independent mean | Opt evaluator calls | Opt CIC count |
|---|---:|---|---:|---:|---:|---:|
| Directed 0→1→2→3 | 1 | [1] | 1 | 1 | 3 | 9 |
| Undirected 0—1—2—3—4 | 1 | [1] | 1 | 1 | 4 | 12 |
| 0→10→1→2 và 0→20→30 | 2 | [10,20] | 1 | 1 | 9 | 27 |

Cả ba đạt optimum kiểm chứng bằng oracle ở cấu hình/seed này; không suy ra bảo
đảm optimum chung cho GA. Best có thể đã xuất hiện trong initial population;
mean population vẫn có thể dao động vì mutation, dù best không tăng khi E>=1.

## Email-Eu-core: convergence và chi phí

Cấu hình được lưu tại experiments/configs/ga_pilot_email.json:
DiGraph 1.005 nodes / 24.929 edges, R=[0], k=2, p=0.05, protector-priority,
N=8, G=5, rates 0.8/0.3, tournament=3, E=1, S_opt=20, cache=True.
Không gian hợp lệ có m=1004 nodes, C(1004,2)=503506 genotype.

| Generation | Best fitness | Mean fitness | Unique genotypes | New evaluator calls |
|---:|---:|---:|---:|---:|
| 0 | 77,85 | 177,18125 | 8 | 8 |
| 1 | 77,85 | 117,73750 | 6 | 3 |
| 2 | 77,85 | 113,93750 | 4 | 2 |
| 3 | 69,60 | 79,03125 | 3 | 1 |
| 4 | 41,15 | 70,16875 | 3 | 1 |
| 5 | 41,15 | 62,85000 | 3 | 1 |

P cuối/best-ever: **[113,271]**. Đây là convergence của objective mẫu cố định,
chưa phải đường hội tụ của kỳ vọng thật. Independent evaluation có mean rumor
**60,93**, population std **78,729442**, khác optimization score 41,15.
Không dùng 41,15 làm kết quả thực nghiệm cuối hoặc kết luận so sánh thuật toán.

Chi phí một optimization:

- Fitness requests: **43 = N+G*(N-E)**; elite fitness carries riêng: **5**.
- Actual evaluator calls: **16**; cache hits: **27**; CIC simulations: **320**.
- Không cache, cùng chính sách elite sẽ có 43 calls / 860 CIC simulations.
- Optimization runtime: **0,528348 giây**, trong đó evaluator **0,515886 giây**.
- Independent evaluation: thêm **1 call / 100 simulations**, **0,164081 giây**.
- Một optimization + independent evaluation: **17 calls / 420 simulations**.
- Kể thêm một optimization replay: email tổng **33 calls / 740 simulations**.
- Toàn pilot bốn graph kể replay/held-out/toy oracle: **85 calls / 868 simulations**.

Đây là runtime đo trên macOS 15.3.1 ARM64, Python 3.15.2, NetworkX 3.7,
không gồm load/I/O trong optimization/evaluation runtime. Runtime sẽ dao động
khi chạy lại. Mức S nhẹ chỉ kiểm tra thực thi, không thay S_opt/S_eval chính thức
hoặc yêu cầu độ chính xác đã khảo sát ở 4A. Chưa chạy parameter study.

## Kiểm thử và xác minh

260/260 tests pass: 209 cũ, 20 operator tests và 31 optimizer tests mới.
Bao phủ initialization, Tournament, Set Crossover, mutation, repair, elite,
stopping, k=0/k=m, quá budget, sparse/mixed IDs, directed/undirected, seed domains,
graph/RNG không đổi, cache context/disable/replay, và process hash independence.

Sau pilot, đối chiếu độc lập toàn bộ population snapshots, fitness ledger,
mean/min/diversity, elite preservation, cache/request/CIC accounting, CSV counts,
held-out seed ranges và raw held-out statistics. Hai fitness records email được
replay trực tiếp qua evaluate_cic. Tất cả khớp.

Toàn bộ 14 raw/processed files giữ nguyên SHA-256; simulator/evaluator/baseline/
Greedy cũ và requirements.txt không đổi. Milestone 5 không thêm dependency.

## Tái lập và artifacts

```sh
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B -m experiments.pilot_genetic_algorithm
```

Đầu ra trong results/pilots/genetic_algorithm/ (được Git bỏ qua):

- config.json, preflight từng case và report.json tổng.
- convergence.png: training generation-best, mean và best-so-far; không trộn
  điểm held-out vào đường training.
- Mỗi case có convergence.csv, convergence.json, fitness_evaluations.csv,
  report.json. JSON lưu cả params/seeds/populations/fitness/independent raw results.
- CSV evaluation ledger chỉ ghi actual calls của optimization đầu; cache hits,
  replay, independent evaluation và oracle được đếm riêng trong JSON.

History giữ population snapshots, tốn bộ nhớ O(G*N*k). Chi phí CIC tối đa không
cache là [N+G*(N-E)]*S_opt; cache có thể giảm nhưng không bảo đảm tìm lời giải tốt
hoặc giảm noise. Không có bảo đảm tối ưu toàn cục hoặc kết luận chất lượng trên
các dataset/configurations khác. Experiment runner/thực nghiệm chính thức vẫn
nằm ngoài Milestone 5.
