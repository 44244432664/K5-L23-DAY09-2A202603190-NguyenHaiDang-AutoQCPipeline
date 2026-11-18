"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict  # noqa: F401

import yaml  # noqa: F401

from ..common import ERROR, parse_yolo_line  # noqa: F401


def fix(ds, issues, cfg):
    # TODO
    drop_codes = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
    remove_codes = {"LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}
    row_actions = defaultdict(lambda: defaultdict(set))
    remove_images = set()
    missing_labels = set()
    repair_names = False

    for issue in issues:
        if issue.severity != ERROR:
            continue

        if issue.code.startswith("DUP_IMAGE_") or issue.code in remove_codes:
            remove_images.add(issue.image)
        elif issue.code in drop_codes | {"BOX_OUT_OF_IMAGE"}:
            if isinstance(issue.line, int) and issue.line > 0:
                row_actions[issue.image][issue.line].add(issue.code)
        elif issue.code == "MISSING_LABEL_FILE":
            missing_labels.add(issue.image)
        elif issue.code == "BAD_CLASS_NAME":
            repair_names = True

    fixes = []
    removed_images = set(remove_images)

    for stem in sorted(remove_images):
        image_path = ds.image_path(stem)
        label_path = ds.label_path(stem)
        existing_paths = [
            path for path in (image_path, label_path)
            if path is not None and path.exists()
        ]
        if not existing_paths:
            continue

        before = ", ".join(path.name for path in existing_paths)
        for path in existing_paths:
            path.unlink()
        fixes.append({
            "image": stem,
            "line": None,
            "action": "remove_image",
            "before": before,
            "after": "đã xoá ảnh và nhãn khỏi dataset",
        })

    for stem in sorted(row_actions):
        if stem in removed_images:
            continue

        label_path = ds.label_path(stem)
        if not label_path.exists():
            continue

        with label_path.open(
            "r", encoding="utf-8", errors="replace", newline=""
        ) as label_file:
            original_text = label_file.read()
        original_lines = original_text.splitlines(keepends=True)
        rebuilt_lines = []
        pending_fixes = []
        changed = False

        for line_no, raw_line in enumerate(original_lines, 1):
            codes = row_actions[stem].get(line_no, set())
            before = raw_line.rstrip("\r\n")

            if codes & drop_codes:
                pending_fixes.append({
                    "image": stem,
                    "line": line_no,
                    "action": "drop_line",
                    "before": before,
                    "after": "(đã xoá dòng)",
                })
                changed = True
                continue

            if "BOX_OUT_OF_IMAGE" not in codes:
                rebuilt_lines.append(raw_line)
                continue

            try:
                class_id, cx, cy, width, height = parse_yolo_line(before)
            except (ValueError, OverflowError):
                rebuilt_lines.append(raw_line)
                continue

            left = max(0.0, cx - width / 2)
            right = min(1.0, cx + width / 2)
            top = max(0.0, cy - height / 2)
            bottom = min(1.0, cy + height / 2)

            if right <= left or bottom <= top:
                pending_fixes.append({
                    "image": stem,
                    "line": line_no,
                    "action": "drop_line",
                    "before": before,
                    "after": "(đã xoá dòng)",
                })
                changed = True
                continue

            clipped_width = right - left
            clipped_height = bottom - top
            clipped_cx = (left + right) / 2
            clipped_cy = (top + bottom) / 2
            after = " ".join([
                str(class_id),
                f"{clipped_cx:.12g}",
                f"{clipped_cy:.12g}",
                f"{clipped_width:.12g}",
                f"{clipped_height:.12g}",
            ])
            line_ending = raw_line[len(before):]
            rebuilt_lines.append(after + line_ending)
            pending_fixes.append({
                "image": stem,
                "line": line_no,
                "action": "clip_box",
                "before": before,
                "after": after,
            })
            changed = True

        if changed:
            with label_path.open(
                "w", encoding="utf-8", newline=""
            ) as label_file:
                label_file.write("".join(rebuilt_lines))
            fixes.extend(pending_fixes)

    if repair_names:
        yaml_data = {}
        if ds.yaml_path.exists():
            yaml_data = yaml.safe_load(
                ds.yaml_path.read_text(encoding="utf-8")
            ) or {}
        if not isinstance(yaml_data, dict):
            yaml_data = {}

        old_names = yaml_data.get("names")
        expected_names = list(cfg["classes"])
        if isinstance(old_names, list):
            names_are_correct = old_names == expected_names
        elif isinstance(old_names, dict):
            try:
                normalized_names = {
                    int(key): value for key, value in old_names.items()
                }
            except (TypeError, ValueError):
                normalized_names = {}
            names_are_correct = normalized_names == dict(enumerate(expected_names))
        else:
            names_are_correct = False

        if not names_are_correct:
            yaml_data["names"] = expected_names
            ds.yaml_path.write_text(
                yaml.safe_dump(
                    yaml_data,
                    allow_unicode=True,
                    sort_keys=False,
                ),
                encoding="utf-8",
            )
            fixes.append({
                "image": "data.yaml",
                "line": None,
                "action": "rename_classes",
                "before": repr(old_names),
                "after": repr(expected_names),
            })

    for stem in sorted(missing_labels - removed_images):
        if ds.image_path(stem) is None or ds.label_path(stem).exists():
            continue
        fixes.append({
            "image": stem,
            "line": None,
            "action": "needs_label",
            "before": "(không có file)",
            "after": "chuyển người gán",
        })

    return fixes
    # raise NotImplementedError("autofix chưa làm")
