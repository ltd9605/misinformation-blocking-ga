# Milestone 4A — Baselines và Monte Carlo stability pilot

Đo ngày 2026-11-10. Toàn bộ số liệu bên dưới chỉ phục vụ kiểm tra triển khai,
độ ổn định và chi phí tính toán, **không phải kết quả thực nghiệm chính thức**.

## Triển khai và kiểm thử

- Random Selection: lấy mẫu đều không hoàn lại bằng RNG riêng từ các node ngoài R.
- Degree: giảm dần theo out-degree trên DiGraph, degree trên Graph, không trọng số.
- PageRank: NetworkX trên toàn bộ graph, alpha=0.85, tol=1e-12, max_iter=1000,
  weight=None, teleportation/dangling mass đều; lọc R sau tính điểm.
- Tie-break: label chuẩn hóa tăng dần, integer ID theo thứ tự số. PageRank dùng
  bản copy chuẩn hóa thứ tự node/edge để kết quả không phụ thuộc insertion order.
- Thêm scipy==1.18.1 cho PageRank; giữ nguyên tất cả pin cũ, `pip check` pass.
- 179/179 tests pass: 145 tests cũ, 26 baseline tests và 8 stability tests.
- IC/CIC/Monte Carlo source giữ nguyên từng byte. Toàn bộ 14 raw/processed files
  giữ nguyên SHA-256. 200 evaluation và 76.000 raw observations đã được kiểm tra
  lại độc lập; 16 observations replay trực tiếp bằng CIC khớp hoàn toàn.

## Thiết kế pilot

Cấu hình tái lập: `experiments/configs/mc_stability_email.json`.

- email-Eu-core processed: DiGraph, 1.005 nodes, 24.929 edges.
- R=[0], k=5 cho các baseline, p=0.05, protector-priority.
- Chọn một P cho mỗi baseline một lần, giữ nguyên trong mọi evaluation.
- Random Selection seed=2026; S=50,100,250,500,1000; 10 batch cho mỗi P/S.
- Seed simulation i trong batch b: `100000 + 1000*b + i`.
- Các batch có block seed không giao nhau; mỗi S trong cùng batch dùng prefix
  lồng nhau. Các P dùng cùng lịch seed, nhưng không bảo đảm cùng random outcome
  trên từng cạnh vì CIC có thể tiêu thụ RNG theo các activation khác nhau.
- 200 evaluation được xáo trộn bằng execution_order_seed=2027 và chạy tuần tự.
- Thời gian chọn P chỉ đo một lần, tách khỏi thời gian mỗi evaluation Monte Carlo.
- Môi trường: macOS 15.3.1 ARM64, Python 3.15.2, NetworkX 3.7, SciPy 1.18.1.

| Phương pháp | P cố định | Thời gian chọn P (giây) |
|---|---|---:|
| Không can thiệp | [] | 0 |
| Random | [122,328,515,525,975] | 0,000265 |
| Degree | [82,86,107,121,160] | 0,000425 |
| PageRank | [62,86,107,121,160] | 0,096417 |

Selection time gồm công việc của lần gọi selector, không loại chi phí khởi tạo
backend phát sinh trong lần gọi đó. Tổng selection time: 0,097106 giây.
Tổng runtime của 200 Monte Carlo evaluations: 117,870445 giây; không gồm load,
ghi file hoặc vẽ biểu đồ. Đây là đo pilot trên máy hiện tại, không phải benchmark
runtime chính thức và không được coi là hằng số cho mọi lần chạy.

## Các đại lượng độ ổn định

- Population std: giữ nguyên `std_rumor_count` của evaluator, ddof=0.
- Sample std = population std * sqrt(S/(S-1)).
- SE của một batch = sample std/sqrt(S) = population std/sqrt(S-1).
- Batch-mean SD: sample std của 10 mean độc lập, phản ánh biến động giữa batch.
- Pooled SE dùng cả 10*S observations, chỉ mô tả pooled mean; không dùng để
  chọn S cho một evaluation tương lai.
- Tăng S làm mean bớt nhiễu; không làm biến mất độ biến động vốn có của counts.

Các giá trị dưới lấy trường hợp lớn nhất qua bốn cấu hình P:

| S | SE lớn nhất (nodes) | Batch-mean SD lớn nhất | Mean MC runtime lớn nhất (giây/evaluation) |
|---:|---:|---:|---:|
| 50 | 31,869349 | 31,722053 | 0,084800 |
| 100 | 21,718534 | 18,909484 | 0,169131 |
| 250 | 13,559140 | 15,433204 | 0,413245 |
| 500 | 9,393088 | 8,182039 | 0,822217 |
| 1000 | 6,543069 | 6,991049 | 1,672396 |

Tại S=1000, mean được tính trên 10 batch; std/SE trong bảng là trung bình các
giá trị của từng batch, không phải uncertainty của pooled mean:

| P | Mean rumor | Mean population std | Mean SE | Batch-mean SD | Mean MC time (giây) |
|---|---:|---:|---:|---:|---:|
| Không can thiệp | 349,5767 | 202,230009 | 6,398274 | 6,991049 | 1,299544 |
| Random | 130,7906 | 137,728883 | 4,357549 | 6,502244 | 1,672396 |
| Degree | 11,3410 | 11,367445 | 0,359650 | 0,341751 | 1,643649 |
| PageRank | 11,5824 | 11,713946 | 0,370613 | 0,434089 | 1,623028 |

Degree và PageRank sát nhau trong pilot này: chênh lệch pooled mean 0,2414 node.
Tỷ lệ batch có thứ tự Degree–PageRank–Random là 60%, 60%, 60%, 70%, 80% lần lượt
theo năm mức S. Do đó chưa thể kết luận chắc chắn Degree luôn tốt hơn PageRank.
Các P Degree/PageRank ở đây còn có bốn node chung. Một tập R, một P Random và
một cấu hình p/k không đại diện cho mọi trường hợp của ba thuật toán.

Rumor ít hơn không đồng nghĩa runtime nhỏ hơn: CIC vẫn mô phỏng các lượt thử
của cả PROTECTOR. Chi phí của một GA tương lai còn phụ thuộc số lần evaluation,
không thể suy ra chỉ từ runtime một lần gọi evaluator.

## Đề xuất S có điều kiện

Các ngưỡng kỹ thuật được khai báo trước khi chạy và xét worst single-batch SE
qua mọi P/batch, bao gồm P rỗng:

- **S_opt=500**: mức nhỏ nhất đã thử đạt SE <=1% tổng nodes (10,05 nodes).
  Worst SE=9,393088; chi phí MC lớn nhất trung bình khoảng 0,822 giây/evaluation.
  Đây là lựa chọn ban đầu cho đánh giá thăm dò, không bảo đảm phân biệt lời giải
  có chênh lệch fitness rất nhỏ.
- **S_eval=1000 tạm thời**: mức lớn nhất đã đo, chi phí tối đa trung bình khoảng
  1,672 giây/evaluation. Chưa đạt ngưỡng SE <=0,5% tổng nodes (5,025 nodes):
  worst SE vẫn 6,543069. `target_met=false` được lưu trong JSON.
- Dùng pooled sample std tại S=1000 để ngoại suy công thức sigma^2/target^2
  gợi ý khoảng **1.623 simulations** cho ngưỡng 5,025 nodes. Đây là ước lượng
  dựa trên phương sai pilot; cần pilot bổ sung, ví dụ S=2000, trước khi chốt mức
  đạt mục tiêu. S=1623/2000 chưa được đo trong milestone này.
- Nếu mục tiêu là phân biệt Degree/PageRank sát nhau ở trên, ngưỡng SE theo
  phần trăm tổng nodes có thể quá lỏng; cần thiết kế độ chính xác riêng cho bài
  toán so sánh đó. Chưa dùng pilot này để quyết định kết quả thuật toán chính thức.

## Tái lập và artifacts

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B -m experiments.pilot_mc_stability
```

Đầu ra trong `results/pilots/mc_stability/`:

- `config.json`, `selections.csv`: cấu hình, P và selection runtime.
- `batches.csv`: 200 evaluation có mean/std/SE/runtime và seed batch.
- `raw_results.csv`: 76.000 observations kèm method/S/batch/index/seed/counts/steps.
- `summary.csv`, `rankings.csv`: tổng hợp theo S và xếp hạng các P cố định.
- `report.json`: kết quả đầy đủ, môi trường, công thức seed, các hạn chế,
  recommendations có cờ target_met và SHA-256 data/artifacts.
- `analysis.md`, `stability.png`: bảng tổng hợp và bốn biểu đồ pilot.

`results/` được Git bỏ qua; có thể tái tạo các file bằng lệnh trên. Các thống kê
tái lập được với cùng cấu hình/môi trường; runtime có thể thay đổi.
