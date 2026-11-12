# Pilot Protocol Validation

Đã hoàn thành kiểm chứng protocol sau Milestone 6. Đây là pilot kỹ thuật, **chưa
phải main experiments, chưa chuyển sang Milestone 7 và không kết luận phương
pháp tốt nhất**. Các số dưới đây được đo từ các lần chạy thực tế.

## 1. Kiểm tra Experiment Runner

Smoke Milestone 6 hỗ trợ 7 API nhưng file cấu hình chỉ chọn **6 phương pháp**:
No Intervention, Random, Degree, PageRank, Candidate-Restricted Greedy và GA.
Full Greedy không nằm trong `algorithms`, Full limits=0. Cả 6 phương pháp đã
chọn đều gọi final evaluator một lần nên có 6 final evaluations. k=2 trong
smoke đó; đây không phải trường hợp k=0 dùng chung control. Evidence/checksums
nằm trong [legacy_smoke_audit.json](docs/pilot_protocol_validation/legacy_smoke_audit.json).

Runner hiện xuất `method_status.csv` và `method_statuses` trong JSON, luôn có
đủ 7 phương pháp. `skipped_algorithms` cho phép cấu hình ghi lý do rõ ràng;
không khai báo lý do thì dùng `not_selected_in_configuration`. Skipped methods
không có số đo chất lượng giả trong `results.csv`. Với k=0, phương pháp vẫn
`completed`, reason=`reused_empty_protector_control`, final calls thêm=0.

Runtime gồm các nhóm cộng được: graph loading/validation, preprocessing (0),
selection/optimization, final MC, primary artifact writes và orchestration.
Orchestration được tách thành config validation; graph snapshot/seeds/preflight;
environment provenance; selection logging/graph checks; final logging/raw
export/checksum; residual overhead. Các phần con nằm trong orchestration,
không cộng thêm lần nữa vào total.

`total_experiment_runtime_seconds` giữ phạm vi Milestone 6: API entry đến xong
primary artifacts, không gồm đọc JSON trước API, khởi động Python/import,
ghi metadata/summary cuối và rename. Protocol bổ sung subprocess wall time
(gồm khởi động/CLI và publish), cùng wall time của toàn đợt điều phối.
Selection gồm MC fitness và dựng candidate pool; final MC/control tính riêng.
Không sửa semantics của IC/CIC/Monte Carlo hoặc bất kỳ thuật toán nào.

## 2. Cấu hình và R cố định

Nguồn: [pilot_protocol_validation.json](experiments/configs/pilot_protocol_validation.json).

| Tham số pilot | Giá trị |
|---|---|
| Datasets | email-Eu-core, ego-Facebook, Wiki-Vote |
| Rumor count / k | 1 / 5 |
| p / tie rule | 0.01 và 0.05 / protector-priority |
| S_opt / S_eval | 20 / 200 |
| Independent algorithm/MC runs | 3 mỗi dataset–p, cùng R |
| GA | N=10, G=10, crossover=0.8, mutation=0.1, tournament=3, elite=1, cache=True |
| Restricted pool | Top 10 out-degree (directed) / degree (undirected), ngoài R |
| PageRank | alpha=0.85, tol=1e-12, max_iter=1000 |
| Master seed / block width | 2026 / 1.000.000 |

R được lấy mẫu đều không hoàn lại từ `sorted(graph.nodes)`, không sinh ID bằng
range(n), không lấy mẫu lại sau khi xem spread/fitness/thuật toán. RNG seed là
8 bytes đầu SHA-256 của `pilot-protocol-rumor-v1:2026:{dataset}`. Manifest
[rumor_scenarios.json](docs/pilot_protocol_validation/rumor_scenarios.json) được
lưu **trước bất kỳ mô phỏng nào**. Cùng R xuyên suốt methods, p và 3 repeats.

| Dataset | R | Sampling RNG seed | Out-degree/degree của R | Số node reachable từ R |
|---|---|---:|---:|---:|
| email-Eu-core | [577] | 648922761795409240 | 13 | 965/1.005 |
| ego-Facebook | [2162] | 11389267221022948117 | 15 | 4.039/4.039 |
| Wiki-Vote | [4341] | 4111783169675930736 | 1 | **2/7.115** |

Reachability chỉ được ghi làm metadata, không dùng để đổi R. Đặc biệt Wiki-Vote
giữ nguyên kịch bản dù khả năng lan truyền rất hạn chế.

Mỗi comparison dùng seed plan đã kiểm chứng của runner. Pilot ánh xạ
`independent_run_index=(dataset_index*2+p_index)*3+replicate_index`, tức 0–17;
smoke dùng 18–20. Replicate index trong mỗi dataset–p vẫn là 0,1,2. Các block
giữa 21 comparisons không giao nhau; nửa đầu optimization, nửa sau final.
Random/GA operators có RNG domain riêng; mọi phương pháp trong comparison dùng
cùng lịch final seeds. Đây là 3 lần chạy ngẫu nhiên độc lập **có điều kiện trên
cùng R**, không phải 3 rumor scenarios độc lập. Lịch seed chung không bảo đảm
cùng outcome trên từng cạnh.

Smoke riêng trên mỗi dataset dùng cùng R/k/p=0.05/pool nhưng S_opt=2, S_eval=5,
GA N=4/G=1/tournament=2; rates/elite giữ như pilot. Đây là cấu hình kiểm tra
tích hợp nhỏ, không thay thế hoặc giảm cấu hình 18 pilots đã đề xuất.

## 3. Preflight và skipped methods

Các giới hạn được khai báo trước execution trong config: mỗi optimizer tối đa
100 calls/2.000 CIC simulations; Full Greedy có thêm limit riêng bằng các mức
này. Tổng protocol tối đa 1.200 s, mỗi comparison tối đa 300 s. Dự tính thời
gian từ tốc độ MC smoke, nhân safety factor=2, chỉ dùng để admission; child
process có hard timeout. Không lựa chọn hoặc thay thế thuật toán theo chất lượng.

| Method | Evaluator calls cho một pilot | Optimization CIC simulations |
|---|---:|---:|
| Random/Degree/PageRank | 0 khi selection | 0 |
| Candidate-Restricted Greedy, m=10/k=5 | 40 chính xác | 800 |
| GA N=10/G=10/E=1 | Tối đa 100, cache có thể giảm | Tối đa 2.000 |

Final gồm 6 calls × 200 = 1.200 CIC simulations. Cận trên một comparison
được nhận chạy là 4.000 CIC simulations. Công thức Full/Restricted là
`k*m-k*(k-1)//2` calls; GA là `N+G*(N-E)` trước cache. Đây là khối lượng công
việc, **không phải runtime đo được**.

| Full Greedy trên dataset | m ngoài R | Calls với k=5 | CIC với S_opt=20 | Trạng thái |
|---|---:|---:|---:|---|
| email-Eu-core | 1.004 | 5.010 | 100.200 | skipped: vượt limits |
| ego-Facebook | 4.038 | 20.180 | 403.600 | skipped: vượt limits |
| Wiki-Vote | 7.114 | 35.560 | 711.200 | skipped: vượt limits |

Có **18 Full Greedy pilot slots skipped**, cộng 3 smoke slots skipped; mọi
slot có reason/cost trong [preflight.csv](docs/pilot_protocol_validation/preflight.csv)
và [method_status.csv](docs/pilot_protocol_validation/method_status.csv).
Không có comparison nào bị bỏ qua, lỗi hoặc timeout. Full Greedy không được
gán kết quả của Restricted và không có runtime thực đo trong đợt này.

## 4. Cấu hình thành công và runtime

**3/3 smoke + 18/18 pilot comparisons thành công**. Mỗi comparison chạy 6
phương pháp, tạo 126 result rows và 147 method-status rows tính cả skipped.

| Smoke | Runner total (s) | CIC simulations |
|---|---:|---:|
| email-Eu-core | 0.494 | 122 |
| ego-Facebook | 2.212 | 122 |
| Wiki-Vote | 1.403 | 120 |

Bảng sau chỉ so sánh chi phí cấu hình, không xếp hạng chất lượng phương pháp.
Loading/overhead được tính một lần mỗi comparison, không cộng total lặp theo
6 rows trong CSV.

| Dataset | p | Comparisons | Selection/optimization tổng (s) | Final MC tổng (s) | Runner totals cộng (s) | Khoảng total mỗi comparison (s) | CIC simulations |
|---|---:|---:|---:|---:|---:|---|---:|
| email-Eu-core | 0.01 | 3 | 1.522 | 1.076 | 3.079 | 1.008–1.039 | 7.700 |
| email-Eu-core | 0.05 | 3 | 6.895 | 5.158 | 12.550 | 4.003–4.370 | 7.540 |
| ego-Facebook | 0.01 | 3 | 10.784 | 9.190 | 21.650 | 6.377–7.824 | 8.200 |
| ego-Facebook | 0.05 | 3 | 52.945 | 39.749 | 94.310 | 30.668–32.291 | 8.080 |
| Wiki-Vote | 0.01 | 3 | 9.197 | 6.661 | 17.534 | 5.531–6.088 | 7.800 |
| Wiki-Vote | 0.05 | 3 | 23.729 | 16.689 | 42.092 | 13.526–14.576 | 8.180 |

18 pilots: 1.295 optimization calls × 20 = 25.900 CIC simulations, 108 final
calls × 200 = 21.600; **47.500 CIC simulations**. Ba smoke thêm 364, nên primary
protocol tổng **47.864**. GA dùng 22–41 actual fitness evaluations/pilot so
với cận 100; Restricted luôn đúng 40 calls.

Cộng runtime 21 comparisons: loading=1.634 s, preprocessing=0,
selection/optimization=107.397 s, final MC=79.050 s, primary writes=0.058 s,
orchestration=7.183 s; runner totals=**195.323 s**. Cộng subprocess wall=198.930 s;
protocol wall qua aggregation=**199.337 s**, dưới ngân sách 1.200 s. Mỗi final
MC call hoàn thành trong tối đa 2.751 s. S_opt=20/S_eval=200 và GA N10/G10 khả
thi về thực thi trong các kịch bản đã chạy; chưa chứng minh đủ độ chính xác.

## 5. Mức lan truyền và Monte Carlo precision

Chẩn đoán dùng **No Intervention**, không dùng hiệu quả một thuật toán để
chọn p. Ngưỡng khai báo trước: low spread nếu mean số node lan thêm <1% n;
near saturation nếu control mean ≥90% n. Pooled control gồm 600 observations
(3 independent batches × 200) cho mỗi dataset–p, cùng R. SD dưới đây là **sample
SD**, SE=sample SD/sqrt(600); trong `results.csv` mỗi method/run vẫn giữ
population std ddof=0 và sample-corrected SE cho S_eval=200.

| Dataset | p | Control mean | Sample SD | Pooled SE | Không lan thêm | Chẩn đoán |
|---|---:|---:|---:|---:|---:|---|
| email-Eu-core | 0.01 | 1.4783 | 2.3796 | 0.0971 | 89.33% | Quá ít lan truyền |
| email-Eu-core | 0.05 | 193.3150 | 229.3170 | 9.3618 | 49.33% | Có spread, variance lớn |
| ego-Facebook | 0.01 | 3.9883 | 22.4146 | 0.9151 | 87.50% | Quá ít lan truyền |
| ego-Facebook | 0.05 | 666.0567 | 904.6621 | 36.9327 | 47.83% | Có spread, variance lớn |
| Wiki-Vote | 0.01 | 1.0033 | 0.0577 | 0.0024 | 99.67% | Giới hạn bởi R chỉ reachable 2 node |
| Wiki-Vote | 0.05 | 1.0467 | 0.2111 | 0.0086 | 95.33% | Giới hạn bởi R chỉ reachable 2 node |

Không cấu hình nào gần bão hòa toàn graph theo ngưỡng 90%; không quan sát nào
trong 600/control/cell đạt 90% n. Kết luận này chỉ áp dụng cho các R đã lưu.
Không suy ra Wiki-Vote nói chung ít lan truyền với hai mức p này.

Ở p=0.05, max SE của một evaluation S=200 là 16.422 nodes (email) và 65.650
nodes (Facebook), lần lượt khoảng 1.63% và 1.63% n. Pooled SE nhỏ hơn không
được dùng thay SE của một evaluation độc lập trong tương lai.

Mục tiêu kỹ thuật tạm theo hướng stability pilot trước: SE_opt≤1% n,
SE_eval≤0.5% n, chưa phải tiêu chuẩn nghiên cứu được chốt. Dùng sample variance
từ 200 held-out observations để ước lượng `ceil((sample_sd/epsilon)^2)`:

| Dataset/p | Cận S_opt plug-in lớn nhất qua các P/runs quan sát | Cận S_eval plug-in |
|---|---:|---:|
| email-Eu-core / 0.05 | 535 | 2.137 |
| ego-Facebook / 0.05 | 529 | 2.114 |

Các cận lớn nhất đến từ control; P trong quá trình tối ưu chưa được khảo sát
đầy đủ bằng held-out MC. Cận không phải S đã chạy hoặc bảo đảm độ chính xác,
và không áp dụng tự động cho R khác. SD nhỏ/0 trong kịch bản gần như không
spread không chứng minh S nhỏ đủ cho mọi kịch bản.

`mc_precision.csv` còn dùng prefixes 20/50/100/200 của cùng raw final sample:
đây là nested prefixes, không phải batches độc lập, không có MC phát sinh.
Ở p=0.05, S=20 có max SE 54.021 (email), 199.887 (Facebook); độ lệch prefix
mean so với full S=200 lên tới 72.57 và 340.815 nodes. Full mean cũng có nhiễu,
không được coi là kỳ vọng thật. Không tự giảm S vì các kịch bản ít spread.

## 6. Optimization fitness và independent evaluation

Các fitness dùng seed optimization cố định/cache cục bộ; final dùng block mới
sau khi chốt P. Không chọn lại P từ final results. Ví dụ GA p=0.05:

| Dataset / replicate | Optimization fitness | Independent mean | Final − optimization |
|---|---:|---:|---:|
| email / 0 | 7.85 | 19.430 | 11.580 |
| email / 1 | 9.50 | 21.575 | 12.075 |
| email / 2 | 13.10 | 17.695 | 4.595 |
| Facebook / 0 | 4.95 | 18.080 | 13.130 |
| Facebook / 1 | 4.40 | 34.160 | 29.760 |
| Facebook / 2 | 7.45 | 59.250 | **51.800** |

Có chênh lệch đáng lưu ý; tăng N/G khi giữ sample fitness rất nhỏ có thể tiếp
tục tối ưu nhiễu. Không thể quy mọi chênh lệch cho một nguyên nhân vì training
score đã qua selection và không lưu uncertainty của toàn bộ fitness trials.
Flag trong `fitness_gaps.csv` chỉ là mô tả: |gap| > max(1% n, 2 final SE), không
phải hypothesis test hoặc confidence interval cho gap.

GA có 11 convergence rows mỗi pilot (generation 0–10); cả 18 histories bảo
toàn elite và generation-best không tăng dưới fixed training objective. Ví dụ
email p=0.05/r0 best 15.85→7.85; Facebook p=0.05/r0 25.2→4.95. Wiki best=1
không đổi trong cả 6 pilots: hợp với kịch bản spread rất hạn chế, không phải
bằng chứng tối ưu tổng quát. Lưu cả best/mean fitness đầy đủ trong convergence.

Có 21/108 pilot result rows đo relative reduction âm. Giữ nguyên số đo, không
cắt thành 0 hoặc kết luận can thiệp gây hại: dùng cùng RNG seed schedule không
đồng nghĩa cùng edge outcomes; variance MC và control uncertainty còn lớn.
Không dùng bất kỳ bảng nào trong pilot này để chọn thuật toán thắng.

## 7. Đề xuất trước main experiments

Các mục sau là **đề xuất cần xác nhận**, chưa triển khai thành main settings:

- Giữ k=5/rumor count=1 và GA N=10/G=10/rates 0.8/0.1/tournament=3/elite=1/cache
  làm reference cấu hình khả thi về thời gian. Chỉ thử một cấu hình nên chưa
  xác định được N/G/rates tốt nhất; chưa chạy parameter study.
- p=0.05 ở email/Facebook là ứng viên cho kịch bản có spread trong R hiện tại;
  p=0.01 hữu ích làm regime ít spread, không đủ để đánh giá chất lượng chung.
  Với Wiki, cần protocol nhiều R được lấy mẫu và chốt **trước outcomes**, có
  thể cân nhắc strata topology được công bố trước. Không thay R sau pilot này
  để tạo lợi thế cho thuật toán.
- S_opt=20/S_eval=200 đã khả thi về compute nhưng chưa nên coi đủ chính xác.
  Đề xuất **pilot xác nhận tiếp** S_opt=100 trước khi tăng N/G, kiểm tra cả các
  candidate P từng bước; 100 chưa được đo ở đây và có thể vẫn không đạt mục
  tiêu 1% n. Nếu áp dụng mục tiêu đó cho envelope variance control hiện tại,
  ước lượng cho thấy cần khoảng 535, nên chưa chốt S_opt cho main experiments.
- S_eval=2.500 là ứng viên cần kiểm tra tiếp cho p=0.05 email/Facebook, dựa
  trên plug-in bounds khoảng 2.100; chưa thực thi và không bảo đảm cho R mới.
  Mọi method/control trong một comparison vẫn phải cùng S_eval/final protocol.
- Nếu thử S_opt=100 phải tăng giới hạn optimization CIC tương ứng (GA upper
  10.000 simulations, Restricted 4.000); không tự nâng Full limits. Mọi runtime
  cho cấu hình tăng S hiện chỉ là dự tính, cần đo lại trước admission.
- Ba runs chỉ đủ pilot kỹ thuật. Đề xuất xác nhận nhiều rumor scenarios và ít
  nhất 10 independent runs cho stability của main experiments; số lượng cuối
  cần chốt cùng error targets, CI/reporting rule và ngân sách thực tế.
- Full Greedy tiếp tục chỉ chạy nơi cost limits cho phép; nếu main graph lớn
  không chạy được, giữ explicit skipped và dùng tên Candidate-Restricted đúng
  bản chất. Pool top-10 đã khả thi, chưa được chứng minh đủ đại diện/đủ tốt.

## 8. Kiểm chứng, artifacts và thay đổi repository

**337/337 tests pass** sau pilot (317 cũ + 20 tests mới), lệnh:

```sh
.venv/bin/python -B -m unittest discover -s tests
```

Audit dữ liệu thực: tính lại mean/population std/SE/reduction từ **21.690 raw
final observations**, kiểm tra 147 primary artifact hashes, 204 convergence
rows, đủ k/disjoint R, seed intervals và runtime accounting của cả 21
comparisons. 14/14 data files và toàn bộ 32 snapshot files (data, các lõi cũ và
requirements) giữ nguyên SHA-256, không thêm/xóa dữ liệu. Processed topology:
email 1.005 nodes/24.929 directed edges; Facebook 4.039/88.234 undirected;
Wiki-Vote 7.115/103.689 directed.

Replay riêng email p=0.05/r0: mọi non-timing summary fields/convergence khớp,
1.200 raw final observations byte-identical. Replay dùng thêm 65 optimization
calls, 6 final calls = **2.500 CIC simulations**, runner time=4.452 s, không
tính vào 18 pilots. Primary+replay tổng **50.364 CIC simulations**; test-suite
simulations không được gộp vào pilot counters.

Artifacts compact để review/commit nằm trong
[docs/pilot_protocol_validation](docs/pilot_protocol_validation): results CSV/JSON,
preflight, execution/status, rumor scenarios, convergence, precision, gaps,
summary, metadata/environment và integrity/validation/replay evidence. Raw MC,
config/metadata đầy đủ của mỗi comparison, selection traces và logs nằm trong
`results/pilot_protocol_validation/` (gitignored). Không sửa các smoke artifacts
Milestone 6 cũ. Môi trường đo: CPython 3.15.2, Darwin arm64, 10 logical CPUs,
16 GiB RAM; Git commit `f62679ef97d66e7d30fb98d6c43a39f1275e17e9`, working tree
dirty được ghi cùng source hashes. Hardware field không đọc được giữ null.

Lệnh tái chạy, dùng output root khác vì không ghi đè:

```sh
.venv/bin/python -B -m experiments.pilot_protocol_validation --output-dir results/pilot_protocol_validation_repeat
```

Code mới: `src/experiments/protocol.py`,
`experiments/pilot_protocol_validation.py`, config pilot và
`tests/test_pilot_protocol.py`. Sửa config/runner để ghi skipped status và
runtime breakdown; bổ sung tests tương ứng, cập nhật tài liệu. IC/CIC/MC,
algorithms, pipeline, dependencies và dữ liệu giữ nguyên. Không thực hiện
Milestone 7 hoặc main experiments.
