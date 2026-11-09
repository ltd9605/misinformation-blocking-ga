# Misinformation blocking — Milestones 1–3

Dataset pipeline cho đồ án nghiên cứu ngăn chặn lan truyền thông tin sai lệch.
Phạm vi hiện tại: load, validate, preprocess, lưu/đọc graph và mô phỏng
Independent Cascade (IC), Competitive Independent Cascade (CIC). Các thuật toán
chọn nút chưa được triển khai.

## Môi trường

Đã kiểm tra trên macOS 15.3.1, Apple Silicon (`arm64`), Python 3.15.2 và
NetworkX 3.7. Các phiên bản dependency được ghi trong `requirements.txt`
(UTF-8); tests sử dụng `unittest` của Python. Mã hiện tại cần Python 3.11+
(`hashlib.file_digest`); các dependency đã pin còn phải hỗ trợ phiên bản Python
được chọn. Môi trường đã kiểm tra đầy đủ dùng Python 3.15.2.

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
