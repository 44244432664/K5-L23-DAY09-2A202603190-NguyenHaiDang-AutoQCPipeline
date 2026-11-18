"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line  # noqa: F401
from ..model_cache import get_preds  # noqa: F401


def run(ds, cfg, preds=None):
    # TODO
    if preds is None:
        preds = get_preds(ds, cfg, "checker")

    thresholds = cfg["second_opinion"]
    issues = []

    for image_path in ds.image_files():
        stem = image_path.stem
        if stem not in preds or not ds.label_path(stem).exists():
            continue

        numbered_labels = []
        for line_no, text in ds.read_label_lines(stem) or []:
            try:
                label = parse_yolo_line(text)
            except (ValueError, OverflowError):
                continue
            if 0 <= label[0] < len(ds.classes):
                numbered_labels.append((line_no, label))

        image_size = ds.image_size(stem)
        prediction_pool = []
        support_pool = []

        for prediction in preds[stem]:
            class_id, confidence, cx, cy, width, height = prediction
            box = (cx, cy, width, height)

            if confidence >= thresholds["fp_conf"]:
                support_pool.append((class_id, confidence, box))

            if image_size is None:
                continue
            image_width, image_height = image_size
            area_px = width * image_width * height * image_height
            if (
                confidence >= thresholds["conf"]
                and area_px >= thresholds["min_area_px"]
            ):
                prediction_pool.append((class_id, confidence, box))

        for predicted_class, confidence, predicted_box in prediction_pool:
            candidates = []
            for _, label in numbered_labels:
                label_class, *label_box = label
                overlap = iou_xywh(predicted_box, label_box)
                if overlap >= thresholds["iou_missing"]:
                    candidates.append((label_class, overlap))

            if not candidates:
                issues.append(Issue(
                    "second_opinion", WARN, "POSSIBLE_MISSING", stem,
                    f"model thấy lớp {predicted_class} nhưng không có box nhãn "
                    f"khớp (conf={confidence:.4f})",
                    extra={"conf": confidence},
                ))
                continue

            same_class_ious = [
                overlap
                for label_class, overlap in candidates
                if label_class == predicted_class
            ]
            if same_class_ious:
                best_same_class_iou = max(same_class_ious)
                if best_same_class_iou < thresholds["iou_loose"]:
                    issues.append(Issue(
                        "second_opinion", WARN, "POSSIBLE_LOOSE_BOX", stem,
                        f"box cùng lớp {predicted_class} khớp chưa chặt "
                        f"(IoU={best_same_class_iou:.4f}, "
                        f"conf={confidence:.4f})",
                        extra={
                            "conf": confidence,
                            "iou": best_same_class_iou,
                        },
                    ))
                continue

            best_other_class_iou = max(
                overlap for _, overlap in candidates
            )
            if best_other_class_iou >= thresholds["iou_match"]:
                issues.append(Issue(
                    "second_opinion", WARN, "POSSIBLE_WRONG_CLASS", stem,
                    f"model dự đoán lớp {predicted_class} nhưng box khớp "
                    f"một nhãn lớp khác (IoU={best_other_class_iou:.4f}, "
                    f"conf={confidence:.4f})",
                    extra={
                        "conf": confidence,
                        "iou": best_other_class_iou,
                    },
                ))

        for line_no, label in numbered_labels:
            _, *label_box = label
            support_ious = [
                iou_xywh(label_box, predicted_box)
                for _, _, predicted_box in support_pool
            ]
            best_support_iou = max(support_ious, default=0.0)
            if best_support_iou < thresholds["iou_missing"]:
                issues.append(Issue(
                    "second_opinion", WARN, "POSSIBLE_FALSE_POS", stem,
                    f"box nhãn ở dòng {line_no} không khớp dự đoán nào "
                    f"(IoU tốt nhất={best_support_iou:.4f})",
                    line=line_no,
                    extra={"iou": best_support_iou},
                ))

    return issues
    # raise NotImplementedError("check second_opinion chưa làm")
