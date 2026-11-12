# Phiên bản mã nguồn dùng cho phụ lục báo cáo

Ngày chốt: **12/11/2026**. Tag của bản chốt này:
**`thesis-chapter3-v1.0`**.

Repository: <https://github.com/ltd9605/misinformation-blocking-ga>.
Đường dẫn phiên bản:
<https://github.com/ltd9605/misinformation-blocking-ga/tree/thesis-chapter3-v1.0>.

## Phạm vi phiên bản

Phiên bản gồm dataset pipeline, IC/CIC, Monte Carlo evaluator, các baseline,
Full Greedy và Candidate-Restricted Greedy, Genetic Algorithm, experiment
runner, calibration, Reduced Parameter Screening, Cross-Scenario Confirmation,
Main Experiments và phần xuất kết quả của Milestones 1–9.

Main Experiments dùng Protocol V2 đã được xác nhận: sáu rumor scenarios,
bốn independent runs/scenario và sáu phương pháp hoàn thành, tổng cộng
**144/144 result rows**. Full Greedy có **24 rows skipped** theo giới hạn chi
phí. Kết quả ghi nhận **2.058 evaluator calls, 1.233.000 CIC simulations**,
runtime chính khoảng **4.436,312 giây**. Đây là bản lưu kết quả đã chạy;
việc tạo commit/tag không chạy thêm thực nghiệm hoặc thay đổi protocol.

Các tham số Main được khóa: k=5, p=0.03, protector-priority, S_opt=100;
GA N=10/G=10/crossover=0.8/mutation=0.1/tournament=3/elitism=1/cache=True.
S_eval mỗi batch là 6.000 cho email, 2.500 cho Facebook/Wiki; hai batch/P.
Chi tiết cấu hình, R/P, lịch seed, giới hạn và uncertainty được lưu cùng báo cáo.

## Những tệp cần dẫn trong phụ lục

| Nội dung | Tệp/thư mục |
|---|---|
| Hướng dẫn cài đặt, cấu trúc và API | [README.md](README.md) |
| Hướng dẫn chạy ví dụ nhỏ bằng tay | [HUONG_DAN_CHAY_THU_CONG.md](HUONG_DAN_CHAY_THU_CONG.md) |
| Protocol Main đã khóa | [MAIN_EXPERIMENTS_PROTOCOL_V2.md](MAIN_EXPERIMENTS_PROTOCOL_V2.md) |
| JSON cấu hình Main | [main_experiments_protocol_v2.json](experiments/configs/main_experiments_protocol_v2.json) |
| Báo cáo thực nghiệm | [MAIN_EXPERIMENTS_RESULTS.md](MAIN_EXPERIMENTS_RESULTS.md) |
| CSV/JSON, bảng tổng hợp, convergence, biểu đồ và manifest | [docs/main_experiments_results](docs/main_experiments_results) |
| Calibration và các khảo sát trước Main | Các báo cáo `PILOT_*`, `MILESTONE_7_*`, `CROSS_SCENARIO_GA_CONFIRMATION.md` và thư mục tương ứng trong `docs/` |
| Kiểm tra trước khi chốt phiên bản | [docs/thesis_version_validation](docs/thesis_version_validation) |
| Phiên bản thư viện | [requirements.txt](requirements.txt) |

Các file trong `docs/` được quản lý trực tiếp bằng Git. Hai ZIP đóng gói cục
bộ được giữ trên máy và bỏ qua khi commit vì trùng với các thư mục đã giải nén.
`.DS_Store`, `.venv/` và `results/` cũng nằm ngoài bản chốt Git.

Các tệp SNAP raw/processed đã được quản lý trong `data/` tiếp tục được giữ
nguyên trong Git; chúng khác với raw observations của mô phỏng Monte Carlo.

Đặc biệt, raw Monte Carlo observations, worker logs và checkpoint đầy đủ trong
`results/main_experiments_v2/` được lưu cục bộ. GitHub chứa kết quả tổng hợp,
R/P, seed schedules, provenance và inventory checksum để đối chiếu; không mô
tả bản checkout Git là đã kèm toàn bộ raw observations/checkpoint đó.

Metadata thực nghiệm giữ Git commit và trạng thái working tree **tại thời
điểm chạy**, có thể là commit cũ hơn tag này. Các trường lịch sử được giữ nguyên;
không thay bằng SHA của bản chốt. Implementation/data/artifact checksums cung
cấp đối chiếu với mã nguồn và dữ liệu đã sử dụng.

## Lấy commit SHA chính xác để trích dẫn

SHA cuối cùng được Git sinh sau khi commit, nên tài liệu trong chính commit
không tự ghi SHA của nó. Sau khi checkout phiên bản, dùng:

```sh
git rev-parse 'thesis-chapter3-v1.0^{commit}'
git show --no-patch --format=fuller thesis-chapter3-v1.0
```

Ghi **đủ 40 ký tự SHA** vào phụ lục. Mẫu nội dung:

> Mã nguồn và kết quả thực nghiệm được lưu tại repository
> `ltd9605/misinformation-blocking-ga`, phiên bản `thesis-chapter3-v1.0`,
> Git commit `<SHA 40 ký tự do Git trả về>`, ngày chốt 12/11/2026.

Liên kết trực tiếp tới commit có dạng
`https://github.com/ltd9605/misinformation-blocking-ga/commit/<SHA>`.
Để kiểm tra mã nguồn của phụ lục, checkout đúng tag/SHA thay vì lấy mặc định
trạng thái mới nhất của nhánh `main`.

## Kiểm tra sau khi lấy phiên bản

Trong một thư mục checkout phù hợp, với môi trường Python/dependencies theo
README, chạy:

```sh
.venv/bin/python -B -m unittest discover -s tests -q
```

Bản chốt được kiểm tra với **493 tests**. Hướng dẫn chạy thủ công cung cấp ví
dụ tổng hợp 9 nút để xác minh cách cấu hình và đọc kết quả với chi phí nhỏ.
Các số đo thời gian có thể thay đổi theo máy và trạng thái hệ thống.
