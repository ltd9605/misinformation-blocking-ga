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

### Monte Carlo evaluator trước baseline và GA

- Mỗi evaluation gọi lại nguyên vẹn `simulate_cic()` đúng S lần với cùng graph,
  R, P, p và tie rule. S là số nguyên dương; base random seed là số nguyên không âm.
- Simulation có chỉ số i từ 0 đến S-1 dùng seed `base_random_seed + i`.
  Cùng cấu hình và base seed phải tái lập được từng quan sát và các thống kê.
- Báo cáo mean rumor/protector/inactive, min/max rumor và độ lệch chuẩn tổng thể
  của S rumor counts (mẫu số S, `ddof=0`; S=1 có std=0). Đây không phải sai số
  chuẩn của mean. Runtime đo riêng và không thuộc phần kết quả cần tái lập.
- Raw results giữ index, seed, các counts và steps của từng simulation, cho phép
  chạy lại bằng CIC mà không cần giữ toàn bộ tập node của S lần trong bộ nhớ.
- Khi so sánh protector sets, dùng cùng S/base seed để có cùng lịch seed. Lịch
  seed chung không bảo đảm cùng random outcome trên từng cạnh vì các activation
  hợp lệ và thứ tự tiêu thụ RNG có thể khác giữa các cấu hình.
- Pilot chỉ kiểm tra triển khai/hiệu năng, không phải kết quả chính thức.

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

### Chính sách Milestone 5 đã xác nhận

- Cá thể là frozenset k node trong V ngoài R. Khởi tạo ngẫu nhiên đều mỗi cá thể;
  các vị trí quần thể được phép có genotype giống nhau, kể cả khi k=0 hoặc k=m.
- Tournament lấy các vị trí không hoàn lại, chọn mean rumor nhỏ nhất. Tie-break
  theo genotype chuẩn hóa rồi slot index. Set Crossover giữ giao cha mẹ và chọn
  ngẫu nhiên đủ node từ hiệu đối xứng; mutation thay một node bằng node ngoài cá
  thể, no-op khi k=0 hoặc hết node thay. Repair loại gene sai/trùng, cắt/bù đủ k.
- Sau initialization, từng toán tử và từng generation đều kiểm tra invariants.
  Elitism giữ nguyên top E vị trí cùng genotype/fitness; không crossover/mutation
  lên elite. E có thể từ 0 đến N, không yêu cầu các elite là genotype khác nhau.
- Thế hệ 0 là initial population. max_generations=G nghĩa là đúng G transitions,
  ghi G+1 history records; không early stop. G=0 vẫn đánh giá quần thể ban đầu.
- Người dùng đã chọn fitness seed cố định và cache cục bộ trong một optimization.
  Mỗi cache miss gọi evaluate_cic nguyên vẹn; mọi genotype dùng cùng p/R/S_opt/
  tie rule/base seed. Cache key là frozenset, chỉ hợp lệ vì toàn bộ context trên
  cùng graph giữ cố định trong lần gọi; không chia sẻ cache giữa các lần gọi.
- cache_fitness=False đánh giá lại non-elite requests bằng cùng seed schedule,
  không đổi sang sample mới. Elite vẫn giữ fitness. Cache hits/elite carries
  không được đếm thành evaluator calls hay CIC simulations mới.
- Đây là fitness có nhiễu ước lượng nhưng được cố định; có thể overfit sample.
  Tăng generations/cache hits không làm tăng độ chính xác fitness đã lưu.
- RNG toán tử dùng seed 64-bit từ SHA-256 của
  `misinformation-ga-v1:operators:{random_seed}`. Base fitness mặc định suy ra
  tương tự với domain `fitness`, hoặc được truyền rõ ràng. RNG đều là local.
  Fitness simulation i dùng base+i. Seed đánh giá độc lập bắt đầu base+S_opt,
  không trùng khoảng seed tối ưu; evaluate riêng sau khi đã chốt P, không feedback.
- Lưu generation-best và best-so-far, mean/worst fitness, population snapshots,
  diversity, actual evaluator calls, cache hits, elite reuses và runtime.
  Với E>=1, generation-best không tăng dưới objective cố định; E=0 vẫn giữ
  best-ever để trả về, dù quần thể cuối có thể kém hơn.
- Không cache: tối đa N+G*(N-E) evaluator calls. Có cache: tối đa min(cận trên đó,
  C(m,k)) calls; mỗi call dùng S_opt CIC simulations. k=0 vẫn cần fitness P rỗng:
  với cache chỉ gọi evaluator một lần, không tạo score giả.
- Pilot email: N=8, G=5, k=2, S_opt=20, S_eval=100, rates 0.8/0.3, tournament=3,
  E=1, random_seed=2026, fitness_base=100000, protector-priority, cache=True.
  Các mức này chỉ kiểm tra thực thi, không phải thiết lập thực nghiệm chính thức.
- Chỉ pilot graph tổng hợp nhỏ và email, không benchmark Facebook/Wiki-Vote,
  không so sánh chất lượng GA/baseline hoặc triển khai experiment runner.

## 6. Baseline algorithms

Các thuật toán đối chứng:

- Random Selection.
- Degree Centrality.
- PageRank.
- Greedy/Monte-Carlo.

Tất cả phương pháp phải được đánh giá bằng cùng một simulator CIC và cùng điều kiện thực nghiệm.

### Milestone 4A: ba baseline và kiểm tra ổn định Monte Carlo

- `select_random`, `select_degree`, `select_pagerank` trả frozenset đúng k node
  phân biệt ngoài R; k có thể bằng 0 và không vượt số node hợp lệ. Không đổi graph.
- Random lấy mẫu đều không hoàn lại từ candidate list theo thứ tự label chuẩn
  của CIC; RNG riêng hỗ trợ random seed. Seed input có thể là iterable/generator.
- Degree xếp giảm dần theo out-degree không trọng số trên DiGraph, degree trên
  Graph. Khi bằng điểm, ưu tiên node label tăng dần (integer ID theo số).
- PageRank tính trên toàn bộ graph, bao gồm rumor nodes, rồi lọc R khi chọn P.
  Dùng NetworkX/SciPy, alpha=0.85, tol=1e-12, max_iter=1000, weight=None,
  teleportation/dangling mass đều. Graph copy chuẩn hóa thứ tự nodes/edges;
  điểm số bằng nhau chính xác dùng label tăng dần. Không ẩn lỗi không hội tụ.
- Tất cả P dùng `evaluate_cic()` hiện có; IC/CIC/Monte Carlo giữ nguyên semantics.
- Pilot email-Eu-core cố định R=[0], k=5, p=0.05, protector-priority, một P rỗng
  và một P cố định cho mỗi baseline. Random Selection dùng seed 2026.
- S=50,100,250,500,1000; 10 batch với seed(batch,i)=100000+1000*batch+i.
  Các batch có khoảng seed không chồng lấp; các S trong cùng batch dùng prefix
  lồng nhau; mọi P dùng cùng lịch seed, không bảo đảm common edge outcomes.
- Ghi riêng thời gian chọn P một lần và thời gian Monte Carlo từng evaluation.
  Giữ population std của evaluator; tính sample std và SE=population_std/sqrt(S-1)
  bên ngoài evaluator. Báo cáo thêm SD của batch means và pooled SE của 10*S
  quan sát, không dùng pooled SE để đề xuất S cho một evaluation tương lai.
- Ngưỡng kỹ thuật khai báo trước pilot: SE tối đa qua các P/batch <=1% số nodes
  cho S_opt, <=0.5% cho S_eval. Nếu không mức S nào đạt, báo rõ chưa đạt và chỉ
  dùng mức lớn nhất đã thử làm lựa chọn tạm; ước lượng S cần thêm chưa phải đo.
- Kết quả chỉ là pilot điều kiện trên R/P/p/k này, chưa kết luận xếp hạng thuật
  toán tổng quát. Chưa triển khai Greedy/Monte-Carlo hoặc GA trong 4A.

### Milestone 4B: Full Greedy và Candidate-Restricted Greedy

- Full Greedy bắt đầu P rỗng. Mỗi bước đánh giá mọi node v ngoài R/P bằng
  `evaluate_cic(graph, R, P union {v}, ...)`, chọn mean rumor nhỏ nhất, lặp đúng k.
- Mean bằng nhau chính xác thì chọn label chuẩn hóa tăng dần. Không dừng sớm,
  không cắt candidate theo degree, không CELF/lazy hoặc giả định submodularity.
- Tất cả trials/steps dùng cùng S, base random seed và tie rule. Seed của
  simulation i vẫn là base+i theo evaluator hiện có. IC/CIC/MC không bị sửa.
- `Full` chỉ nghĩa là xét toàn bộ candidate mỗi bước, không phải tối ưu toàn cục
  trên tất cả tổ hợp k node. Các score đã dùng để chọn P không phải đánh giá hold-out.
- Candidate-Restricted Greedy có API/tên kết quả riêng, nhận pool cố định rõ ràng,
  không xóa node/cạnh khỏi graph; từ chối pool chứa R hoặc node không tồn tại.
- Với m candidates, k<=m, số evaluator calls chính xác E=k*m-k*(k-1)/2; số CIC
  simulations E*S. Full có m=|V|-|R|; restricted có m=|pool|. Công thức không
  phải runtime đo được. k=0 không gọi evaluator, không gán score giả cho P rỗng.
- Lưu P cuối, thứ tự chọn, P/score mỗi bước, score mọi ứng viên, số calls,
  runtime toàn bộ search và tổng runtime evaluator tách riêng. Không giữ toàn
  bộ node sets/raw simulations của mọi trial trong bộ nhớ.
- Pilot: Full Greedy chỉ trên graph nhỏ tính tay; email-Eu-core dùng Candidate-
  Restricted Greedy với top-10 out-degree ngoài R làm pool, R=[0], k=2, p=0.05,
  S=20, base seed=100000, protector-priority. Preflight 19 calls/380 simulations
  mỗi search; replay là một search riêng và được đếm riêng. Full email ở cùng
  k/S cần 2007 calls/40140 simulations, không được thực thi trong pilot.
- S=20 chỉ kiểm tra chạy được, không thay thế khuyến nghị độ chính xác của 4A.
  Không benchmark Facebook/Wiki-Vote và chưa triển khai GA ở milestone này.

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
scipy==1.18.1
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

### Experiment Runner – Milestone 6

- API `load_experiment_config(path)` và `run_experiment(config)` trong
  `src/experiments/`; JSON strict, không thêm dependency. Nạp processed graph
  đã kiểm chứng, không chạy preprocessing hay sửa raw/processed/core APIs.
- Một config chứa một thuật toán hoặc danh sách để so sánh. Luôn có mốc
  No Intervention; cùng R/k/p/tie/S_eval cho các phương pháp trong run.
  R explicit hoặc random policy fixed/per_run; resolve đúng một lần trước selection.
- S_opt, S_eval, GA parameters, PageRank parameters và giới hạn tối ưu phải
  khai báo rõ. Mọi P được chốt trước khi chạy independent final evaluation.
  Fitness cố định/cache/elite của Milestone 5 giữ nguyên, không dùng hold-out
  để chọn protector seeds. No Intervention là ngoại lệ P rỗng khi k>0.
- Seed plan versioned: Cantor-pair (master, independent index) thành block
  width chẵn; nửa đầu optimization, nửa sau final. Mỗi S không vượt nửa width.
  Giữ width cố định trong study; các run có block tách biệt. SHA-256 domain
  riêng cho R sampling, Random và GA operators input. Final block của runner
  thay base hold-out gợi ý bởi GA API; raw final observations có thể bật để replay.
- Full Greedy chỉ chạy khi chi phí exact calls/simulations không vượt các
  limit khai báo. Candidate-Restricted là tên phương pháp riêng/pool rõ ràng.
  Preflight mọi optimizer trước bất kỳ selection/evaluation; không mặc định
  Full Greedy trên graph lớn, không tự chuyển phương pháp khi vượt giới hạn.
- Lưu config/results/summary/metadata/preflight/selection_details, convergence
  CSV cho GA và raw final CSV tùy chọn. Lưu đầy đủ R/P, seeds, source checksums,
  Python/libraries/OS/hardware/Git commit + dirty status; không ghi đè run cũ.
- Rumor std gốc ddof=0; bổ sung sample std/SE (null khi S_eval=1). Relative
  reduction undefined/null khi control_mean=0. Control đánh giá một lần;
  k=0 tham chiếu cùng control, không đếm thêm final calls/time.
- Timing tách loading/selection/final/write/overhead; total từ API entry đến
  xong primary artifacts, không gồm config parsing và final manifests/rename.
- `experiments/configs/runner_smoke_email.json` chỉ là smoke pilot nhẹ. Chưa
  chốt S/GA parameters cho nghiên cứu, chưa chạy main experiments hoặc chuyển
  sang Milestone 7. Hướng dẫn seed formula/schema đầy đủ trong README.

## 10. Mục tiêu Chương 3

### Pilot Protocol Validation sau Milestone 6

Đã thực hiện pilot kỹ thuật cả ba processed datasets theo yêu cầu mới, không
phải main experiments/parameter study. Báo cáo `PILOT_PROTOCOL_VALIDATION.md`;
compact CSV/JSON trong `docs/pilot_protocol_validation/`. Config đề xuất nằm ở
`experiments/configs/pilot_protocol_validation.json`, không phải main defaults.

R lấy mẫu đều từ actual node IDs bằng SHA-256 domain riêng, lưu trước mô phỏng:
email [577], Facebook [2162], Wiki [4341]. Giữ cùng R qua p/methods/repeats;
không lấy mẫu lại theo kết quả. Wiki R chỉ reachable 2 nodes nên pilot không
đại diện cho độ lan truyền của toàn dataset. Independent runs thay RNG thuật
toán/MC, không thay R. Ba smokes và 18 pilots đều thành công, Full Greedy vượt
cost limits được skipped tường minh, không thay bằng Restricted dưới tên Full.

337 tests pass; dữ liệu và core semantics không đổi. Runner có method-status
manifest đủ 7 methods và breakdown orchestration runtime. S_opt=20/S_eval=200,
GA N10/G10 đã khả thi về thời gian; chưa chốt độ chính xác. p=0.01 ít spread
trong các R hiện tại; p=0.05 email/Facebook có variance cao. Cần xác nhận thêm
rumor scenarios, error targets, S/GA parameters/run count trước main. Không
chuyển sang Milestone 7 theo yêu cầu giai đoạn này.

### Pilot 2 – Calibration, chưa main experiments

Báo cáo `PILOT_2_CALIBRATION.md`; compact artifacts `docs/pilot_2_calibration/`.
Reachability chính xác cho cả 12.159 nodes: email chủ yếu 1–2 hoặc 965–966;
Facebook tất cả 4.039; Wiki 1–10 hoặc 2.316–2.320. Không tồn tại medium strata
thật sự; không tạo giả bằng cách chia ties. Lấy mẫu đều theo actual IDs trong
các strata, lưu manifest trước outcomes; giữ low scenarios và Wiki [4341].

Control scan 11 R × p=.01/.03/.05/.10 × 2 batches, chọn calibration references
bằng No Intervention gate trước optimizer: email [926], Facebook [1180], Wiki
[1210], đều p=.03. Không dùng chất lượng GA/algorithm nào để chọn R/p.

16 optimization comparisons + 3 smokes, 2 independent accuracy batches tới
S_eval=2500 cho fixed P; actual 250.216 CIC, active phases 1.084,121 s; 361 tests
pass và 39 existing file checksums/14 data files không đổi. Facebook S_opt250
skipped do projection >300 s; Wiki không full S grid. Nested prefixes không
là independent batches. Accuracy t CIs/paired differences và solution/ranking
stability bổ sung SE; không dùng SE/n đơn lẻ. Email còn CI tương đối rộng,
Wiki S_opt100 còn training-validation gap. Main protocol vẫn là proposal cần
xác nhận; đề xuất extrapolated S_eval6000 email chưa được thực thi. Chưa chạy
Milestone 7 hoặc main experiments.

### Experimental Protocol v1 và chuẩn bị Milestone 7

`EXPERIMENT_PROTOCOL_V1.md` và `experiments/configs/experiment_protocol_v1.json`
cố định reference k5/p.03/protector-priority/S_opt100, S_eval mỗi batch
6000 email và 2500 Facebook/Wiki, hai final batches độc lập mỗi P. N10/G10,
rates .8/.1/tournament3/elite1/cache là reference khả thi, không phải tối ưu.
Development R926/1180/1210 dùng cùng giữa mọi cấu hình; R858/1555/2110 giữ
ngoài tuning GA cho validation sau. Low/legacy scenarios không bị loại.

Thiết kế OFAT 4 panels lần lượt population/generations/crossover/mutation:
9 unique profiles (12 panel rows) dùng chung physical baseline. Full270 runs/
7,3 triệu CIC vượt budget; reduced45 runs/1,026 triệu CIC mới là đề xuất.
Chỉ pilot N10/N20 trên email R926 và Wiki R1210 được thực thi: 8/8 GA runs,
154.200 CIC, 280,701 s; 379 tests pass. S_eval6000 nay đã đo trong scope pilot
hẹp, chưa bảo đảm mọi P/R. CI parameter effects qua hai GA repeats còn chứa0;
không winner selection. Không full parameter sweep hoặc main experiments.
Compact tables/preflight/pilot evidence: `docs/experiment_protocol_v1/`.

### Milestone 7 – Reduced Screen request và budget stop

`MILESTONE_7_REDUCED_SCREEN.md` / `docs/milestone_7_reduced_screen/` ghi ma trận
đọc trực tiếp Protocol v1: 9 unique profiles, Reduced chọn 5, reference thuộc
cả 4 panels. 45 v1 là tổng 5 profiles × 3 scenarios × 3 repeats; yêu cầu mới
5 repeats là 75 runs, 25 mỗi dataset/scenario. Giữ R926/1180/1210, k=5,
p=.03, S_opt=100 và S_eval/B=2 của v1.

Projection 10.985,164 s vượt cap 10.800 s dù calls/CIC vẫn fit. Theo điều kiện
A của user, đã dừng toàn bộ tại preflight: 0 completed screen runs, 75 explicit
skipped, không quality/convergence plots giả. Không tự nâng budget/giảm repeats
hoặc chọn matrix khác. Screen master=2026111108 tách pilot master=2026111107
và reserved main master=2026111109; validation scenarios được reserve.
389 tests pass, 44 existing file checksums/14 data files không đổi. Không có
evidence Reduced Screen mới để thay reference GA, không full design/main.

### Milestone 7 – Reduced Screen V2

Theo thiết kế mới được user xác nhận: đủ 9 profiles/4 panels ba mức, chỉ email
R926 (chọn từ reachability/No Intervention Pilot 2), 5 independent runs/profile:
45/45 GA thành công, không failed/skipped. Giữ k5/p.03/protector-priority,
S_opt100, S_eval6000/batch/B2 và reference v1. Mỗi GA có optimizer/fitness seeds
riêng; final schedules chung theo repetition giữa profiles, tách optimization.
Master V2=2026111110; main2026111109 và validation Rs không dùng trong V2.

Preflight upper 8.600 calls/1.450.000 CIC, projection gồm safety1.5+overhead300s
=2.898,246 s <10.800 s. Thực đo 3.243 calls/914.300 CIC, active runtime khoảng
1.116,95 s; 5.357 cache hits, 650 elite carries. Checkpoint atomic/resume giữ
budget cộng dồn, không chạy lại run hoàn tất. 695 convergence rows; audit
9.150 individuals và 600.000 final/control observations. Đã xuất CSV/JSON và
4 nhóm plots cùng convergence/quality-cost tại docs/milestone_7_reduced_screen_v2.

Cả 8 contrasts với reference có CI hiệu chỉnh Bonferroni chứa0: chưa đủ bằng
chứng thay reference. N20/N40 chỉ là ứng viên trade-off cần kiểm tra trên
development scenarios khác, không là hyperparameters tối ưu. Không suy rộng
population effect qua dataset khác; không chạy main/Full Design. 415 tests
pass, 44 protected file hashes/14 data files không đổi. Báo cáo
`MILESTONE_7_REDUCED_SCREEN_V2.md`; không ghi đè preflight v1 bị chặn trước đó.

### Cross-Scenario GA Configuration Confirmation

27/27 GA runs và18 shared-control batches thành công: N10/N20/N40 ×3 repeats
trên email R858/Facebook R1555/Wiki R2110. Đây là validation scenarios v1,
trước đó chỉ có No Intervention scan, nay đã consumed cho confirmation; không
tiếp tục coi là blind main holdouts. Giữ G10/rates .8/.1/tournament3/elite1/
cache, k5/p.03/protector-priority/S_opt100/S_eval6000 hoặc2500 mỗi batch/B2.

Preflight6.732 calls/930.000 CIC upper, forecast6.359,888s gồm safety/overhead
<10.800s; worker RSS cap2GiB, concurrency1. Thực đo3.362 calls/593.000CIC,
active2.163,03s, peakRSS177,8MiB; 3.370 cache hits,270 elite carries. Audit297
convergence rows,6.930 individuals,264.000 final/control observations. 443 tests
pass;44 protected/14 data files không đổi. Có checkpoint/resume không lặp work.

Cả6 family CIs của contrasts đều chứa0; giữ reference như practical candidate,
không chứng minh equivalence/optimality hoặc gộp effect giữa datasets. Email/
Wiki validation R có ít spread, n=3 còn yếu. Main proposal giữ N10/G10/.8/.1/
tournament3/elite1/cache; frozen v1 không bị sửa, chưa khóa/chạy main.

Confirmation master2026111111 tách main2026111109. Main R đề xuất mới bằng
topology-only: email[485]/[374],Facebook[714]/[2733],Wiki[1961]/[1795], chưa có
diffusion outcomes.60 seed slots reserve chỉ là slots, main repeats chưa chốt.
Báo cáo `CROSS_SCENARIO_GA_CONFIRMATION.md`, CSV/JSON/plots ở
docs/cross_scenario_ga_confirmation; không Main Experiments hoặc Full Design.

### Main Experiments Design Freeze & Computational Preflight

User đã khóa GA N10/G10/crossover.8/mutation.1/tournament3/elite1/cache,
S_opt100/k5/p.03/protector-priority. Sáu main R giữ nguyên: email485/374,
Facebook714/2733,Wiki1961/1795; topology/sampling/old-R exclusions được audit,
không chạy diffusion trên R mới. Wiki1961 d5 có analytic NI no-growth85,87%,
Wiki1795 d44 là26,18%; giữ cả hai. Low/legacy cũ vẫn ở supplementary manifest,
không được gọi lại là official blind holdouts.

Đề xuất5 repeats ×6R ×6methods =180 primary rows, thêm30 Full Greedy explicit
skipped do calls/CIC limits; tổng210 matrix rows. Final B2/S_eval6000 email,
2500 Facebook/Wiki theo v1. Exact upper4.560 calls/1.740.000CIC; runtime proxy
envelope gồm safety1.5+overhead300s =11.036,921s >10.800s, **STOPPED AT PREFLIGHT**.
Không tự giảm repeats: alternatives4≈8.889,537s,3≈6.742,153s chỉ proposal.
V1 cap sensitivity được giữ như conservative main ceiling, main allocation
chưa tự được xác nhận. Main calls/CIC=0; design/execution confirmation=false.

Statistical plan: paired rumor differences,30 scenario+15 within-dataset
equal-weight contrasts, Bonferroni family45; ratio-of-means spread reduction
với descriptive Fieller CI. Tách MC/algorithm variation, không cross-dataset
pooling hoặc equivalence claims khi CI chứa0. Chưa triển khai main all-method
two-batch/checkpoint adapter; existing one-batch runner không được gọi hai lần
để thay thế. 461 tests pass;64 existing file hashes/14 data files không đổi.
Báo cáo `MAIN_EXPERIMENTS_PROTOCOL.md`, config/CSV/JSON ở
docs/main_experiments_protocol; main chưa chạy, GA không retune.

### Main Experiments Protocol V2 — đã hoàn thành

User ngày12/11/2026 xác nhận4 independent runs/scenario, giữ6 main R, toàn bộ
GA/k/p/tie/S/B và cap10800s. Protocol5runs không ghi đè; V2 riêng tại
`MAIN_EXPERIMENTS_PROTOCOL_V2.md`, JSON cùng tên và docs/main_experiments_protocol_v2.
Preflight upper3648calls/1.392.000CIC, projected8889,537s,headroom1910,463s;
144primary results và24Full Greedy skipped. Adapter gọi dispatcher/evaluator
cũ, checkpoint144 selections trước288 final batches, có selection barrier.

Main hoàn tất 144/144 result rows, 0 failed; 24 Full Greedy rows skipped do
chi phí. Actual 2.058 evaluator calls/1.233.000 CIC, active 4.436,312 s trong
cap 10.800 s; cache hits 1.590, peak worker 205,8 MiB. Final 288 batches có
1.056.000 observations độc lập với optimization. 493/493 tests pass; 67 tệp
được bảo vệ, gồm 14 data files, cùng các artifact cũ giữ checksum/topology.
Resume không tạo thêm worker/CIC; numeric reaggregation bit-identical, không
rerun main để kiểm tra. Family45 có 9 effects phân biệt được, 36 chưa đủ bằng
chứng; không suy equivalence hoặc global winner. Giữ 19 reduction âm, không
retune GA/R hoặc thêm experiments. Báo cáo MAIN_EXPERIMENTS_RESULTS.md và
docs/main_experiments_results; raw/checkpoint ở results/main_experiments_v2.
Các mục trên là lịch sử.

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
