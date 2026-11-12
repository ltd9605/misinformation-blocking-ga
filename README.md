# Misinformation blocking — Milestones 1–9

Dataset pipeline cho đồ án nghiên cứu ngăn chặn lan truyền thông tin sai lệch.
Phạm vi hiện tại: load, validate, preprocess, lưu/đọc graph và mô phỏng
Independent Cascade (IC), Competitive Independent Cascade (CIC), Monte Carlo
evaluator, ba baseline Random/Degree/PageRank, Greedy/Monte-Carlo (Full và
Candidate-Restricted), Genetic Algorithm và Experiment Runner cấu hình bằng JSON.
Main Experiments đã hoàn thành theo Protocol V2; kết quả và biểu đồ ở
[MAIN_EXPERIMENTS_RESULTS.md](MAIN_EXPERIMENTS_RESULTS.md).

Bản chốt dùng cho phụ lục báo cáo:
[THESIS_VERSION.md](THESIS_VERSION.md), tag `thesis-chapter3-v1.0`.

Để tự cấu hình và chạy một ví dụ nhỏ, xem
[Hướng dẫn chạy thủ công](HUONG_DAN_CHAY_THU_CONG.md): đồ thị tổng hợp 9 nút,
JSON có sẵn, preflight, lệnh Terminal, đọc CSV/convergence và kiểm tra bằng tay.

## Môi trường

Đã kiểm tra trên macOS 15.3.1, Apple Silicon (`arm64`), Python 3.15.2 và
NetworkX 3.7. Các phiên bản dependency được ghi trong `requirements.txt`
(UTF-8); tests sử dụng `unittest` của Python. Mã hiện tại cần Python 3.11+
(`hashlib.file_digest`); các dependency đã pin còn phải hỗ trợ phiên bản Python
được chọn. Môi trường đã kiểm tra đầy đủ dùng Python 3.15.2.

Milestone 4A bổ sung `scipy==1.18.1` cho NetworkX PageRank, đã kiểm tra wheel
macOS ARM64; các pin cũ giữ nguyên. Khi cập nhật checkout, chạy lại
`python -m pip install -r requirements.txt` và `python -m pip check`.

Thiết lập trên macOS/Linux bằng Terminal (zsh/bash), tại thư mục repository:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
```

Trên Apple Silicon, kiểm tra `python -c "import platform; print(platform.machine())"`
trả về `arm64` để xác nhận Python chạy native. Tạo lại virtual environment khi
chuyển máy hoặc hệ điều hành; không sao chép `.venv` từ máy cũ. Trong VS Code,
chọn Python interpreter của `.venv`. Các lệnh `python` bên dưới dùng môi trường
đã kích hoạt.

## Chạy dataset pipeline

Chạy tại thư mục repository:

```sh
python main.py dataset --name email-Eu-core
python main.py dataset --name ego-Facebook
python main.py dataset --name Wiki-Vote
```

Mỗi command kiểm tra raw counts, preprocess, lưu artifact, đọc lại để đối chiếu
chính xác nodes/edges/directedness và in thống kê trước/sau. Đường dẫn mặc định
được xác định từ repository, không phụ thuộc working directory.

Tùy chọn:

- `--raw-dir PATH`: thư mục nguồn chứa các thư mục dataset.
- `--output-dir PATH`: thư mục lưu ba artifact của dataset đang chạy.
- `--keep-self-loops`: giữ self-loops, ghi nhận cấu hình trong metadata.
- `--remove-self-loops`: bỏ self-loops, ghi nhận cấu hình trong metadata.

Hai tùy chọn self-loop loại trừ nhau. Nếu không chỉ định, email-Eu-core bỏ loops;
ego-Facebook và Wiki-Vote giữ nguyên dữ liệu. Chạy lại sẽ tái tạo các artifact
trong thư mục output; mọi đường dẫn output trỏ vào raw đều bị từ chối.

## Nguồn và quy tắc dữ liệu

Nguồn: Stanford SNAP, các tệp đã có trong `data/raw/`.

| Dataset | Edge list | Loại | Nodes gốc | Edges gốc | Self-loops gốc | Edges processed mặc định |
|---|---|---|---:|---:|---:|---:|
| email-Eu-core | `email-Eu-core/email-Eu-core.txt.gz` | Directed | 1.005 | 25.571 | 642 | 24.929 |
| ego-Facebook | `ego-Facebook/facebook_combined.txt.gz` | Undirected | 4.039 | 88.234 | 0 | 88.234 |
| Wiki-Vote | `wiki-Vote/wiki-Vote.txt.gz` | Directed | 7.115 | 103.689 | 0 | 103.689 |

Đây là thống kê cấu trúc dữ liệu được kiểm tra, không phải kết quả thực nghiệm
lan truyền. Cả ba nguồn hiện không có duplicate edges.

- Raw được mở để đọc, không chỉnh sửa hoặc giải nén đè lên dữ liệu nguồn.
- Loader nhận edge list plain hoặc gzip, bỏ qua dòng trống, header/comment `#`.
  Mỗi bản ghi phải có đúng hai integer node ID; inline comment `#` được hỗ trợ.
- Duplicate edges và dòng không hợp lệ gây lỗi rõ ràng. Với undirected graph,
  `(u, v)` và `(v, u)` là cùng một cạnh; với directed graph chúng là hai cạnh khác nhau.
- Không thay đổi node ID, hướng cạnh, không lấy largest connected component,
  không bổ sung node bằng `range(max_id + 1)` và không loại isolated nodes.
- **email-Eu-core sau bỏ loops vẫn giữ 1.005 nodes, gồm 19 isolated nodes.**
- Wiki-Vote có 7.115 node ID trong khoảng 3–8297; ID không liên tục.
- Department labels và `facebook.tar.gz` được giữ nguyên nhưng không dùng làm
  nguồn topology. Pipeline không tự động gộp các ego networks trong archive.

## Dữ liệu processed và cách sử dụng

```text
data/processed/<dataset>/
├── nodes.csv       # node_id, gồm cả isolated nodes
├── edges.csv       # source,target, mỗi cạnh lưu một lần
└── metadata.json   # source/config/counts/environment/SHA-256
```

Các CSV được sắp xếp ổn định. Loại graph được lưu trong metadata; cạnh undirected
được chuẩn hóa với `source <= target`. `load_processed_graph()` kiểm tra checksum,
node references, duplicates và counts trước khi trả về graph.

```python
from src.data import load_processed_graph
from src.data.specs import PROJECT_ROOT

graph = load_processed_graph(PROJECT_ROOT / "data/processed/email-Eu-core")
assert graph.is_directed()
assert graph.number_of_nodes() == 1005
assert graph.number_of_edges() == 24929
```

Có thể chạy pipeline bằng Python API:

```python
from src.data import PreprocessConfig, prepare_dataset

result = prepare_dataset("email-Eu-core")
graph = result.graph
metadata = result.metadata

# Chỉ định rõ một cấu hình khác; nên lưu ra thư mục riêng.
variant = prepare_dataset(
    "email-Eu-core",
    config=PreprocessConfig(remove_self_loops=False),
    output_directory="data/processed/email-Eu-core-keep-loops",
)
```

Metadata schema v1 ghi nguồn và SHA-256 của raw, expected raw counts, parse/graph
statistics trước xử lý, cấu hình và phép biến đổi đã thực hiện, statistics sau
xử lý, phiên bản Python/NetworkX và SHA-256 của hai CSV. Không lưu timestamp để
việc tái tạo cùng nguồn/cấu hình/môi trường có đầu ra ổn định. Artifact lưu topology
với integer node IDs; thuộc tính node/edge như labels hoặc weights chưa thuộc schema.
`source.raw_directory` là đường dẫn tương đối từ repository nếu nguồn nằm trong
repository (mặc định `data/raw`), dùng dấu `/` trên mọi hệ điều hành. Nguồn nằm
ngoài repository giữ đường dẫn tuyệt đối của máy chạy để truy vết. Trường này
chỉ ghi provenance; đọc processed graph không cần truy cập raw directory.

## Independent Cascade (Milestone 2)

```python
from src.data import load_processed_graph
from src.data.specs import PROJECT_ROOT
from src.diffusion import simulate_ic

graph = load_processed_graph(PROJECT_ROOT / "data/processed/email-Eu-core")
result = simulate_ic(graph, seed_nodes=[0], propagation_probability=0.05, random_seed=42)
print(result.active_nodes)       # frozenset các nút active cuối cùng, gồm seeds
print(result.active_count)       # số nút active khác nhau
print(result.steps)              # số bước lan truyền có nút mới, không tính t=0
print(result.activation_layers)  # tuple các frozenset, lớp đầu là seeds tại t=0
```

Simulator nhận simple NetworkX `Graph`/`DiGraph`, một iterable seed nodes và một
xác suất thực hữu hạn `p` trong `[0, 1]` áp dụng chung cho mọi cạnh. Thuộc tính
edge như `weight` không tham gia tính xác suất. MultiGraph/MultiDiGraph bị từ
chối để tránh ngầm chọn quy tắc cho cạnh song song. Node labels có thể là bất kỳ
giá trị hashable nào; không cần ID liên tục hoặc các labels so sánh được với nhau.

- Seeds active tại `t=0`; seed trùng được gộp, seed không tồn tại gây `ValueError`.
- Mỗi nút vừa active chỉ thử một lần trên mỗi neighbor chưa active. Cạnh directed
  chỉ cho phép lan tới successor; cạnh undirected cho phép lan theo cả hai chiều.
- Nút kích hoạt thành công được đưa vào lớp kế tiếp, chỉ lan tiếp ở bước sau.
  Một nút chỉ xuất hiện trong một lớp; self-loops và chu trình không tái kích hoạt.
  Khi một nút đã được xếp vào lớp kế tiếp, các lần thử tiếp theo tới nó được bỏ qua.
- Dừng khi không có nút mới. `steps` không tính vòng thử cuối không kích hoạt
  được nút nào. Seeds rỗng trả tập rỗng, không có lớp, `steps=0`; nếu chỉ có seeds
  active thì có một lớp và `steps=0`.
- Không sửa graph, thuộc tính hay seed input. Kết quả dùng các tập bất biến.
- `random_seed` nhận integer hoặc `None`; RNG riêng không thay đổi RNG toàn cục.
  Cùng graph với cùng thứ tự nodes, seed set, `p` và random seed cho cùng kết quả.
  Thứ tự seed input/edge insertion không ảnh hưởng nếu thứ tự nodes không đổi.
  Graph đọc từ processed CSV có thứ tự nodes ổn định. `None` không bảo đảm tái lập.

Chạy các ví dụ tính tay và một pilot nhỏ trên email-Eu-core:

```sh
python -B -m experiments.pilot_ic
```

Script kiểm tra directed/undirected chain, isolated seed và `p=0`, sau đó chạy
email-Eu-core với seeds `[0]`, `p=0.05`, random seed `42`, kiểm tra chạy lại cho
cùng kết quả và SHA-256 của artifacts không đổi. Cấu hình, môi trường, tập active,
các lớp lan truyền và runtime chẩn đoán được lưu trong
`results/pilots/ic_email_eu_core.json` (được Git bỏ qua theo `results/`).
**Pilot chỉ kiểm tra triển khai, không phải kết quả chính thức của đồ án.**

## Competitive Independent Cascade (Milestone 3)

```python
from src.diffusion import TieBreakingRule, simulate_cic

result = simulate_cic(
    graph, rumor_seeds=[0], protector_seeds=[1], propagation_probability=0.05,
    tie_breaking=TieBreakingRule.PROTECTOR_PRIORITY, random_seed=42,
)
print(result.rumor_nodes, result.rumor_count)
print(result.protector_nodes, result.protector_count)
print(result.inactive_nodes, result.inactive_count)
print(result.steps)
for layer in result.activation_layers:
    print(layer.rumor_nodes, layer.protector_nodes)
```

CIC nhận simple Graph/DiGraph trực tiếp từ `load_processed_graph()`, dùng một
`p` hữu hạn trong `[0, 1]` chung cho hai cascade. Bỏ qua thuộc tính cạnh và từ
chối MultiGraph giống IC. R/P phải tồn tại trong graph và không giao nhau;
seed trùng trong cùng cascade được gộp. Kết quả là dataclass frozen chứa các
frozenset; ba tập cuối cùng tạo thành một partition của toàn bộ nodes.

Quy tắc đã chốt trong mục 3 của `PROJECT_CONTEXT.md`:

- Seeds R/P active tại lớp 0. Chỉ nodes ở lớp trước thử truyền ở timestep kế tiếp,
  một lần trên mỗi neighbor chưa active; DiGraph chỉ lan theo successor.
- Thu thập riêng các thành công của RUMOR và PROTECTOR trong toàn bộ timestep.
  Đích đã có thành công từ cùng cascade có thể bỏ qua lần thử dư thừa; cascade
  đối thủ vẫn được thử tới đích đó trong timestep hiện tại.
- Sau khi thu thập xong mới giải quyết cạnh tranh và cập nhật trạng thái.
  Chỉ một cascade thành công thì cascade đó thắng. Nếu cả hai thành công,
  `protector-priority` ưu tiên PROTECTOR, `rumor-priority` ưu tiên RUMOR.
  `tie_breaking` là keyword bắt buộc (enum hoặc chuỗi), không có default ngầm.
- Node đã active giữ nguyên cascade vĩnh viễn. Dừng khi không có node mới.
  `steps` có cùng cách đếm với IC; cả hai tập seeds rỗng trả không có lớp.

CIC dùng RNG riêng và chuẩn hóa thứ tự nguồn/neighbor theo loại rồi giá trị
label, không dựa vào thứ tự chèn nodes/edges, thứ tự seeds hay Python hash.
Hỗ trợ chính xác các kiểu built-in `int`, `bool`, `str`, `bytes`, `float` hữu hạn
và tuple/frozenset tổ hợp những kiểu đó. Label object tùy biến bị từ chối bằng
`TypeError`, không dùng `repr` hoặc địa chỉ bộ nhớ để sắp xếp. Cùng cấu hình,
graph và integer random seed cho cùng partition và activation layers, kể cả
khi đảo thứ tự chèn graph hoặc đổi `PYTHONHASHSEED`. `None` không bảo đảm tái lập.
IC giữ nguyên API, code và quy ước duyệt của Milestone 2; CIC có quy ước duyệt
chuẩn hóa riêng. Với graph integer có thứ tự node chuẩn như processed datasets,
CIC chỉ có một cascade cho cùng kết quả như IC khi dùng cùng cấu hình/seed.

Chạy các ví dụ tính tay và pilot kiểm tra CIC trên email-Eu-core:

```sh
python -B -m experiments.pilot_cic
```

Pilot cố định R=`[0]`, P=`[1]`, `p=0.05`, random seed `42`, tie rule
`protector-priority`. Cấu hình, partition cuối cùng, activation layers, môi trường,
runtime chẩn đoán, 10 ví dụ tính tay và SHA-256 toàn bộ dữ liệu được lưu tại
`results/pilots/cic_email_eu_core.json`. Script kiểm tra tái lập, đảo thứ tự chèn
graph và toàn bộ raw/processed không đổi. File kết quả nằm trong `results/`
được Git bỏ qua. **Pilot không phải kết quả chính thức của đồ án.**

## Monte Carlo evaluator

```python
from src.evaluation import evaluate_cic

estimate = evaluate_cic(
    graph, rumor_seeds=[0], protector_seeds=[1], propagation_probability=0.05,
    number_of_simulations=100, base_random_seed=42,
    tie_breaking="protector-priority",
)
print(estimate.mean_rumor_count, estimate.std_rumor_count)
print(estimate.mean_protector_count, estimate.mean_inactive_count)
print(estimate.min_rumor_count, estimate.max_rumor_count)
print(estimate.number_of_simulations, estimate.runtime_seconds)
print(estimate.raw_results[0])
```

Evaluator gọi nguyên vẹn `simulate_cic()` đúng S lần. `number_of_simulations`
phải là integer dương, `base_random_seed` phải là integer không âm; booleans
bị từ chối. Simulation i (0-based) dùng seed `base_random_seed + i`, không dùng
RNG toàn cục. Các input graph/seeds/p/tie giữ nguyên validation và semantics CIC.
Seed iterable được materialize một lần, nên generator cũng được tái sử dụng
nhất quán trong tất cả simulation. Không sửa graph hay các seed collections.

Kết quả frozen gồm các thống kê và `raw_results`: tuple các record frozen có
`simulation_index`, `random_seed`, `rumor_count`, `protector_count`,
`inactive_count`, `steps`. Chỉ lưu counts, không giữ các tập node/layers của mọi
lần chạy, để bộ nhớ cho raw observations tăng theo S. Dùng seed trong record để
chạy lại một simulation trực tiếp bằng CIC khi cần xem chi tiết.

`std_rumor_count` là độ lệch chuẩn **tổng thể của S counts**, mẫu số S (`ddof=0`),
không phải sample std hay standard error. Với S=1, std=0. Runtime dùng
`perf_counter`, bao gồm chuẩn hóa seed input, S lần gọi CIC và tổng hợp;
không gồm load dataset hay ghi file. Runtime không tái lập và được loại khỏi
phép so sánh giá trị `MonteCarloResult`; các thống kê và raw observations vẫn
phải khớp hoàn toàn khi cùng cấu hình/base seed.

Cùng base seed tạo cùng lịch seed cho các protector sets. Điều này không đồng
nghĩa mỗi cạnh sẽ có cùng random outcome giữa hai cấu hình: số/thứ tự các lần
thử hợp lệ của CIC có thể thay đổi. Tăng S giữ nguyên prefix các simulation cũ.

Chạy pilot nhỏ (S=100, R=`[0]`, P=`[1]`, p=`0.05`, base seed `42`,
`protector-priority`) và kiểm tra cấu hình protector trên chain tính tay:

```sh
python -B -m experiments.pilot_monte_carlo
```

Pilot lưu cấu hình, mean/std, min/max, raw observations, môi trường, runtime
và checksum toàn bộ dữ liệu vào `results/pilots/monte_carlo_email_eu_core.json`.
Một batch thứ hai kiểm tra replay các thống kê/quan sát; runtime báo cáo là của
batch S simulation đầu tiên. **Đây là kiểm tra triển khai/hiệu năng, không phải
kết quả chính thức của đồ án.** File kết quả nằm trong `results/` được Git bỏ qua.

## Baseline algorithms (Milestone 4A)

```python
from src.algorithms import select_random, select_degree, select_pagerank

R, k = [0], 5
random_P = select_random(graph, R, k, random_seed=2026)
degree_P = select_degree(graph, R, k)
pagerank_P = select_pagerank(graph, R, k)
estimate = evaluate_cic(graph, R, degree_P, 0.05, 500,
                        base_random_seed=100000, tie_breaking="protector-priority")
```

Mỗi baseline trả `frozenset` đúng k node khác nhau ngoài R; không yêu cầu ID
liên tục. K=0 hợp lệ; thiếu candidate hoặc seed không tồn tại gây lỗi. Không sửa
graph hay seed input. Hỗ trợ cùng node label chuẩn hóa như CIC.

- Random chọn đều không hoàn lại từ candidate list chuẩn hóa bằng RNG riêng.
- Degree xếp giảm dần theo **out-degree** trên DiGraph, degree trên Graph,
  không dùng weight; khi bằng điểm, label tăng dần quyết định. Raw counts và
  degree/(n-1) cho cùng xếp hạng trên một graph.
- PageRank dùng `nx.pagerank` trên graph copy có thứ tự chuẩn hóa, **giữ toàn bộ
  rumor nodes khi tính điểm** rồi lọc R khi chọn. alpha=0.85, tol=1e-12,
  max_iter=1000, weight=None, teleportation/dangling mass đều. Điểm bằng nhau
  chính xác dùng label tăng dần. Không có fallback đổi thuật toán khi không hội tụ.

## Monte Carlo stability pilot (Milestone 4A)

```sh
python -B -m experiments.pilot_mc_stability
```

Cấu hình được commit tại `experiments/configs/mc_stability_email.json`:
email-Eu-core, R=[0], k=5, p=0.05, protector-priority. Tạo một P rỗng và chọn
ba P baseline một lần (Random seed 2026), sau đó giữ nguyên P để chỉ đo nhiễu MC.
Không dùng các random P mới trong mỗi batch để tránh trộn nhiễu chọn nút với MC.

Chạy S=50,100,250,500,1000 trên 10 batch. Batch b dùng base seed
`100000+1000*b`; simulation i dùng base+i. Mỗi batch chiếm tối đa 1000 seed,
không trùng batch khác. Các mức S trong cùng batch có prefix lồng nhau, không
được xem như các thí nghiệm độc lập; mọi P dùng cùng lịch seed. Đây không bảo
đảm cùng outcome trên mỗi cạnh. Thứ tự 200 evaluation được xáo trộn xác định
bằng execution_order_seed=2027; runtime được đo riêng cho từng evaluation.

Phân biệt các thống kê:

- Population std của counts giữ đúng giá trị từ evaluator (`ddof=0`), không nhất
  thiết giảm khi S tăng.
- Sample std = population std * sqrt(S/(S-1)); **SE = sample std/sqrt(S)**.
- SD của 10 batch means đo biến động thực tế giữa các ước lượng mean độc lập.
- Pooled SE dựa trên 10*S quan sát; không dùng nó để chọn S cho một evaluation.

Ngưỡng kỹ thuật khai báo trước: worst single-batch SE qua các P/batch <=1% số
nodes cho S_opt và <=0.5% cho S_eval. Nếu chưa đạt, report ghi `target_met=false`,
chỉ lấy S lớn nhất đã đo làm lựa chọn tạm và ước lượng số simulation cần thêm.
Đề xuất này phụ thuộc dataset/R/P/p/k; không phải tiêu chuẩn chính thức của đồ án.

Kết quả tại `results/pilots/mc_stability/` (được Git bỏ qua):

- `config.json`, `selections.csv`: R/P, cấu hình và thời gian chọn P một lần.
- `batches.csv`: 200 evaluation, mean/std/SE, runtime MC tách khỏi selection.
- `raw_results.csv`: 76.000 CIC observations kèm method/S/batch/seed để replay.
- `summary.csv`, `rankings.csv`: biến động theo S và độ nhất quán xếp hạng của
  ba P cố định; không suy rộng thành xếp hạng thuật toán trên mọi cấu hình.
- `report.json`, `analysis.md`, `stability.png`: tổng hợp, đề xuất có điều kiện,
  môi trường, checksum và biểu đồ. Error bars của mean là SD của batch means.

**Toàn bộ là pilot, không dùng làm kết quả chính thức.** Baseline P được đánh giá
bằng chính `evaluate_cic()`; không sửa IC/CIC/Monte Carlo hoặc raw/processed.

## Greedy/Monte-Carlo (Milestone 4B)

```python
from src.algorithms import (
    estimate_greedy_cost, select_greedy, select_candidate_restricted_greedy,
)

# Full Greedy: chỉ nên bắt đầu với graph nhỏ sau khi xem preflight cost.
cost = estimate_greedy_cost(len(graph) - len(set(R)), k=2, number_of_simulations=20)
print(cost.evaluation_count, cost.cic_simulation_count)
result = select_greedy(
    graph, R, k=2, propagation_probability=0.05, number_of_simulations=20,
    base_random_seed=100000, tie_breaking="protector-priority",
)
print(result.protector_nodes, result.selection_order, result.final_mean_rumor_count)
print(result.evaluation_count, result.runtime_seconds, result.evaluation_runtime_seconds)
```

Full Greedy bắt đầu P rỗng, tại mỗi bước đánh giá **mọi** v ngoài P/R bằng
`evaluate_cic(P union {v})`, chọn mean rumor nhỏ nhất. Bằng mean chính xác thì
label chuẩn hóa tăng dần quyết định. Tiếp tục đến đúng k, kể cả khi score hữu
hạn mẫu không giảm. Không CELF/lazy pruning, không giả định submodularity và
không ngầm lọc candidates theo degree. `Full` không nghĩa là tìm optimum trên
mọi tổ hợp k node. API không thay IC/CIC/Monte Carlo, graph hoặc seed input.

Kết quả frozen có P cuối, selection_order, candidate pool, steps, evaluation_count,
cic_simulation_count, total runtime và tổng thời gian evaluator. Mỗi step lưu
P mới, selected node, mean/std và compact scores của mọi trial. Không giữ raw
node sets/layers hoặc S observations của tất cả trials. Timing được loại khỏi
so sánh giá trị để kiểm tra replay. k=0 trả P rỗng, 0 calls và final score=None;
muốn biết score P rỗng cần gọi evaluator riêng và tính thêm chi phí đó.

Mọi trial/bước dùng cùng base seed; CIC simulation i vẫn dùng base+i. Không bảo
đảm common edge outcomes giữa P khác nhau. Score trong lịch sử đã được dùng để
chọn P, có nhiễu và selection bias; không coi đó là chất lượng hold-out chính thức.

Biến thể giới hạn phải gọi API riêng và nhận pool rõ ràng:

```python
pool = select_degree(graph, R, 10)
limited = select_candidate_restricted_greedy(
    graph, R, 2, 0.05, 20, candidate_nodes=pool,
    base_random_seed=100000, tie_breaking="protector-priority",
)
assert limited.algorithm == "candidate-restricted-greedy"
```

Candidate-Restricted Greedy xét toàn bộ node còn lại **trong pool**, không xóa
node/cạnh graph. Pool chứa R hoặc node không tồn tại gây lỗi; k không vượt số
node phân biệt trong pool. Pool bằng toàn bộ candidates cho cùng lịch sử Full,
nhưng tên biến thể vẫn được giữ rõ ràng.

Với m candidates, **E=k*m-k*(k-1)/2** evaluator calls, **E*S** CIC simulations.
Full: m=n-|R|; restricted: m=|pool|. Không có call khởi đầu/kết thúc phụ.
Email-Eu-core, R=[0], k=5, S=500 cần 5.010 calls và 2.505.000 simulations cho
Full Greedy. Đây là công thức số lượng, không phải một runtime đã đo.

Pilot nhỏ, chỉ kiểm tra thực thi:

```sh
python -B -m experiments.pilot_greedy
```

Full chỉ chạy trên ba graph tính tay. Email dùng Candidate-Restricted với config
`experiments/configs/greedy_email.json`: top-10 out-degree, R=[0], k=2, p=0.05,
S=20, base=100000. Mỗi search 19 calls/380 simulations; một search replay được
đếm riêng (email tổng 38 calls/760 simulations). Full email cùng k/S cần 2.007
calls/40.140 simulations và **không được thực thi**. S=20 thấp hơn S_opt/S_eval
của 4A vì chỉ dùng cho smoke pilot. Không benchmark Facebook/Wiki-Vote.

Đầu ra `results/pilots/greedy/`: config.json, preflight.json (ghi trước search),
report.json, steps.csv và trials.csv. Lưu riêng chi phí dựng pool, runtime search,
runtime evaluator, replay và calls/simulations của các graph tính tay.
**Toàn bộ là pilot, không dùng làm kết quả chính thức.**

## Genetic Algorithm (Milestone 5)

```python
from src.algorithms import select_genetic_algorithm

ga = select_genetic_algorithm(
    graph, rumor_seeds=[0], k=2, propagation_probability=0.05,
    number_of_simulations=20,  # S_opt, chỉ là smoke budget trong ví dụ
    population_size=8, max_generations=5,
    crossover_rate=0.8, mutation_rate=0.3,
    tournament_size=3, elitism_count=1,
    random_seed=2026, fitness_base_random_seed=100000,
    tie_breaking="protector-priority", cache_fitness=True,
)
print(ga.best_protector_nodes, ga.best_estimated_fitness)
print(ga.generations_run, ga.evaluation_count, ga.cic_simulation_count)

# Đánh giá độc lập SAU khi đã chọn P; không đưa score này ngược vào GA.
independent = evaluate_cic(
    graph, [0], ga.best_protector_nodes, 0.05, 100,
    base_random_seed=ga.seeds.independent_evaluation_base_random_seed,
    tie_breaking="protector-priority",
)
```

Cá thể là frozenset đúng k node hợp lệ trong toàn bộ V ngoài R, không dùng
candidate restriction. Quần thể luôn có N slot; genotype giữa các slot có thể
trùng nhau để hỗ trợ k=0/k=m hoặc không gian nghiệm nhỏ. Khởi tạo mỗi cá thể
bằng random sampling không hoàn lại. Invariants được kiểm tra trong từng operator
và sau mỗi generation. Node labels dùng hợp đồng chuẩn hóa của CIC.

- Tournament lấy các slot không hoàn lại; fitness thấp nhất thắng, tie theo
  genotype chuẩn hóa rồi index. Một cặp parent được chọn cho mỗi child.
- Set Crossover giữ giao parent, chọn phần còn thiếu từ hiệu đối xứng; nếu không
  crossover thì clone parent thứ nhất. Rate là xác suất trên mỗi child.
- Mutation thay một node bằng một node hợp lệ ngoài cá thể khi có thể; no-op
  ở k=0 hoặc k=m. Repair loại gene sai/trùng và cắt/bù về đúng k bằng RNG riêng.
- Top E slot là elite, mang nguyên genotype/fitness sang generation sau, không
  bị các toán tử thay đổi. Không yêu cầu các elite là genotype khác nhau.
- Generation 0 là initialization; max_generations=G thực hiện đúng G transitions,
  ghi G+1 records. Không early stop. G=0 chỉ đánh giá initial population.
- Log cả generation-best và best-so-far. Khi E=0 quần thể có thể kém đi nhưng
  kết quả trả về vẫn là best-ever. Tie fitness dùng genotype chuẩn hóa.

Chính sách fitness đã được người dùng xác nhận: **fixed seeds + local cache**.
Mỗi cá thể dùng evaluate_cic với cùng graph/R/p/S_opt/tie/base. Cache key là
frozenset, không chia sẻ giữa các lần gọi. Elite giữ nguyên fitness. Cache hits
không tạo thêm thông tin độc lập hoặc thêm CIC simulations. cache_fitness=False
gọi lại evaluator cho mọi non-elite request bằng cùng lịch seed; không resample
objective, không đánh giá lại elite. Bật/tắt cache không đổi evolution khi giữ
mọi cấu hình/seed, chỉ đổi chi phí và counters.

random_seed là integer không âm. Operators RNG dùng 64-bit đầu SHA-256 của
`misinformation-ga-v1:operators:{random_seed}`. Base fitness mặc định được suy
ra với domain `fitness`; có thể truyền fitness_base_random_seed để dùng lịch
seed rõ ràng. Simulation i dùng base+i; seed evaluation độc lập bắt đầu base+
S_opt, không giao khoảng seed tối ưu. Không dùng RNG toàn cục; thứ tự graph/
seed input hoặc PYTHONHASHSEED không đổi evolution. Lịch seed chung vẫn không
bảo đảm common edge outcomes giữa các P, theo semantics evaluator hiện tại.

best_estimated_fitness là objective mẫu đã dùng để tối ưu, có thể overfit, **không
phải kết quả thực nghiệm cuối cùng**. Independent evaluation phải gọi riêng
trên seed mới; tăng G/cache hits không làm tăng S của một fitness đã lưu.

Result lưu parameters/seeds, best P/fitness, history với population snapshots,
fitness evaluation ledger, actual MC calls/CIC count, request/cache-hit/elite-
reuse counters, evaluator runtime và optimization runtime. Tất cả timing được
loại khỏi value equality. Không giữ S raw observations của mọi fitness trong GA.
History snapshots có chi phí bộ nhớ O(G*N*k).

Không cache: N+G*(N-E) calls. Có cache: tối đa min(cận trên này, C(m,k)) calls.
Chỉ actual calls được nhân S_opt thành CIC count. k=0 vẫn trả best fitness thật
cho P rỗng: cache chỉ cần một evaluator call, còn population/history vẫn đủ N/G.

Chạy smoke pilots, không phải experiment runner:

```sh
python -B -m experiments.pilot_genetic_algorithm
```

Ba graph tổng hợp nhỏ có oracle exhaustive p=1 chạy **sau** GA để kiểm chứng,
không dùng để seed/chọn cá thể. Email dùng config
`experiments/configs/ga_pilot_email.json`: N=8, G=5, k=2, S_opt=20, S_eval=100,
rates 0.8/0.3, tournament=3, elitism=1, random_seed=2026, fitness base=100000.
Tối ưu tối đa 43 calls/860 CIC simulations trước cache. Seed held-out từ 100020.
Các mức S nhẹ hơn khuyến nghị độ chính xác 4A, chỉ kiểm tra khả năng thực thi.

Đầu ra `results/pilots/genetic_algorithm/`: config, preflight từng case,
convergence.png, report.json tổng và thư mục mỗi case chứa report.json,
convergence.csv, convergence.json, fitness_evaluations.csv. JSON tách rõ
optimization/independent_evaluation; replay/oracle/hold-out có counters riêng.
**Toàn bộ là pilot, chưa so sánh chất lượng GA với baseline và không benchmark
Facebook/Wiki-Vote. Không triển khai experiment runner ở Milestone 5.**

## Experiment Runner (Milestone 6)

```python
from src.experiments import load_experiment_config, run_experiment

config = load_experiment_config("experiments/configs/runner_smoke_email.json")
result = run_experiment(config)
print(result.output_directory, result.rows)
```

```sh
python -B main.py experiment --config experiments/configs/runner_smoke_email.json
python -B -m experiments.run_experiment --config experiments/configs/runner_smoke_email.json --run-index 1 --output-dir results/another_root
```

CLI chạy một independent run index của một cấu hình; nhiều index được gọi riêng.
Runner hỗ trợ JSON, không thêm dependency. Đường dẫn tương đối tính từ thư mục
chứa config. API `ExperimentConfig.from_dict(values, base_directory=...)` cho
cấu hình trong Python. Dataset mặc định đọc `data/processed/<dataset>`; custom
fixture cần `processed_directory` và label metadata khớp `dataset`.

Mỗi cấu hình nhận `algorithm` hoặc danh sách `algorithms`: `no_intervention`,
`random`, `degree`, `pagerank`, `full_greedy`, `candidate_restricted_greedy`,
`genetic_algorithm`. Runner luôn thêm No Intervention đầu tiên. Bắt buộc khai
báo dataset, R/policy, k, p, tie rule, S_opt, S_eval, random_seed,
independent_run_index, output_directory. Không có mặc định nghiên cứu cho S hoặc
GA. PageRank phải khai báo alpha/tol/max_iter; GA phải khai báo đủ N, G, rates,
tournament_size, elitism_count, cache_fitness. Config không hợp lệ/unknown keys
bị từ chối. File smoke có giá trị nhẹ **chỉ dành cho kiểm tra thực thi**.

R khai báo bằng `rumor_seeds: [0]` hoặc
`rumor_seed_policy: {"method": "random", "count": 1, "scope": "fixed"}`.
`fixed` giữ R qua các independent index cùng master seed và graph; `per_run`
sinh R theo index. Mọi phương pháp trong một run dùng đúng một R đã resolve,
cùng k/p/tie/S_eval. Khi nghiên cứu độ ổn định thuật toán trên cùng bài toán,
giữ R cố định; không gộp runs có R khác mà coi là chỉ khác RNG thuật toán.
No Intervention dùng P rỗng, vẫn ghi k của cấu hình so sánh.

Quy trình: nạp graph/check checksum → resolve R/kiểm tra budget → preflight mọi
optimizer → chọn P của **tất cả** phương pháp → independent final evaluation →
ghi kết quả. Chỉ gọi lại các API đã kiểm chứng, không thay đổi semantics hay
preprocess dataset. Graph được freeze và so sánh attributes/topology trước/sau;
checksum nguồn processed được đối chiếu lại.

Seed plan version `cantor-block-v1/sha256-phases-v1`: với master `a`, run index
`b`, `q=(a+b)*(a+b+1)//2+b`, `start=q*seed_block_size`. Nửa đầu block dành cho
optimization (`start+i`, i<S_opt); nửa sau final (`start+width//2+i`, i<S_eval).
Width chẵn, mỗi S không vượt nửa width; mặc định kỹ thuật width=1,000,000 có thể
đổi. **Giữ nguyên width trong cùng study** để các master/index có block tách
biệt. Cùng config/order khác vẫn dùng cùng seed schedule. Mọi method/control
dùng cùng final schedule, tách khỏi optimization. Lịch seed chung không bảo đảm
cùng random outcomes trên từng cạnh theo semantics CIC hiện tại.

Rumor sampling, Random Selection và RNG đầu vào GA dùng SHA-256
`experiment-runner-v1:{master}:{index}:{domain}` lấy 8 bytes đầu, domain tương
ứng `rumor`, `random-selection`, `ga`. Rumor `fixed` dùng index=0. GA tiếp tục
suy ra RNG operators theo chính sách Milestone 5; Greedy/GA fitness dùng base
optimization của runner, cache GA cục bộ/elite không đổi. Base hold-out gợi ý
trong kết quả GA là của API cũ; **runner dùng final block của chính runner**,
được ghi rõ trong metadata. Không feedback final score vào chọn P.

Full Greedy trên m=|V\\R| xét `k*m-k*(k-1)//2` evaluator calls, nhân S_opt thành
số CIC simulations. Candidate-Restricted dùng m bằng pool size, cấu hình pool
`{"method":"degree","size":...}` hoặc `{"method":"explicit","nodes":[...]}`.
GA cận trên không cache `N+G*(N-E)`, có cache chặn thêm `C(m,k)`. Mọi optimizer
cần `limits.max_optimization_evaluations/max_optimization_cic_simulations`;
Full còn cần `max_full_greedy_evaluations/max_full_greedy_cic_simulations`.
Giới hạn áp dụng **từng phương pháp**. Vượt cận trên cấu hình thì cả run dừng
trước selection/evaluation, không tự đổi sang restricted. Preflight chỉ dự tính
số calls/simulations; runtime để null tới khi đo, không suy ra thời gian từ n.

Output riêng, không ghi đè:

```text
<output_directory>/<dataset>/run_<index>_<config-hash>/
  config.json                # cấu hình normalized đầy đủ
  results.csv                # mỗi phương pháp một hàng, chứa cả R và P
  metadata.json              # seed intervals, Python/libs/OS/hardware/Git/source hashes
  summary.json               # final metrics, actual counts và timings
  preflight.json             # cận trên công việc, không phải runtime đo được
  selection_details.json     # kết quả tối ưu, trace và seeds nguyên API cũ
  convergence.csv            # GA: generation 0 tới G
  raw_observations.csv       # tùy chọn, chỉ final/control
```

Thư mục đích được publish sau khi toàn bộ run thành công; lỗi không để lại run
dở. Hash cấu hình không phụ thuộc output root hoặc tùy chọn raw observations.
Chạy lại dùng output root khác để tránh ghi đè. Các file tổng hợp không giữ raw
fitness MC; `save_raw_observations=true` lưu final/control với simulation seeds
để replay. GA selection details vẫn có population/history/counters nguyên API;
chi phí bộ nhớ history phụ thuộc N/G/k.

Metrics dùng independent final results: rumor mean, population std (ddof=0),
sample std, SE=sample std/sqrt(S_eval), protector/inactive means, min/max,
reduction=(control_mean-method_mean)/control_mean và phần trăm. S_eval=1 có SE
và sample std=null; control mean=0 có relative reduction=null; không cắt kết
quả giảm âm do sai số MC. Optimization score lưu cột riêng. Control được đánh
giá một lần; mọi P rỗng (k=0) tham chiếu lại cùng evaluation ID, không đếm thêm
calls/runtime. GA k=0 vẫn tính fitness theo API cũ.

Timing tách loading (bao gồm validation), preprocessing=0, selection/optimization
(gồm MC fitness và dựng candidate pool), final evaluation, primary artifact
writes và orchestration overhead. Degree/Random/PageRank chỉ đo selection;
Greedy/GA đo toàn bộ tối ưu; candidate pool time được ghi riêng bên trong
selection. Final time lấy evaluator runtime và control chỉ tính một lần. Total
đo từ vào `run_experiment` đến ghi xong primary artifacts, loại config parsing
và vài bước ghi metadata/summary/rename cuối; phạm vi này ghi trong metadata.
Không dùng runtime pilot làm benchmark hoặc coi timing là giá trị tái lập.

Kiểm chứng và kết quả smoke xem [docs/MILESTONE_6_SMOKE.md](docs/MILESTONE_6_SMOKE.md).
Trước main experiments còn phải chốt R/policy, k, p, S_opt/S_eval, GA parameters,
candidate pools/limits, số independent runs và study seed schedule. Chưa chạy
parameter study hoặc thực nghiệm chính thức trên ba bộ dữ liệu.

## Pilot Protocol Validation

Đã kiểm chứng nhẹ cả ba datasets, k=5, rumor count=1, p=0.01/0.05,
S_opt=20/S_eval=200, GA N=10/G=10, 3 independent runs mỗi dataset–p. R được
lưu trước mô phỏng, không resample theo outcomes. 3 smokes và 18 pilots thành
công; Full Greedy skipped rõ lý do cost limits, sáu phương pháp còn lại chạy
cùng protocol. Chưa main experiments hoặc parameter study.

Runner thêm `skipped_algorithms: {"full_greedy": "reason"}` cho method không
được chọn; không được khai báo skipped cho method đang chọn. `method_status.csv`
và JSON có đủ 7 statuses; `results.csv` chỉ có số đo đã thực thi. Orchestration
runtime có breakdown riêng trong metadata, là phần con của tổng overhead.

```sh
python -B -m experiments.pilot_protocol_validation --output-dir results/pilot_protocol_validation_repeat
```

Config/resource caps nằm trong `experiments/configs/pilot_protocol_validation.json`.
Chương trình preflight trước, smoke tất cả datasets trước pilot, chạy tuần tự,
có hard timeout và ghi skipped/failed/timed_out khác nhau; partial work không
được báo giả là zero. Independent run index ánh xạ riêng mỗi matrix cell;
replicate index vẫn 0–2. Dữ liệu/semantics thuật toán giữ nguyên.

Xem [PILOT_PROTOCOL_VALIDATION.md](PILOT_PROTOCOL_VALIDATION.md) và compact
CSV/JSON trong `docs/pilot_protocol_validation/`. Raw observations/per-case
artifacts nằm trong results. S=20/200 khả thi về compute, chưa được chốt cho
main experiments: p=0.05 còn variance lớn; Wiki R đã chọn chỉ reachable 2 nodes.

## Pilot 2 – Calibration

[PILOT_2_CALIBRATION.md](PILOT_2_CALIBRATION.md) ghi kết quả đo, ngoại suy và
bảng protocol Chương 3 dạng draft. Compact CSV/JSON/figures ở
`docs/pilot_2_calibration/`; raw/traces/logs ở `results/pilot_2_calibration/`.

Đã tính reachable cho mọi node, giữ empty strata và low/legacy scenarios;
scan No Intervention với 11 R × 4 p × 2 batches, sau đó hiệu chỉnh MC trên
các reference R/p được chọn chỉ từ control. Đã chạy 16 optimization comparisons
và 3 smokes, 2 independent accuracy batches tới S_eval=2500 trên mỗi dataset.
Facebook S_opt250 skipped do projected runtime; Wiki chỉ có reference S_opt100.
250.216 CIC simulations, 361 tests pass; core/runner/data/dependencies giữ nguyên.

```sh
python -B -m experiments.pilot_2_calibration --output-dir results/pilot_2_repeat
python -B -m experiments.analyze_pilot_2 --root results/pilot_2_repeat
```

Có phase CLI riêng để không tự rerun một đợt đã thực thi. Config pilot/resource
limits nằm trong `experiments/configs/pilot_2_calibration.json`. Main proposal
JSON là tài liệu dự kiến, không phải config thực thi đã xác nhận. Chưa chạy
main experiments/Milestone 7. Không kết luận thuật toán thắng từ calibration.

## Experimental Protocol v1 và Milestone 7 pilot

[EXPERIMENT_PROTOCOL_V1.md](EXPERIMENT_PROTOCOL_V1.md) cố định reference setup
và xuất các bảng để đối chiếu mục 3.3/3.5. Specification JSON nằm trong
`experiments/configs/experiment_protocol_v1.json`; tables/preflight ở
`docs/experiment_protocol_v1/`. Đây là reference, không phải tham số tối ưu.

OFAT population/generations/crossover/mutation có 12 panel rows, 9 unique
profiles, shared physical baseline. Full design 270 GA runs/7,3 triệu CIC vượt
budget; reduced screen 45 runs/1,026 triệu CIC fit dự tính nhưng chưa chạy.
Chỉ bounded pilot N10/N20 trên R926/R1210 đã chạy: 8/8 runs, 154.200 CIC,
280,701 s. Không full sweep hoặc main experiments. 379 tests pass, old core/
runner/data/dependencies không đổi. Không chọn winner từ hai pilot repeats.

```sh
python -B -m experiments.design_protocol_v1 --output-dir docs/protocol_v1_design_repeat
python -B -m experiments.pilot_milestone_7 --output-dir results/milestone_7_pilot_v1_repeat
```

Pilot CLI kiểm tra protocol/manifest/schedule/evidence đã export và chỉ dùng
frozen pilot schedule. Nó chốt mọi P trước final/control, lưu hai independent
final batches mỗi P và pooled statistics có sample size rõ ràng. Conditional
MC uncertainty và variance giữa independent GA runs được báo riêng. Không có
dispatcher tự chạy full/reduced design khi thấy fit budget.

## Milestone 7 – Reduced Screen preflight

[MILESTONE_7_REDUCED_SCREEN.md](MILESTONE_7_REDUCED_SCREEN.md) giải thích rõ
45 runs v1 là tổng 5 profiles × 3 scenarios × 3 repeats. Yêu cầu 5 repeats
mới thành 75 runs, 25 mỗi dataset/scenario. Ma trận đầy đủ và seeds ở
`docs/milestone_7_reduced_screen/`; không sửa frozen Protocol-v1 JSON.

Preflight dự tính 10.985,164 s vượt cap10.800 s; đã dừng trước execution theo
yêu cầu người dùng. 75 planned runs explicit skipped, quality/CI/runtime=null,
không tạo experimental plots hoặc chọn winner từ dữ liệu không tồn tại.
Không tăng budget/giảm repeats tự động, không chạy full design/main. 389 tests
pass; data và các lõi giữ nguyên checksum.

```sh
python -B -m experiments.preflight_reduced_screen --output-dir docs/reduced_screen_preflight_repeat
```

Đây là preflight-only CLI. Screen seed namespace tách pilot/main; reserved
validation scenarios được giữ nguyên. Các phương án tiếp tục trong báo cáo
chỉ là đề xuất, chưa được thực thi.

## Milestone 7 – Reduced Screen V2

[MILESTONE_7_REDUCED_SCREEN_V2.md](MILESTONE_7_REDUCED_SCREEN_V2.md) ghi thiết kế
được user điều chỉnh: 9 profiles × email R926 ×5 repeats =45/45 GA runs thành
công. Bốn panel OFAT có đủ ba mức, reference dùng chung, giữ k5/p.03/S_opt100/
S_eval6000 mỗi batch/B2. Không so sánh khác dataset để suy ra hiệu ứng tham số.

Preflight gồm safety/overhead=2.898,246 s <10.800 s; thực đo khoảng1.116,95 s,
3.243 calls/914.300 CIC. Checkpoint lưu từng run, resume không lặp lại run đã
hoàn tất hoặc reset budget. CSV/JSON, convergence và plots ở
`docs/milestone_7_reduced_screen_v2/`; raw ở `results/milestone_7_reduced_screen_v2/`.
415 tests pass, 44 protected file hashes/14 data files không đổi. CI hiệu chỉnh
cả 8 contrasts còn chứa0; không chốt GA tối ưu hoặc chạy Full Design/main.

```sh
python -B -m experiments.reduced_screen_v2 --phase preflight
python -B -u -m experiments.reduced_screen_v2 --phase run
python -B -m experiments.analyze_reduced_screen_v2
```

Code mới: `experiments/reduced_screen_v2.py`,
`experiments/analyze_reduced_screen_v2.py`, request JSON V2 và hai test modules
`tests/test_reduced_screen_v2*.py`. Các semantics core và Protocol-v1 JSON giữ nguyên.

## Cross-Scenario GA Configuration Confirmation

[CROSS_SCENARIO_GA_CONFIRMATION.md](CROSS_SCENARIO_GA_CONFIRMATION.md):
27/27 GA runs trên email R858,Facebook R1555,Wiki R2110; N10/N20/N40,3 repeats,
các điều kiện còn lại v1 giữ nguyên. Preflight gồm safety/overhead6.359,888s
<10.800s. Thực đo3.362 calls/593.000CIC,active2.163,03s,peakRSS177,8MiB <2GiB.
443 tests pass,44 protected file hashes/14 data files không đổi.

Các contrasts được phân tích riêng dataset; cả6 family CIs chứa0. Giữ reference
như practical candidate, không chứng minh equivalence hoặc optimality. Các R
confirmation không còn blind main holdouts; topology-only main reservations
và seed slots riêng ở docs/cross_scenario_ga_confirmation. Chưa chốt/chạy main.

```sh
python -B -m experiments.cross_scenario_ga_confirmation --phase preflight
python -B -u -m experiments.cross_scenario_ga_confirmation --phase run
python -B -m experiments.analyze_cross_scenario_confirmation
```

Runner checkpoint/resume theo fingerprint, giám sát RSS bằng resource/heartbeat
và timeout, gọi lại V2 GA/evaluator bridge. Raw ở results/cross_scenario_ga_confirmation
(gitignored); compact CSV/JSON/per-run histories và figures ở docs cùng tên.
New code: `experiments/cross_scenario_ga_confirmation.py`,
`experiments/analyze_cross_scenario_confirmation.py`, config JSON và
`tests/test_cross_scenario_confirmation.py`, `tests/test_cross_scenario_analysis.py`.

## Main Experiments — Design Freeze & Preflight

[MAIN_EXPERIMENTS_PROTOCOL.md](MAIN_EXPERIMENTS_PROTOCOL.md) khóa GA reference
theo user; giữ6 main R topology-only đã reserve. Proposal5 repeats ×6R ×6methods
=180 primary rows +30 Full Greedy skipped. Upper4.560 evaluator calls/1.740.000
CIC, runtime proxy có safety/overhead11.036,921s >10.800s: **stopped_at_preflight**.
Không tự hạ repeats hoặc chạy main. Các phương án3/4/10 chỉ là arithmetic
proposals cần xác nhận. Exact source rates/topology/matrix/seed schedules và
unconfirmed conditions ở `docs/main_experiments_protocol/`.

461 tests pass;64 existing protected files, gồm14 data files, checksum giữ
nguyên. Statistics prespecify paired comparisons/family45/equal-weight scenarios
trong từng dataset; không pool quality giữa graph hoặc suy equivalence từ CI0.
Chỉ có planning CLI, chưa main all-methods two-batch execution adapter:

```sh
python -B -m experiments.design_main_experiments --output-dir docs/main_design_repeat
```

New files: `experiments/design_main_experiments.py`,
`experiments/configs/main_experiments_protocol.json`,
`tests/test_main_experiments_design.py`. Config này là design specification,
không là executable one-batch runner config; main execution/design flags=false.

## Main Experiments V2: 4 independent runs

[Protocol V2](MAIN_EXPERIMENTS_PROTOCOL_V2.md) ghi nhận lựa chọn 4 runs/scenario
của người dùng, giữ nguyên protocol 5 runs và toàn bộ thiết lập khoa học.
Ma trận gồm 6 scenarios × 4 runs × 6 methods = 144 primary result rows;
24 Full Greedy rows được ghi skipped riêng vì vượt giới hạn chi phí.
Preflight: tối đa 3.648 evaluator calls/1.392.000 CIC, runtime projection
8.889,537 s trong ngân sách 10.800 s. Đã hoàn thành 144/144 primary rows,
0 failed; actual 2.058 evaluator calls/1.233.000 CIC trong 4.436,312 s.
493/493 tests pass; checksum 67 protected files/14 data files và topology giữ
nguyên. [MAIN_EXPERIMENTS_RESULTS.md](MAIN_EXPERIMENTS_RESULTS.md) báo cáo
9/45 effects phân biệt được và 36 chưa đủ bằng chứng, không suy global winner.
Resume không tạo thêm worker/CIC; tái tổng hợp raw counts cho numeric outputs
identical, không chạy lại toàn bộ main. Giữ nguyên 19 reduction âm.

Runner gọi các implementation đã kiểm chứng, khóa 144 tập P trước khi bắt đầu
288 final batches. Mỗi selection/batch có atomic checkpoint, raw counts và
checksum. Resume kiểm tra code/config/data/seed/P rồi bỏ qua unit đã hoàn tất;
chỉ chạy một tiến trình điều phối trên cùng output directory.

```sh
python -B -m experiments.main_experiments --phase run
python -B -m experiments.analyze_main_experiments
```

Lệnh đầu chỉ thực thi hoặc resume ma trận V2 đã được xác nhận. Lệnh phân tích
chỉ đọc các observations đã lưu, không chạy thêm Monte Carlo. CSV/JSON, 15
biểu đồ (PNG/SVG), uncertainty, runtime và audit xuất riêng ở
`docs/main_experiments_results/`; checkpoint/raw ở `results/main_experiments_v2/`
(gitignored). Protocol V2 và seed audit ở `docs/main_experiments_protocol_v2/`.
Không dùng training fitness làm final quality, không clip reduction âm,
không tuning tiếp hoặc thêm thí nghiệm ngoài ma trận.

## Tests

```sh
python -B -m unittest discover -s tests -v
```

Unit tests dùng fixtures nhỏ và thư mục tạm. Integration tests đọc cả ba dataset
thật, xuất vào thư mục tạm, đối chiếu chính xác topology và bytes của nodes/edges
với processed datasets trong repository, kiểm tra CLI với đường dẫn có khoảng
trắng/Unicode từ working directory khác, và so sánh SHA-256 của
toàn bộ tệp trong `data/raw/` trước/sau pipeline. Cần có raw datasets để chạy đủ tests.

Tests IC kiểm tra `p=0/1`, hướng cạnh, từng bước đồng bộ, isolated nodes, seeds và
xác suất không hợp lệ, tái lập, RNG riêng, không sửa graph, không thử lại cạnh
thất bại và không kích hoạt lặp. Integration tests chạy trực tiếp trên cả ba
processed datasets; tại `p=1`, đối chiếu tập active với reachability của NetworkX.

Tests CIC kiểm tra hai cascade riêng/đồng thời, thời điểm đến, hai tie rules,
trạng thái vĩnh viễn, `p=0/1`, hướng cạnh, seeds/xác suất không hợp lệ, không thử
lại cạnh thất bại và conservation của partition/layers. Tái lập được kiểm tra
khi đảo thứ tự graph/seeds và bằng hai tiến trình có `PYTHONHASHSEED` khác nhau.
Integration tests chạy cả ba processed datasets; tại `p=1`, đối chiếu với
khoảng cách đường đi ngắn nhất, và kiểm tra cascade đơn khớp IC trên email data.

Tests Monte Carlo đối chiếu từng simulation với CIC trực tiếp, kiểm tra công thức
tổng hợp bằng các quan sát biết trước, seed schedule, replay, S=1, p=0/1, input
validation, RNG/graph không đổi và protector configurations trên chain tính tay.
Integration tests đọc cả ba processed datasets và replay các quan sát email.

Tests baseline kiểm tra đủ k, loại R, sparse IDs, tie-break, out-degree,
PageRank incoming/full graph, không sửa input và tích hợp evaluator trên ba
datasets. Tests stability kiểm tra seed blocks độc lập, công thức SE/pooled
variance, CSV replay và trường hợp không đạt ngưỡng đề xuất S.

Tests Greedy kiểm tra Full trên graph nhỏ tính tay, oracle exhaustive từng bước,
đủ k, k=0, pool/budget không hợp lệ, không sửa input, reproducibility, mọi trial
đều qua evaluator, và Candidate-Restricted được tách tên/không đổi topology.

Tests GA kiểm tra từng toán tử, k=0/k=m, sparse/mixed labels, đúng population size,
elite genotype/fitness preservation, stopping G transitions, cache/re-evaluation,
seed blocks độc lập, RNG/graph không đổi, replay qua các Python hash seeds và
các bài toán nhỏ tính tay. Test cache toggle xác nhận evolution không đổi.

Tests Runner kiểm tra cấu hình/giới hạn, tất cả bảy phương pháp trên processed
fixtures, fairness R/k/p/tie/final seeds, preflight trước bất kỳ selection nào,
selection hoàn tất trước final, replay/order independence, k=0, null metrics,
bytes/topology/attributes, atomic output, CSV/JSON/convergence và CLI Unicode.
Tests Protocol bổ sung explicit skipped/empty-P status, runtime accounting,
rumor policy trên sparse IDs, reachability, budget planning, timeout bookkeeping,
descriptive spread/precision metrics và không tạo kết quả giả khi skipped.

## Cấu trúc mã nguồn

- `src/data/specs.py`: dataset registry và preprocessing config.
- `src/data/loader.py`: parser plain/gzip và fingerprint của nguồn.
- `src/data/validation.py`: graph statistics và các invariant về topology.
- `src/data/preprocess.py`: bỏ self-loops theo cấu hình, giữ nguyên tập nodes.
- `src/data/storage.py`: CSV/JSON, bảo vệ raw và đọc lại processed graph.
- `src/data/pipeline.py`: điều phối và kiểm chứng round-trip.
- `main.py`: command line.
- `tests/test_dataset_*.py`: unit và integration tests.
- `src/diffusion/ic.py`: IC simulator và kết quả có activation layers.
- `tests/test_ic.py`: unit tests IC và tích hợp với processed datasets.
- `experiments/pilot_ic.py`: ví dụ tính tay và pilot kiểm tra triển khai IC.
- `src/diffusion/cic.py`: CIC simulator, explicit tie rules và activation layers.
- `tests/test_cic.py`: unit tests CIC và tích hợp với processed datasets.
- `experiments/pilot_cic.py`: ví dụ tính tay và pilot kiểm tra triển khai CIC.
- `src/evaluation/monte_carlo.py`: evaluator CIC và thống kê/raw observations.
- `tests/test_monte_carlo.py`: unit và integration tests evaluator.
- `experiments/pilot_monte_carlo.py`: pilot Monte Carlo kiểm tra hiệu năng/replay.
- `src/algorithms/baselines.py`: ba baseline chọn protector nodes.
- `tests/test_baselines.py`, `tests/test_mc_stability.py`: kiểm thử Milestone 4A.
- `experiments/pilot_mc_stability.py`: stability pilot và xuất CSV/JSON/figure.
- `experiments/configs/mc_stability_email.json`: cấu hình pilot cố định.
- `src/algorithms/greedy.py`: Full Greedy, Candidate-Restricted Greedy và work counts.
- `tests/test_greedy.py`: kiểm thử đầy đủ trên graph nhỏ.
- `experiments/pilot_greedy.py`, `experiments/configs/greedy_email.json`: smoke pilot 4B.
- `src/algorithms/ga_operators.py`, `src/algorithms/genetic_algorithm.py`: GA/fitness policy.
- `tests/test_ga_operators.py`, `tests/test_genetic_algorithm.py`: kiểm thử Milestone 5.
- `experiments/pilot_genetic_algorithm.py`, `experiments/configs/ga_pilot_email.json`: GA smoke pilots.
- `src/experiments/`: cấu hình, seed plan, metrics, provenance và unified runner.
- `experiments/run_experiment.py`: CLI cấu hình một independent run.
- `experiments/configs/runner_smoke_email.json`: cấu hình kiểm tra nhẹ Milestone 6.
- `tests/test_experiment_*.py`, `tests/experiment_helpers.py`: unit/integration runner.
