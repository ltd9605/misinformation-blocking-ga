# Cấu trúc dự án và việc di chuyển tài liệu

Ngày sắp xếp: 17/11/2026.

## Quy tắc tổ chức

- Thư mục gốc chứa README, CLI, dependency và hướng dẫn cho agent.
- `src/` chứa logic dữ liệu, mô hình, thuật toán và hạ tầng thực nghiệm dùng lại.
- `experiments/` chứa các lệnh chạy/phân tích; cấu hình ở `experiments/configs/`.
- `tests/` chứa kiểm thử, fixtures nhỏ được tạo trong thư mục tạm.
- `data/raw/` và `data/processed/` giữ dữ liệu SNAP cùng metadata tiền xử lý.
- `docs/guides/`, `planning/`, `protocols/`, `reports/` và `reference/` phân nhóm tài liệu.
- `docs/<campaign>/` giữ các bảng, biểu đồ, manifests và bằng chứng đã lưu.
- `results/` chứa đầu ra cục bộ, observations và checkpoint, được bỏ qua bởi Git.

## Tài liệu đã di chuyển

README cũ được giữ đầy đủ trong [TECHNICAL_GUIDE.md](../guides/TECHNICAL_GUIDE.md).
README ở thư mục gốc trở thành trang bắt đầu ngắn gọn. Các báo cáo `PILOT_*`,
`MILESTONE_*`, `CROSS_SCENARIO_GA_CONFIRMATION.md` và `MAIN_EXPERIMENTS_RESULTS.md`
được gom vào `docs/reports/`. Các protocol được gom vào `docs/protocols/`.
Hướng dẫn thủ công ở `docs/guides/`, kế hoạch và bối cảnh ở `docs/planning/`,
phiên bản phụ lục ở `docs/reference/`.

Liên kết Markdown và hình minh họa đã được điều chỉnh theo vị trí mới. Các
lệnh shell và đường dẫn trong cấu hình vẫn tính từ thư mục gốc repository.
Các bộ xuất báo cáo dùng `experiments/reporting.py` để chọn vị trí mới và đổi
liên kết tương đối theo nơi xuất báo cáo.

## Bằng chứng và checksum lịch sử

Việc sắp xếp không di chuyển hoặc chỉnh sửa dữ liệu, cấu hình thực nghiệm,
CSV/JSON, hình ảnh, manifests, raw observations hay checkpoint đã lưu.
Các trường đường dẫn, commit và checksum trong bằng chứng lịch sử được giữ
nguyên theo thời điểm thực nghiệm.

Nội dung Markdown của tài liệu đã đổi ở các liên kết, vì vậy checksum của
những tài liệu đó khác bản chốt trước đây. Các checksum lịch sử không được tính
lại để thay thế bằng chứng. Khi kiểm tra nguyên vẹn bản chốt, dùng đúng tag
`thesis-chapter3-v1.0` như [hướng dẫn trích dẫn](THESIS_VERSION.md).

`verify_main_experiments` vẫn so sánh với checksum đã ghi nhận: bộ phân giải
nhận biết vị trí tài liệu mới, nhưng thay đổi nội dung vẫn bị báo là thay đổi.
Việc sắp xếp không chứng nhận lại checkpoint hoặc cập nhật fingerprint của
các đợt chạy cũ. Kiểm thử hiện tại kiểm tra chương trình tại phiên bản hiện tại.
