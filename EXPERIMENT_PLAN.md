# EXPERIMENT_PLAN.md

## Mục tiêu

Xây dựng hệ thống thực nghiệm phục vụ Chương 3 của đồ án theo từng giai đoạn. Không triển khai tất cả thành phần cùng lúc.

---

## Milestone 1 – Dataset pipeline

Mục tiêu:

Có thể đọc, kiểm tra và tiền xử lý ba dataset.

Cần thực hiện:

- Xây dựng dataset loader.
- Hỗ trợ đọc file .gz trực tiếp khi phù hợp.
- Hỗ trợ directed và undirected graph.
- Bỏ qua comment/header khi cần.
- Kiểm tra node count.
- Kiểm tra edge count.
- Kiểm tra duplicate edges.
- Kiểm tra self-loops.
- Loại self-loop theo cấu hình preprocessing.
- Không giả định node ID liên tục.
- Lưu metadata của dataset sau preprocessing.

Dataset:

- email-Eu-core.
- ego-Facebook.
- Wiki-Vote.

Kiểm thử:

- Số node đọc được phải khớp dữ liệu gốc.
- Số edge phải được báo cáo trước và sau preprocessing.
- Không làm thay đổi file trong data/raw.

Điều kiện hoàn thành:

Có thể chạy một command để load từng dataset và in ra thống kê của graph.

---

## Milestone 2 – Independent Cascade simulator

Mục tiêu:

Xây dựng simulator Independent Cascade.

Cần thực hiện:

- Input graph.
- Seed nodes.
- Propagation probability.
- Random seed.
- Trả về tập node cuối cùng được kích hoạt.
- Hỗ trợ directed và undirected graph.

Kiểm thử:

- p = 0 phải không lan truyền khỏi seed.
- Các graph nhỏ có kết quả xác định cần có unit test.
- Random seed giống nhau phải tạo kết quả tái lập được.

---

## Milestone 3 – Competitive Independent Cascade simulator

Mục tiêu:

Xây dựng CIC simulator cho rumor và corrective information.

Cần thực hiện:

- rumor seeds R.
- protector seeds P.
- propagation model.
- tie-breaking rule.
- random seed.
- số node cuối cùng bị misinformation ảnh hưởng.
- số node được bảo vệ.

Không tự chọn tie-breaking rule nếu PROJECT_CONTEXT.md chưa định nghĩa rõ.

Quy tắc Milestone 3 đã được chốt trong mục 3 của PROJECT_CONTEXT.md: lan truyền
đồng bộ, thu thập thành công của cả hai cascade trước khi giải quyết xung đột,
trạng thái không đổi sau activation. Tie rule phải được truyền rõ ràng;
`protector-priority` là cấu hình chính, có thêm `rumor-priority` để kiểm tra.
Thứ tự lấy mẫu CIC phải được chuẩn hóa độc lập với thứ tự chèn graph/seeds.

Kiểm thử bổ sung:

- Chỉ có một cascade, hai cascade tách biệt và cả hai tập seeds rỗng.
- Đến trước, đến đồng thời, hai tie rules và trạng thái không bị đổi về sau.
- Directed/undirected, isolated seeds, seeds không hợp lệ, `p=0/1`.
- Tái lập khi đổi thứ tự chèn nodes/edges, seed input và `PYTHONHASHSEED`.
- Giữ nguyên toàn bộ tests IC và dataset pipeline.
- Sau unit tests, chạy pilot email-Eu-core với cấu hình/kết quả lưu riêng,
  đánh dấu chỉ kiểm tra triển khai, không phải kết quả chính thức.
- So sánh SHA-256 toàn bộ raw/processed trước và sau kiểm tra.

Điều kiện hoàn thành:

Có unit tests cho các graph nhỏ mà kết quả lan truyền có thể kiểm tra bằng tay.

---

## Milestone 4 – Baseline algorithms

Triển khai:

- Random Selection.
- Degree Centrality.
- PageRank.

Sau đó mới triển khai:

- Greedy/Monte-Carlo.

Mọi baseline trả về một tập gồm đúng k protector nodes.

---

## Milestone 5 – Genetic Algorithm

Triển khai GA gồm:

- representation;
- initialization;
- fitness;
- selection;
- crossover;
- mutation;
- elitism;
- stopping condition.

Cần kiểm tra invariant sau mỗi phép toán:

- đúng k nodes;
- không trùng node;
- node tồn tại;
- không chọn rumor seed.

Fitness sử dụng CIC simulator và Monte Carlo.

---

## Milestone 6 – Experiment runner

Xây dựng chương trình cho phép chạy experiment từ configuration.

Ví dụ configuration cần chứa:

- dataset;
- rumor seeds;
- k;
- propagation probability;
- Monte Carlo runs;
- algorithm;
- population size;
- generations;
- crossover rate;
- mutation rate;
- elitism;
- random seed.

Kết quả được lưu ra results/.

---

## Milestone 7 – Parameter study

Khảo sát:

- population size;
- generations;
- mutation rate;
- crossover rate;
- protector budget k;
- propagation probability.

Mỗi lần chỉ thay đổi biến cần khảo sát trong khi giữ các biến còn lại cố định.

---

## Milestone 8 – Algorithm comparison

So sánh:

- Random.
- Degree Centrality.
- PageRank.
- Greedy/Monte-Carlo.
- Genetic Algorithm.

Các phương pháp phải chạy trong cùng điều kiện.

Các chỉ tiêu:

- misinformation spread;
- spread reduction;
- protected nodes;
- runtime;
- stability.

---

## Milestone 9 – Results export

Tạo:

- CSV tổng hợp.
- Bảng kết quả.
- Dữ liệu convergence.
- Dữ liệu parameter study.
- Các biểu đồ cần cho Chương 3.

Không tự tạo hoặc giả lập kết quả nếu experiment chưa được thực thi.
