# Misinformation blocking — Milestone 1

Dataset pipeline cho đồ án nghiên cứu ngăn chặn lan truyền thông tin sai lệch.
Phạm vi hiện tại: load, validate, preprocess và lưu/đọc graph. IC, CIC và các
thuật toán chọn nút chưa được triển khai.

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

## Tests

```sh
python -B -m unittest discover -s tests -v
```

Unit tests dùng fixtures nhỏ và thư mục tạm. Integration tests đọc cả ba dataset
thật, xuất vào thư mục tạm, đối chiếu chính xác topology và bytes của nodes/edges
với processed datasets trong repository, kiểm tra CLI với đường dẫn có khoảng
trắng/Unicode từ working directory khác, và so sánh SHA-256 của
toàn bộ tệp trong `data/raw/` trước/sau pipeline. Cần có raw datasets để chạy đủ tests.

## Cấu trúc mã nguồn

- `src/data/specs.py`: dataset registry và preprocessing config.
- `src/data/loader.py`: parser plain/gzip và fingerprint của nguồn.
- `src/data/validation.py`: graph statistics và các invariant về topology.
- `src/data/preprocess.py`: bỏ self-loops theo cấu hình, giữ nguyên tập nodes.
- `src/data/storage.py`: CSV/JSON, bảo vệ raw và đọc lại processed graph.
- `src/data/pipeline.py`: điều phối và kiểm chứng round-trip.
- `main.py`: command line.
- `tests/test_dataset_*.py`: unit và integration tests.
