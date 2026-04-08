from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

import numpy as np
import streamlit as st
from PIL import Image, ImageDraw, ImageFont


# A4 at ~300 DPI for clear print quality.
A4_WIDTH = 2480
A4_HEIGHT = 3508
PAGE_MARGIN = 90
HEADER_HEIGHT = 180


@dataclass
class Item:
    style_no: str
    qty: int
    image_bytes: bytes


@dataclass
class BoxSheet:
    box_no: str
    items: List[Item]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("Arial Unicode.ttf", "Arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_image(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    src = img.convert("RGB")
    scale = min(max_w / src.width, max_h / src.height)
    new_size = (max(1, int(src.width * scale)), max(1, int(src.height * scale)))
    return src.resize(new_size, Image.Resampling.LANCZOS)


def _ocr_extract_style(image_bytes: bytes) -> str:
    """
    Try OCR and return likely style code like 3Y-56465.
    Falls back to empty string if OCR is unavailable or not recognized.
    """
    try:
        import pytesseract  # type: ignore
    except Exception:
        return ""

    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            gray = img.convert("L")
            text = pytesseract.image_to_string(gray, lang="eng")
    except Exception:
        return ""

    normalized = text.replace(" ", "").replace("_", "-").replace("—", "-").upper()
    # Prefer codes that look like "3Y-56465" / "YF-56405"
    patterns = [
        r"\b[A-Z0-9]{1,4}-[A-Z0-9]{3,8}\b",
        r"\b[A-Z]{1,3}[0-9]{2,8}[A-Z]{0,2}\b",
    ]
    for p in patterns:
        m = re.search(p, normalized)
        if m:
            return m.group(0)
    return ""


def _group_consecutive(nums: List[int], max_gap: int = 2) -> List[List[int]]:
    if not nums:
        return []
    groups: List[List[int]] = [[nums[0]]]
    for n in nums[1:]:
        if n - groups[-1][-1] <= max_gap:
            groups[-1].append(n)
        else:
            groups.append([n])
    return groups


def _detect_grid_lines(gray: np.ndarray, axis: int, dark_threshold: int, min_dark_ratio: float) -> List[int]:
    """
    Return line centers along one axis:
      axis=0 -> detect vertical lines (scan columns)
      axis=1 -> detect horizontal lines (scan rows)
    """
    if axis == 0:
        # column dark ratio across rows
        dark_ratio = (gray < dark_threshold).mean(axis=0)
    else:
        # row dark ratio across cols
        dark_ratio = (gray < dark_threshold).mean(axis=1)
    candidate = [i for i, v in enumerate(dark_ratio) if v >= min_dark_ratio]
    groups = _group_consecutive(candidate, max_gap=2)
    return [int(sum(g) / len(g)) for g in groups if len(g) >= 2]


def _slice_big_sheet(
    image_bytes: bytes,
    dark_threshold: int = 85,
    min_dark_ratio: float = 0.55,
    min_cell_w: int = 70,
    min_cell_h: int = 70,
) -> List[bytes]:
    """
    Try to cut a catalog sheet image by detecting table/grid lines.
    Returns cropped image bytes for each cell (PNG), filtered by cell size.
    """
    with Image.open(io.BytesIO(image_bytes)) as src:
        rgb = src.convert("RGB")
    arr = np.asarray(rgb)
    gray = (0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]).astype(np.uint8)

    v_lines = _detect_grid_lines(gray, axis=0, dark_threshold=dark_threshold, min_dark_ratio=min_dark_ratio)
    h_lines = _detect_grid_lines(gray, axis=1, dark_threshold=dark_threshold, min_dark_ratio=min_dark_ratio)

    if len(v_lines) < 2 or len(h_lines) < 2:
        return []

    crops: List[bytes] = []
    for r in range(len(h_lines) - 1):
        y1, y2 = h_lines[r], h_lines[r + 1]
        for c in range(len(v_lines) - 1):
            x1, x2 = v_lines[c], v_lines[c + 1]
            w, h = x2 - x1, y2 - y1
            if w < min_cell_w or h < min_cell_h:
                continue

            # keep center area and avoid border lines/text bands too much
            pad_x = max(2, int(w * 0.03))
            pad_y = max(2, int(h * 0.08))
            crop = rgb.crop((x1 + pad_x, y1 + pad_y, x2 - pad_x, y2 - pad_y))

            buf = io.BytesIO()
            crop.save(buf, format="PNG")
            crops.append(buf.getvalue())
    return crops


def _image_content_score(image_bytes: bytes) -> float:
    """
    Heuristic: lower values are likely blank/light cells.
    """
    with Image.open(io.BytesIO(image_bytes)) as im:
        gray = np.asarray(im.convert("L"))
    return float((gray < 210).mean())


def _draw_table_grid(
    draw: ImageDraw.ImageDraw,
    left: int,
    top: int,
    table_w: int,
    table_h: int,
    cols: int,
    rows: int,
) -> tuple[int, int]:
    cell_w = table_w // cols
    cell_h = table_h // rows
    right = left + table_w
    bottom = top + table_h
    draw.rectangle([(left, top), (right, bottom)], outline="#444", width=3)
    for c in range(1, cols):
        x = left + c * cell_w
        draw.line([(x, top), (x, bottom)], fill="#666", width=2)
    for r in range(1, rows):
        y = top + r * cell_h
        draw.line([(left, y), (right, y)], fill="#666", width=2)
    return cell_w, cell_h


def _render_box_pages(box: BoxSheet, *, cols: int, rows: int, image_only: bool) -> List[Image.Image]:
    pages: List[Image.Image] = []
    items_per_page = cols * rows
    pages_needed = max(1, (len(box.items) + items_per_page - 1) // items_per_page)

    content_w = A4_WIDTH - PAGE_MARGIN * 2
    header_h = 0 if image_only else HEADER_HEIGHT
    content_h = A4_HEIGHT - PAGE_MARGIN * 2 - header_h
    text_top_h = 0 if image_only else 44
    text_bottom_h = 0 if image_only else 44
    table_top = PAGE_MARGIN + header_h
    table_h = content_h
    image_pad = 8

    title_font = _font(58)
    sub_font = _font(38)
    style_font = _font(24)
    qty_font = _font(28)

    for page_idx in range(pages_needed):
        page = Image.new("RGB", (A4_WIDTH, A4_HEIGHT), "white")
        draw = ImageDraw.Draw(page)

        if not image_only:
            title = f"箱号 / Box No: {box.box_no}"
            draw.text((PAGE_MARGIN, PAGE_MARGIN - 10), title, fill="black", font=title_font)
            subtitle = f"页码: {page_idx + 1}/{pages_needed}"
            draw.text((PAGE_MARGIN, PAGE_MARGIN + 74), subtitle, fill="black", font=sub_font)
            draw.text((A4_WIDTH - PAGE_MARGIN - 520, PAGE_MARGIN + 74), "款式目录 / Packing List", fill="black", font=sub_font)
            cell_w, cell_h = _draw_table_grid(
                draw,
                PAGE_MARGIN,
                table_top,
                content_w,
                table_h,
                cols,
                rows,
            )
        else:
            cell_w = content_w // cols
            cell_h = table_h // rows
        image_h = cell_h - text_top_h - text_bottom_h - image_pad * 2

        start = page_idx * items_per_page
        end = min(start + items_per_page, len(box.items))
        page_items = box.items[start:end]

        for i, item in enumerate(page_items):
            row = i // cols
            col = i % cols
            x = PAGE_MARGIN + col * cell_w
            y = table_top + row * cell_h

            with Image.open(io.BytesIO(item.image_bytes)) as raw:
                fitted = _fit_image(raw, cell_w - 12, image_h)
                ix = x + (cell_w - fitted.width) // 2
                iy = y + text_top_h + image_pad + (image_h - fitted.height) // 2
                page.paste(fitted, (ix, iy))

            if not image_only:
                style_text = item.style_no.strip() or "-"
                style_w = draw.textlength(style_text, font=style_font)
                draw.text((x + (cell_w - style_w) / 2, y + 8), style_text, fill="black", font=style_font)

                qty_text = str(item.qty)
                qty_w = draw.textlength(qty_text, font=qty_font)
                draw.text((x + (cell_w - qty_w) / 2, y + cell_h - text_bottom_h + 4), qty_text, fill="black", font=qty_font)

        pages.append(page)

    return pages


def _build_pdf_bytes(boxes: List[BoxSheet], *, cols: int, rows: int, image_only: bool) -> bytes:
    all_pages: List[Image.Image] = []
    for box in boxes:
        all_pages.extend(_render_box_pages(box, cols=cols, rows=rows, image_only=image_only))

    if not all_pages:
        blank = Image.new("RGB", (A4_WIDTH, A4_HEIGHT), "white")
        all_pages = [blank]

    pdf_io = io.BytesIO()
    all_pages[0].save(
        pdf_io,
        format="PDF",
        resolution=300.0,
        save_all=True,
        append_images=all_pages[1:],
    )
    pdf_io.seek(0)
    return pdf_io.getvalue()


def _default_style_name(filename: str) -> str:
    return Path(filename).stem.strip() or "未命名款号"


def main() -> None:
    st.set_page_config(page_title="箱单图片转PDF", layout="wide")
    st.title("箱单图片自动整理并生成A4 PDF")
    st.caption("流程: 输入箱号 -> 上传该箱款图 -> 填写款号与数量 -> 加入箱单 -> 导出PDF")

    if "boxes" not in st.session_state:
        st.session_state.boxes = []
    if "autofill_done" not in st.session_state:
        st.session_state.autofill_done = False

    st.sidebar.subheader("PDF版式")
    pdf_cols = st.sidebar.slider("每行几列", min_value=3, max_value=6, value=5, step=1)
    pdf_rows = st.sidebar.slider("每页几行", min_value=4, max_value=8, value=6, step=1)
    pdf_image_only = st.sidebar.checkbox("仅输出排列图片（无箱号/款号/数量）", value=False)

    st.subheader("1) 当前箱信息")
    box_no = st.text_input("箱号 (例如: 3Y-56465)", key="current_box_no")

    st.markdown("### 可选: 一键切分整张目录图")
    big_sheet = st.file_uploader(
        "上传整张目录图（像你发的那种整页图）",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=False,
        key="big_sheet_file",
    )
    if big_sheet is not None:
        c_cfg1, c_cfg2, c_cfg3 = st.columns(3)
        with c_cfg1:
            detect_dark = st.slider("线条识别-暗色阈值", min_value=40, max_value=160, value=85, step=1)
        with c_cfg2:
            detect_ratio = st.slider("线条识别-占比阈值", min_value=0.20, max_value=0.90, value=0.55, step=0.01)
        with c_cfg3:
            min_content = st.slider("过滤空白格阈值", min_value=0.01, max_value=0.30, value=0.06, step=0.01)

        if st.button("自动切分整图并加入当前箱"):
            sliced = _slice_big_sheet(
                big_sheet.getvalue(),
                dark_threshold=detect_dark,
                min_dark_ratio=detect_ratio,
            )
            if not sliced:
                st.warning("没有识别到稳定网格线，请调高/调低参数后重试，或改用手动多图上传。")
            else:
                filtered = [b for b in sliced if _image_content_score(b) >= min_content]
                if not filtered:
                    st.warning("识别到了网格，但过滤后没有有效图片。可下调“过滤空白格阈值”。")
                else:
                    st.session_state.current_box_files = []
                    st.session_state.autofill_done = False
                    st.session_state["_auto_sliced_items"] = filtered
                    st.success(f"切分完成：共识别 {len(filtered)} 张有效小图，已载入当前箱编辑区。")

    uploaded = st.file_uploader(
        "上传该箱所有款图 (可多选，支持 JPG/PNG/WEBP)",
        type=["jpg", "jpeg", "png", "webp"],
        accept_multiple_files=True,
        key="current_box_files",
    )

    current_items: List[Item] = []
    sliced_items: List[bytes] = st.session_state.get("_auto_sliced_items", [])
    if uploaded or sliced_items:
        st.info("OCR自动识别需要本机安装 Tesseract。若未安装，仍可手动输入款号。")
        autofill_clicked = st.button("尝试OCR自动填充款号")
        if autofill_clicked:
            st.session_state.autofill_done = True

        st.markdown("### 2) 填写每款信息")
        cols = st.columns(3)
        normalized: List[tuple[str, bytes]] = []
        for f in uploaded:
            normalized.append((f.name, f.getvalue()))
        for i, b in enumerate(sliced_items, start=1):
            normalized.append((f"auto_slice_{i}.png", b))

        for idx, (fname, fbytes) in enumerate(normalized):
            col = cols[idx % 3]
            with col:
                st.image(fbytes, use_container_width=True)
                auto_style = ""
                if st.session_state.autofill_done:
                    auto_style = _ocr_extract_style(fbytes)
                default_name = auto_style or _default_style_name(fname)
                style = st.text_input(
                    f"款号 #{idx + 1}",
                    value=default_name,
                    key=f"style_{idx}_{fname}",
                )
                qty = st.number_input(
                    f"数量 #{idx + 1}",
                    min_value=0,
                    value=0,
                    step=1,
                    key=f"qty_{idx}_{fname}",
                )
                current_items.append(Item(style_no=style, qty=int(qty), image_bytes=fbytes))

    add_disabled = (not box_no.strip()) or (len(current_items) == 0)
    if st.button("加入该箱到待导出列表", disabled=add_disabled, type="primary"):
        st.session_state.boxes.append(BoxSheet(box_no=box_no.strip(), items=current_items))
        st.session_state.autofill_done = False
        st.session_state["_auto_sliced_items"] = []
        st.success(f"已加入箱号 {box_no.strip()}，共 {len(current_items)} 款。")

    st.divider()
    st.subheader("3) 待导出箱单")
    boxes: List[BoxSheet] = st.session_state.boxes

    if not boxes:
        st.info("还没有箱单。先在上方加入至少一个箱子。")
    else:
        for i, b in enumerate(boxes, start=1):
            total_qty = sum(it.qty for it in b.items)
            st.write(f"{i}. 箱号: {b.box_no} | 款数: {len(b.items)} | 总顶数: {total_qty}")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("清空待导出列表"):
                st.session_state.boxes = []
                st.rerun()

        with c2:
            pdf_bytes = _build_pdf_bytes(boxes, cols=pdf_cols, rows=pdf_rows, image_only=pdf_image_only)
            filename = f"box_sheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            st.download_button(
                "生成并下载A4 PDF",
                data=pdf_bytes,
                file_name=filename,
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
