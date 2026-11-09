# PROJECT_CONTEXT.md

## 1. Đề tài nghiên cứu

Nghiên cứu thuật toán di truyền trong bài toán ngăn chặn lan truyền thông tin sai lệch trên mạng xã hội.

Mục tiêu của chương trình là mô phỏng quá trình lan truyền cạnh tranh giữa thông tin sai lệch và thông tin đính chính trên mạng xã hội, sau đó sử dụng Genetic Algorithm (GA) để tìm tập nút bảo vệ phù hợp.

## 2. Mô hình đồ thị

Mạng xã hội được biểu diễn dưới dạng đồ thị:

G = (V, E)

Trong đó:

- V là tập các nút.
- E là tập các cạnh.
- R là tập rumor seeds, tức các nút phát tán thông tin sai lệch ban đầu.
- P là tập protector seeds.
- k là ngân sách lựa chọn nút bảo vệ.
- |P| = k.

Tập protector seeds không được chứa các nút thuộc rumor seeds.

## 3. Mô hình lan truyền

Sử dụng Independent Cascade (IC) làm mô hình lan truyền cơ sở.

Sử dụng Competitive Independent Cascade (CIC) để mô phỏng sự cạnh tranh giữa:

- misinformation/rumor;
- corrective information.

Quá trình lan truyền có tính ngẫu nhiên.

Các quy tắc xử lý trường hợp rumor và corrective information cùng tiếp cận một nút phải được định nghĩa rõ và áp dụng thống nhất trong toàn bộ thực nghiệm.

Không tự ý lựa chọn một biến thể CIC khác nếu chưa được xác nhận.

### Quy tắc CIC đã chốt cho Milestone 3

- RUMOR và PROTECTOR dùng cùng một xác suất cạnh `p` trong `[0, 1]`.
- Rumor seeds R và protector seeds P phải tồn tại trong graph và không giao nhau;
  cả hai tập active tại lớp 0. Nút chưa thuộc cascade nào là inactive.
- Lan truyền đồng bộ: mỗi nút mới active chỉ thử truyền ở timestep tiếp theo,
  một lần trên mỗi cạnh tới neighbor chưa active. Cạnh directed chỉ đi theo
  hướng cạnh; cạnh undirected truyền được theo cả hai chiều. Mỗi lần thử hợp lệ
  là một phép thử Bernoulli độc lập với xác suất `p`.
- Trong mỗi timestep, thu thập riêng các đích kích hoạt thành công của từng
  cascade trước khi cập nhật trạng thái. Thành công của một cascade không được
  ngăn cascade còn lại thử tới cùng đích trong timestep đó. Trong cùng cascade,
  đích đã có một lần thành công không cần thử tiếp.
- Nếu chỉ một cascade thành công, đích nhận trạng thái của cascade đó. Nếu cả
  hai cùng thành công, áp dụng tie rule được truyền rõ ràng. Cấu hình chính là
  `protector-priority`; tùy chọn `rumor-priority` phục vụ kiểm tra độ ưu tiên.
  Không ngầm lấy cascade được duyệt trước làm bên thắng.
- Trạng thái đã active là vĩnh viễn; một node không thể bị đổi cascade hay active
  lại. Dừng khi timestep không tạo ra node active mới.
- `steps` đếm số lớp có node active mới sau lớp seeds, giống IC; không tính vòng
  thử cuối không thành công. Cả hai tập seeds rỗng thì không có lớp, `steps=0`.
- CIC chuẩn hóa thứ tự nguồn/đích theo loại và giá trị node label trước khi lấy
  mẫu bằng RNG riêng. Kết quả có random seed cố định không phụ thuộc thứ tự chèn
  nodes/edges, thứ tự seeds hoặc `PYTHONHASHSEED`. Hỗ trợ các label built-in
  `int`, `bool`, `str`, `bytes`, `float` hữu hạn và tuple/frozenset tổ hợp các kiểu
  này; label object tùy biến bị từ chối để tránh thứ tự không ổn định.
- API và hành vi IC của Milestone 2 giữ nguyên, bao gồm quy ước duyệt của IC.

## 4. Hàm mục tiêu

Mục tiêu là lựa chọn tập protector seeds P gồm k nút sao cho số nút kỳ vọng bị misinformation ảnh hưởng là nhỏ nhất.

Do quá trình lan truyền mang tính ngẫu nhiên, hàm mục tiêu được ước lượng thông qua nhiều lần mô phỏng Monte Carlo.

Fitness của một cá thể được xác định dựa trên số lượng trung bình các nút cuối cùng bị misinformation ảnh hưởng.

Fitness càng nhỏ thì lời giải càng tốt.

## 5. Genetic Algorithm

Mỗi cá thể là một tập gồm k node ID khác nhau.

GA gồm:

1. Initialization.
2. Fitness evaluation.
3. Selection.
4. Crossover.
5. Mutation.
6. Elitism.
7. Stopping condition.

Mọi toán tử phải bảo đảm:

- cá thể luôn có đúng k nút;
- không có node ID trùng trong cùng một cá thể;
- protector seed không thuộc rumor seed;
- tất cả node ID phải tồn tại trong đồ thị.

## 6. Baseline algorithms

Các thuật toán đối chứng:

- Random Selection.
- Degree Centrality.
- PageRank.
- Greedy/Monte-Carlo.

Tất cả phương pháp phải được đánh giá bằng cùng một simulator CIC và cùng điều kiện thực nghiệm.

## 7. Datasets

Sử dụng ba dataset từ Stanford SNAP.

### email-Eu-core

- 1.005 nút.
- 25.571 cạnh gốc.
- Directed graph.
- Có self-loop trong dữ liệu gốc.
- Dự kiến loại bỏ self-loop trong quá trình preprocessing.

### ego-Facebook

- 4.039 nút.
- 88.234 cạnh.
- Undirected graph.

### Wiki-Vote

- 7.115 nút.
- 103.689 cạnh.
- Directed graph.
- Node ID không nhất thiết liên tục.

Dữ liệu gốc phải được giữ nguyên trong:

data/raw/

Dữ liệu đã tiền xử lý được ghi vào:

data/processed/

Không chỉnh sửa trực tiếp dữ liệu trong raw.

## 8. Môi trường thực nghiệm

Ngôn ngữ: Python.

IDE: Visual Studio Code.

Các thư viện dự kiến:

- NetworkX
- NumPy
- Pandas
- Matplotlib

Máy thực nghiệm chính:
- MacBook Pro 16-inch
- Apple M1 Pro
- Apple Silicon / ARM64
- Unified Memory: [16 GB]
- macOS [15.3.1]

Phiên bản python được sử dụng trong môi trường là phiên bản 3.15.2 cùng các thư viện khác có phiên bản như sau:
contourpy==1.4.0
cycler==0.12.1
fonttools==4.68.0
kiwisolver==1.5.1
matplotlib==3.11.2
networkx==3.7
numpy==2.5.4
packaging==26.3
pandas==3.1.0
pillow==13.0.0
pyparsing==3.3.3
python-dateutil==4.0.0
tzdata==2026.6
All final runtime measurements used in the thesis must be produced
on the same experimental machine and software environment.

## 9. Yêu cầu tái lập thực nghiệm

Mọi thành phần ngẫu nhiên phải hỗ trợ random seed.

Mỗi experiment phải lưu tối thiểu:

- dataset;
- random seed;
- rumor seeds;
- protector budget k;
- probability configuration;
- GA parameters;
- Monte Carlo runs;
- runtime;
- protector seeds tìm được;
- fitness/result;
- timestamp nếu cần.

Kết quả nên được lưu dưới CSV hoặc JSON để có thể phân tích lại mà không cần chạy lại thuật toán.

## 10. Mục tiêu Chương 3

Chương 3 gồm:

3.1. Môi trường thực nghiệm.

3.2. Các bộ dữ liệu thực nghiệm.

3.3. Thiết lập thực nghiệm.

3.4. Kết quả thực nghiệm thuật toán di truyền.

3.5. Phân tích sự hội tụ và ảnh hưởng của các tham số.

3.6. So sánh kết quả với các phương pháp đối chứng.

3.7. Phân tích kết quả.

3.8. Hạn chế của nghiên cứu.

3.9. Tóm tắt chương.

Mã nguồn được xây dựng nhằm tạo ra dữ liệu thực nghiệm phục vụ trực tiếp cho các mục 3.3 đến 3.6.
