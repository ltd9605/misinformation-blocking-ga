# Ngăn chặn lan truyền thông tin sai lệch bằng thuật toán di truyền

Đồ án Python mô phỏng lan truyền thông tin trên đồ thị bằng IC/CIC và dùng
Genetic Algorithm để chọn tập nút bảo vệ có kích thước k. Các phương pháp đối
chứng gồm Random, Degree, PageRank và Greedy/Monte Carlo.

Mã nguồn đã có pipeline dữ liệu, mô hình lan truyền, thuật toán, bộ chạy thực
nghiệm và kiểm thử. Báo cáo Main Experiments theo Protocol V2 nằm trong
[tài liệu kết quả](docs/reports/MAIN_EXPERIMENTS_RESULTS.md).

## Bắt đầu

Chạy các lệnh tại thư mục gốc dự án. Mã nguồn cần Python 3.11+; phiên bản Python
còn phải tương thích với các thư viện đã pin trong `requirements.txt`.
Chi tiết môi trường đã kiểm tra nằm trong [hướng dẫn kỹ thuật](docs/guides/TECHNICAL_GUIDE.md#môi-trường).

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
python main.py --help
```

Trong VS Code, chọn interpreter của `.venv`. Bộ dữ liệu SNAP raw/processed đã
có trong `data/`. Kiểm tra toàn bộ chương trình bằng:

```sh
python -B -m unittest discover -s tests -q
```

Để chạy một ví dụ nhỏ, xem [hướng dẫn chạy thủ công](docs/guides/HUONG_DAN_CHAY_THU_CONG.md).
Ví dụ này dùng đồ thị tổng hợp 9 nút, có cấu hình JSON và cách kiểm tra kết quả
bằng tay. Các số liệu từ ví dụ không phải kết quả thực nghiệm trên SNAP.

## Cấu trúc dự án

```text
.
├── main.py                  # CLI: dataset / experiment
├── requirements.txt         # Phiên bản thư viện
├── src/                     # Các thành phần dùng lại
│   ├── data/                # Đọc, kiểm tra, tiền xử lý và lưu đồ thị
│   ├── diffusion/           # IC và CIC
│   ├── evaluation/          # Ước lượng Monte Carlo
│   ├── algorithms/          # Baselines, Greedy và Genetic Algorithm
│   └── experiments/         # Cấu hình, seed, metrics và runner
├── experiments/             # Lệnh chạy pilot, thiết kế và phân tích
│   └── configs/             # Cấu hình JSON của từng thực nghiệm
├── tests/                   # Unit tests và integration tests
├── data/
│   ├── raw/                 # Dữ liệu SNAP gốc
│   └── processed/           # nodes.csv, edges.csv, metadata.json
├── docs/
│   ├── README.md            # Mục lục tài liệu và bảng số liệu
│   ├── guides/              # Cài đặt, API và hướng dẫn chạy
│   ├── planning/            # Bối cảnh dự án và kế hoạch
│   ├── protocols/           # Thiết kế và protocol thực nghiệm
│   ├── reports/             # Báo cáo pilot, khảo sát và Main Experiments
│   ├── reference/           # Phiên bản dùng trong phụ lục
│   └── <campaign>/          # CSV/JSON, biểu đồ và bằng chứng đã lưu
└── results/                 # Đầu ra cục bộ, raw observations và checkpoint
```

`src/experiments/` chứa logic dùng lại; `experiments/` chứa các lệnh điều phối.
Hai thư mục có vai trò riêng. `results/` được bỏ qua bởi Git; các bảng và biểu
đồ đã lưu trong `docs/<campaign>/` được quản lý phiên bản.

## Các lệnh thường dùng

| Công việc | Lệnh |
|---|---|
| Xem tùy chọn dataset | `python main.py dataset --help` |
| Tái tạo processed data của email | `python main.py dataset --name email-Eu-core` |
| Chạy một cấu hình | `python main.py experiment --config experiments/configs/runner_smoke_email.json` |
| Xem tùy chọn runner | `python -m experiments.run_experiment --help` |
| Chạy kiểm thử | `python -B -m unittest discover -s tests -q` |

Lệnh dataset ghi lại dữ liệu processed của dataset được chọn. Khi thử quy tắc
tiền xử lý khác, dùng `--output-dir` riêng và lưu cấu hình tương ứng.

## Tài liệu

- [Mục lục đầy đủ](docs/README.md).
- [Hướng dẫn kỹ thuật, mô hình và API](docs/guides/TECHNICAL_GUIDE.md).
- [Protocol Main V2](docs/protocols/MAIN_EXPERIMENTS_PROTOCOL_V2.md).
- [Kết quả Main Experiments](docs/reports/MAIN_EXPERIMENTS_RESULTS.md).
- [Phiên bản dùng trong phụ lục](docs/reference/THESIS_VERSION.md).
- [Ghi nhận việc sắp xếp tài liệu và checksum lịch sử](docs/reference/PROJECT_LAYOUT.md).
