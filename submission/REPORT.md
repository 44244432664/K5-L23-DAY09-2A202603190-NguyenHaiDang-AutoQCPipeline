# Báo cáo Day 09 — Nguyễn Hải Đăng, 2A202603190

## 1. Kết luận trước

Pipeline kết luận **Release**. Hệ thống quét 224 ảnh thô, loại 19 ảnh ở intake và xuất 205 ảnh trong `clean_v1`. Sau autofix và bước duyệt mô phỏng trên 80 ảnh, danh sách v3 còn **0 ERROR**, 31 WARN; 16/205 ảnh chưa duyệt còn cảnh báo (7,80%), thấp hơn ngưỡng Hold 10%. Release là đạt chính sách cửa chặn, không đồng nghĩa mọi nhãn đã được xác nhận đúng.

## 2. Lỗi và phân việc

Số liệu dưới đây lấy từ `02_error_list_v1.csv`; lỗi intake được tính trong cùng báo cáo v1. Cột “người” mô tả trách nhiệm xử lý ngữ nghĩa; lần chạy này thực hiện bước đó bằng script duyệt mô phỏng được cung cấp.

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| `CORRUPT_IMAGE` | 2 ảnh | máy | Ảnh không đọc được nên loại khỏi bản làm việc |
| `BAD_SIZE` | 3 ảnh | máy | Ảnh nhỏ hơn kích thước tối thiểu |
| `DUP_IMAGE_EXACT` | 8 ảnh | máy | Trùng byte, giữ bản xuất hiện trước |
| `DUP_IMAGE_NEAR` | 2 ảnh | máy | Trùng gần theo pHash đã calibrate |
| `LEAK_TEST` | 4 ảnh | máy | Trùng kho test/validation nên phải loại |
| `MISSING_LABEL_FILE` | 6 ảnh | người | Máy chỉ ghi `needs_label`, không được bịa nhãn |
| `EMPTY_LABEL` | 12 ảnh | người | Có thể là ảnh nền hoặc nhãn chưa hoàn thành |
| `BAD_FORMAT` | 3 dòng | máy | Xoá dòng YOLO không parse được |
| `BAD_CLASS_ID` | 6 dòng | máy | Xoá dòng có ID ngoài 0–3 |
| `BOX_ZERO` | 4 dòng | máy | Xoá box có cạnh không dương |
| `BOX_OUT_OF_IMAGE` | 8 dòng | máy | Cắt hình chữ nhật về giao với ảnh |
| `DUP_BOX` | 7 dòng | máy | Xoá box cùng lớp bị lặp |
| `BAD_CLASS_NAME` | 2 phát hiện | máy | Ghi lại thứ tự `car, person, truck, bus` |
| `BOX_TINY` | 6 dòng | người | Box nhỏ là cảnh báo ngữ nghĩa, không tự xoá |
| `BOX_HUGE` | 3 dòng | người | Box quá lớn cần người xác nhận |
| `CLASS_RARE` | 4 lớp | người | Cần xem lại phân bố, không tự tạo thêm nhãn |
| `POSSIBLE_MISSING` | 32 cảnh báo | người | Model lớn thấy vật chưa có box khớp |
| `POSSIBLE_WRONG_CLASS` | 14 cảnh báo | người | Model và nhãn bất đồng lớp |
| `POSSIBLE_LOOSE_BOX` | 12 cảnh báo | người | Cùng lớp nhưng IoU chưa đủ chặt |
| `POSSIBLE_FALSE_POS` | 29 cảnh báo | người | Box nhãn không có dự đoán hỗ trợ |

Autofix tạo 35 bản ghi: 20 `drop_line`, 8 `clip_box`, 1 `rename_classes`, 6 `needs_label`. Hàng đợi có 102 ảnh. Ảnh đầu `img_0020` đạt 11,524 điểm do cộng tín hiệu `FIXED_DROP_LINE`, `POSSIBLE_MISSING`, `POSSIBLE_WRONG_CLASS`; nhóm thiếu nhãn có `NEEDS_LABEL=10`. Trong ngân sách 80 ảnh, script mô phỏng xử lý 68 ảnh có cảnh báo ngữ nghĩa, tương ứng 77 cặp (ảnh, mã `POSSIBLE_*`) phân biệt trong log, không phải 77 lỗi đã được xác nhận.

## 3. Calibration (2 ngưỡng)

| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do |
|---|---:|---:|---|---|
| `duplicates.phash_dist` | 2 | **4** | `DUP_IMAGE_NEAR`: 1,00/0,50 → 1,00/0,67 (F1 0,67 → 0,80) | Tăng recall nhưng giữ ngưỡng bảo thủ vì xoá nhầm ảnh là phá huỷ dữ liệu |
| `second_opinion.conf` | 0,25 | **0,8** | WRONG_CLASS: 0,56/0,83 → 1,00/0,83; MISSING: 0,50/1,00 → 0,67/0,75 | Tăng độ tin cậy và giảm tải duyệt; chấp nhận mất 2/8 lỗi MISSING trong calibration và ghi rõ điểm mù |

Calibration có thể đánh lừa vì bộ đo chỉ có 39 ảnh. `phash_dist=16` đạt precision 1,00 và recall 0,83 trên calibration nhưng đối chiếu ảnh raw cho thấy ghép nhầm `img_0011`/`img_0008` (tennis/ski) và `img_0177`/`img_0113` (lướt sóng/người ngồi bàn). Vì vậy ngưỡng cuối là 4; các cặp distance 0 được đối chiếu là cùng cảnh được resize/crop. Việc tăng `conf` cũng làm một số lỗi biến mất khỏi báo cáo do lọc dự đoán, không phải vì nhãn đã được sửa; mức giảm recall trong bảng là đánh đổi cần theo dõi.

## 4. Cửa chặn và điều pipeline không bắt được

Thí nghiệm `--budget 0` trong `work/task_validation/no_review/` trả **Rework**, mã 20: còn 6 `MISSING_LABEL_FILE`, `exported=null`, và không có `export/clean_v1/manifest.json`. Đây là bằng chứng đã lưu ở cấu hình khởi đầu (pHash 2, conf 0,25), không phải lần chạy zero-review mới ở cấu hình cuối. Các test e2e kiểm tra thêm việc chặn khi thiếu nhãn. Ở lần chạy chính với pHash 4, conf 0,8, 0 ERROR và chỉ 16/205 ảnh chưa duyệt còn WARN nên gate trả **Release**, mã 0.

Các điểm mù có bằng chứng:

1. Ở `conf=0.8`, `POSSIBLE_MISSING` chỉ recall 0,75 và `POSSIBLE_LOOSE_BOX` recall 0,20; model lớn vẫn có thể bỏ sót vật hoặc box lỏng.
2. `POSSIBLE_FALSE_POS` có precision 0,31 dù recall 1,00, nên nhiều cảnh báo là báo động giả và bắt buộc cần người xem.
3. pHash có thể cho khoảng cách nhỏ với ảnh khác nội dung; kiểm tra trực quan raw đã ngăn lựa chọn ngưỡng 16 quá mạnh.

## 5. Train: raw vs clean

**Chưa chạy.** Phần train là tùy chọn và cần môi trường GPU/Colab
## 6. Quyết định và ghi chú AI

Quyết định cuối: **Release**. Bản xuất có 205 ảnh, manifest ghi Release, 0 lỗi bắt buộc và tỉ lệ cảnh báo chưa duyệt 7,80%. Nếu dữ liệu hoặc cấu hình thay đổi phải chạy lại test, calibration và pipeline; không được giữ quyết định cũ.

- **Prompt chính:** yêu cầu AI tạo kế hoạch, break-down task, duyệt, rồi triển khai lần lượt bốn module theo docstring/test, giữ nguyên template và ghi tài liệu kiểm chứng, sau đó tự kiểm tra và kiểm tra theo hướng người dùng đề nghị.
- **Cách kiểm:** đối chiếu diff và log thực thi: 79 test bảo vệ + 18 test synthetic, e2e, hai sweep calibration, hash file bảo vệ và ảnh nghi trùng; checker không sửa đổi chạy qua WSL đạt 0 lỗi, 1 cảnh báo bỏ qua train.
- **Một lần AI sai:** ban đầu AI chọn `phash_dist=16` vì F1 calibration cao; kiểm tra ảnh raw phát hiện cặp khác nội dung, nên sửa về 4 và sinh lại toàn bộ bằng chứng.
