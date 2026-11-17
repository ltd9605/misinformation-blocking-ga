# Milestone 4B — Greedy/Monte-Carlo implementation pilot

Số liệu chỉ kiểm tra tính đúng đắn/khả năng thực thi, **không phải kết quả chính
thức**. Không chạy Full Greedy trên email hoặc benchmark Greedy trên Facebook/
Wiki-Vote. IC/CIC/Monte Carlo và topology dữ liệu được giữ nguyên.

## API

```python
from src.algorithms import (
    estimate_greedy_cost, select_greedy, select_candidate_restricted_greedy,
)

cost = estimate_greedy_cost(candidate_count=3, k=2, number_of_simulations=20)
full = select_greedy(
    small_graph, rumor_seeds=[0], k=2,
    propagation_probability=1, number_of_simulations=3,
    base_random_seed=42, tie_breaking="protector-priority",
)
limited = select_candidate_restricted_greedy(
    graph, rumor_seeds=[0], k=2,
    propagation_probability=0.05, number_of_simulations=20,
    candidate_nodes=pool, base_random_seed=100000,
    tie_breaking="protector-priority",
)
```

Full Greedy xét mọi node ngoài R/P tại mỗi bước bằng evaluate_cic(P union {v}),
chọn minimum mean rumor count; mean bằng nhau chính xác dùng label chuẩn hóa
tăng dần. Lặp đúng k, không early stop, không prefilter degree, không lazy/CELF
hoặc giả định submodularity. Full không phải tìm optimum trên mọi tổ hợp k node.

Candidate-Restricted Greedy có API và result.algorithm riêng; pool cố định được
truyền rõ ràng, không cắt graph. Pool chứa R hoặc node không tồn tại bị từ chối.
Pool bằng toàn bộ eligible nodes cho cùng history như Full nhưng vẫn được gắn
nhãn Candidate-Restricted nếu gọi API đó.

Mọi trial dùng cùng S/base seed/tie rule; simulation i vẫn dùng base+i theo
evaluator hiện có. Không bảo đảm common edge-level random outcomes giữa các P.
History lưu P/selected node/mean/std mọi bước, tất cả candidate scores và timing.
Raw S observations hoặc node sets của mọi trial không bị giữ lại trong history.
Runtime được loại khỏi value equality để kiểm tra replay. k=0 trả 0 calls, P rỗng,
không có history, final score=None; không tạo score giả cho tập rỗng.

## Work estimate trước khi thực thi dữ liệu thật

Với m candidates, k<=m:

E = m + (m-1) + ... + (m-k+1) = k*m - k*(k-1)/2.

E là số lần gọi evaluate_cic. Số simulation CIC là E*S. Full có m=n-|R|,
restricted có m=|pool|. Không có call phụ cho P rỗng hoặc đánh giá lại P cuối.

| Trường hợp | m | k | S | Evaluator calls | CIC simulations | Đã thực thi? |
|---|---:|---:|---:|---:|---:|---|
| Full, email cấu hình tham khảo 4A | 1004 | 5 | 500 | 5010 | 2505000 | Không |
| Full, email cùng budget pilot | 1004 | 2 | 20 | 2007 | 40140 | Không |
| Candidate-Restricted, email | 10 | 2 | 20 | 19 | 380 | Có |

Đây là khối lượng tính toán, không phải runtime dự đoán. Runtime Full Greedy trên
email chưa được đo. Thời gian thực tế còn phụ thuộc graph, p, R/P và activation;
không chuyển công thức số calls thành một khẳng định runtime.

## Full Greedy kiểm tra tính tay

Tất cả dùng p=1, S=3, base seed=42, protector-priority, R=[0], k=2:

| Graph | Cạnh | Thứ tự chọn | Mean rumor từng bước | Calls |
|---|---|---|---|---:|
| Directed chain | 0→1→2→3 | [1,2] | [1,1] | 5 |
| Undirected chain | 0—1—2—3 | [1,2] | [1,1] | 5 |
| Hai nhánh | 0→10→1→2 và 0→20→30 | [10,20] | [3,1] | 9 |

Trường hợp hai nhánh xác nhận việc tính lại objective sau mỗi lựa chọn:
singleton score của node 1 bằng node 20; sau khi chọn 10, cần chọn 20 để chặn
nhánh còn lại. Không được chỉ lấy top-k singleton scores độc lập.

Ba graph dùng tổng 19 evaluator calls / 57 CIC simulations.

## Candidate-Restricted email pilot

Cấu hình: `experiments/configs/greedy_email.json`.

- email-Eu-core processed, DiGraph 1.005 nodes / 24.929 edges; R=[0].
- k=2, p=0.05, S=20, base seed=100000, protector-priority.
- Pool top-10 out-degree ngoài R, dùng chính select_degree của 4A:
  [13,62,82,86,107,121,160,183,249,434].
- Graph đầy đủ được đưa vào evaluator; chỉ không gian tìm kiếm bị giới hạn.
- S=20 chỉ là smoke budget, không thay thế S_opt/S_eval từ pilot 4A.

| Bước | Node chọn | P sau bước | Mean rumor dùng để chọn | Population std | Calls |
|---:|---:|---|---:|---:|---:|
| 1 | 62 | [62] | 31,25 | 33,226307 | 10 |
| 2 | 160 | [62,160] | 13,25 | 11,466800 | 9 |

Thời gian đo trong lần pilot đã lưu:

- Dựng candidate pool: 0,000421 giây, tách khỏi search.
- Search đầu: **0,599700 giây**, gồm **0,599117 giây** trong evaluate_cic.
- Search replay: 0,608310 giây; selection order/P/trial scores khớp hoàn toàn.
- Một search: 19 calls / 380 simulations.
- Hai search email kể cả replay: **38 calls / 760 simulations**.
- Toàn bộ pilot kể cả ba graph nhỏ: **57 calls / 817 simulations**.
- Wall runtime pilot trước ghi report: 1,266124 giây, có cả load/check/hash/CSV.

Score 13,25 là optimization score trên mẫu đã dùng để lựa chọn, không phải một
held-out evaluation hoặc bằng chứng chất lượng Full Greedy. Không suy rộng kết
quả của pool 10 nodes thành kết quả trên toàn bộ 1004 candidates.

## Kiểm thử và dữ liệu

209/209 tests pass: 179 cũ và 30 Greedy tests mới. Bao gồm k=0/đủ k/quá budget,
loại R, sparse IDs, directed/undirected, score tie, RNG/replay, oracle exhaustive
từng bước, đúng mọi call P union {v}, input không đổi, error propagation và hai
biến thể có tên rõ ràng. Toàn bộ raw/processed, IC/CIC/MC, baseline cũ và
requirements.txt giữ nguyên từng byte; Milestone 4B không thêm dependency.

## Artifacts và tái lập

```sh
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B -m experiments.pilot_greedy
```

`results/pilots/greedy/` có config.json, preflight.json ghi trước dataset search,
report.json, steps.csv và trials.csv. CSV chỉ chứa search đầu; replay có số calls
và runtime riêng trong JSON. JSON lưu thêm graph tính tay, môi trường, chi phí
dựng pool, checksum raw/processed và các hạn chế. `results/` được Git bỏ qua;
có thể tái tạo bằng lệnh trên. Runtime có thể đổi khi chạy lại.

Chưa triển khai Genetic Algorithm. Full Greedy có chi phí O(k*m) evaluator calls,
mỗi call lại dùng S simulations. Không có bảo đảm tối ưu toàn cục, và nhiễu MC
có thể làm thay đổi thứ tự chọn khi đổi seed/S. Cần đánh giá độc lập bằng seed
mới và S phù hợp trước khi dùng lời giải cho so sánh chính thức.
