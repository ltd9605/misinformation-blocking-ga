# Tài liệu dự án

Các lệnh trong tài liệu được chạy tại thư mục gốc repository. Xem
[README](../README.md) để cài đặt, xem cấu trúc và chạy kiểm thử.

## Hướng dẫn và kế hoạch

| Tài liệu | Nội dung |
|---|---|
| [Hướng dẫn kỹ thuật](guides/TECHNICAL_GUIDE.md) | Nội dung README chi tiết trước khi sắp xếp: dữ liệu, IC/CIC, Monte Carlo, API, thuật toán và các milestone |
| [Chạy thủ công](guides/HUONG_DAN_CHAY_THU_CONG.md) | Ví dụ đồ thị nhỏ, cấu hình, lệnh chạy và cách đọc đầu ra |
| [Bối cảnh dự án](planning/PROJECT_CONTEXT.md) | Các quyết định và trạng thái nghiên cứu đã ghi nhận |
| [Kế hoạch thực nghiệm](planning/EXPERIMENT_PLAN.md) | Kế hoạch đánh giá các phương pháp |
| [Phiên bản phụ lục](reference/THESIS_VERSION.md) | Bản chốt `thesis-chapter3-v1.0` và hướng dẫn trích dẫn |
| [Cấu trúc và lịch sử đường dẫn](reference/PROJECT_LAYOUT.md) | Quy tắc tổ chức, tài liệu đã di chuyển và checksum lịch sử |

## Protocol

| Tài liệu | Bảng, cấu hình và bằng chứng |
|---|---|
| [Experimental Protocol V1](protocols/EXPERIMENT_PROTOCOL_V1.md) | [experiment_protocol_v1/](experiment_protocol_v1/) |
| [Main Protocol — 5 runs](protocols/MAIN_EXPERIMENTS_PROTOCOL.md) | [main_experiments_protocol/](main_experiments_protocol/) |
| [Main Protocol V2 — 4 runs](protocols/MAIN_EXPERIMENTS_PROTOCOL_V2.md) | [main_experiments_protocol_v2/](main_experiments_protocol_v2/) |

Các cấu hình JSON để chạy nằm trong [experiments/configs/](../experiments/configs/).

## Báo cáo

| Báo cáo | Bảng, biểu đồ và bằng chứng |
|---|---|
| [Milestone 4A](reports/MILESTONE_4A_PILOT.md) | Pilot baseline và Monte Carlo stability |
| [Milestone 4B](reports/MILESTONE_4B_PILOT.md) | Pilot Greedy |
| [Milestone 5](reports/MILESTONE_5_PILOT.md) | Pilot Genetic Algorithm |
| [Milestone 6](reports/MILESTONE_6_SMOKE.md) | Smoke test của experiment runner |
| [Pilot Protocol Validation](reports/PILOT_PROTOCOL_VALIDATION.md) | [pilot_protocol_validation/](pilot_protocol_validation/) |
| [Pilot 2 — Calibration](reports/PILOT_2_CALIBRATION.md) | [pilot_2_calibration/](pilot_2_calibration/) |
| [Reduced Screen](reports/MILESTONE_7_REDUCED_SCREEN.md) | [milestone_7_reduced_screen/](milestone_7_reduced_screen/) |
| [Reduced Screen V2](reports/MILESTONE_7_REDUCED_SCREEN_V2.md) | [milestone_7_reduced_screen_v2/](milestone_7_reduced_screen_v2/) |
| [Cross-Scenario Confirmation](reports/CROSS_SCENARIO_GA_CONFIRMATION.md) | [cross_scenario_ga_confirmation/](cross_scenario_ga_confirmation/) |
| [Main Experiments Results](reports/MAIN_EXPERIMENTS_RESULTS.md) | [main_experiments_results/](main_experiments_results/) |

Kiểm tra bản chốt trước đây nằm trong [thesis_version_validation/](thesis_version_validation/).
Raw observations, logs và checkpoint đầy đủ nằm trong `results/` trên máy chạy;
thư mục này không được đưa vào Git.
