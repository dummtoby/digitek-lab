import threading
import time


class FishbotOverlay:
    def __init__(self, bbox, magic_value, stop_callback, error_callback=None, ready_callback=None, object_mode=False):
        self._bbox = self._normalize_bbox(bbox)
        self._magic_value = int(magic_value or 100)
        self._stop_callback = stop_callback
        self._error_callback = error_callback
        self._ready_callback = ready_callback
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._frame = None
        self._percent = 100.0
        self._detected = False
        self._object_box = None
        self._object_mode = bool(object_mode)
        self._thread = threading.Thread(target=self._run, name="FishbotOverlay", daemon=True)
        self._thread.start()

    def update(self, image, percent, detected, magic_value=None, object_box=None, object_mode=None):
        with self._lock:
            self._frame = image.copy()
            self._percent = float(percent or 0)
            self._detected = bool(detected)
            if magic_value is not None:
                self._magic_value = int(magic_value or 100)
            self._object_box = object_box if object_box and len(object_box) == 4 else None
            if object_mode is not None:
                self._object_mode = bool(object_mode)

    def close(self):
        self._closed.set()

    def object_mode(self):
        with self._lock:
            return bool(self._object_mode)

    def _run(self):
        try:
            import tkinter as tk
            from PIL import Image, ImageDraw, ImageTk
        except Exception as exc:
            self._report_error(exc)
            return

        try:
            width = 460
            height = 300
            toolbar_h = 28

            root = tk.Tk()
            root.withdraw()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.configure(bg="#111111")
            root.geometry(f"{width}x{height + toolbar_h}+0+0")

            drag = {"x": 0, "y": 0}

            toolbar = tk.Frame(root, bg="#464646", height=toolbar_h)
            toolbar.pack(side="top", fill="x")
            toolbar.pack_propagate(False)

            percent_label = tk.Label(toolbar, text="W/B: 0.0%", bg="#464646", fg="white", font=("Segoe UI", 9))
            percent_label.pack(side="left", padx=(8, 4))

            object_btn = tk.Button(
                toolbar,
                text="Object: Off",
                command=lambda: toggle_object_mode(),
                bg="#5a5a5a",
                fg="white",
                activebackground="#707070",
                activeforeground="white",
                bd=0,
                padx=8,
                pady=1,
                font=("Segoe UI", 8),
            )
            object_btn.pack(side="left", padx=4, pady=4)

            stop_btn = tk.Button(
                toolbar,
                text="■",
                command=self._request_stop,
                bg="#5a5a5a",
                fg="white",
                activebackground="#707070",
                activeforeground="white",
                bd=0,
                padx=8,
                pady=1,
                font=("Segoe UI", 9),
            )
            stop_btn.pack(side="right", padx=6, pady=4)

            preview = tk.Label(root, bg="black", bd=0)
            preview.pack(side="top", fill="both", expand=True)
            preview.image_ref = None

            def begin_drag(event):
                drag["x"] = event.x_root - root.winfo_x()
                drag["y"] = event.y_root - root.winfo_y()

            def drag_window(event):
                root.geometry(f"+{event.x_root - drag['x']}+{event.y_root - drag['y']}")

            toolbar.bind("<ButtonPress-1>", begin_drag)
            toolbar.bind("<B1-Motion>", drag_window)
            percent_label.bind("<ButtonPress-1>", begin_drag)
            percent_label.bind("<B1-Motion>", drag_window)

            def toggle_object_mode():
                with self._lock:
                    self._object_mode = not self._object_mode

            def tick():
                if self._closed.is_set():
                    root.destroy()
                    return
                frame, percent, detected, magic_value, object_box, object_mode = self._snapshot()
                if frame is not None:
                    gray = frame.convert("L")
                    threshold = max(0, min(255, int(magic_value)))
                    frame = gray.point(lambda px: 0 if px <= threshold else 255).convert("RGB")
                    resample = getattr(getattr(Image, "Resampling", Image), "BILINEAR")
                    src_w, src_h = frame.size
                    scale = min(width / float(max(1, src_w)), height / float(max(1, src_h)))
                    view_w = max(1, int(src_w * scale))
                    view_h = max(1, int(src_h * scale))
                    offset_x = (width - view_w) // 2
                    offset_y = (height - view_h) // 2
                    frame = frame.resize((view_w, view_h), resample)
                    canvas = Image.new("RGB", (width, height), "black")
                    canvas.paste(frame, (offset_x, offset_y))
                    frame = canvas
                    draw = ImageDraw.Draw(frame)
                    if object_mode and object_box:
                        x1, y1, x2, y2 = object_box
                        rect = [
                            offset_x + int(x1 * scale),
                            offset_y + int(y1 * scale),
                            offset_x + int(x2 * scale),
                            offset_y + int(y2 * scale),
                        ]
                        for offset in range(2):
                            draw.rectangle(
                                [rect[0] - offset, rect[1] - offset, rect[2] + offset, rect[3] + offset],
                                outline="#38bdf8",
                            )
                    status = "Detected" if detected else "Not detected"
                    color = "#22c55e" if detected else "#ef4444"
                    draw.text((9, 8), status, fill="black")
                    draw.text((8, 7), status, fill=color)
                    photo = ImageTk.PhotoImage(frame)
                    preview.configure(image=photo)
                    preview.image_ref = photo
                    percent_label.configure(text=f"W/B: {percent:.1f}%")
                    object_btn.configure(
                        text="Object: On" if object_mode else "Object: Off",
                        bg="#2563eb" if object_mode else "#5a5a5a",
                    )
                root.after(80, tick)

            root.deiconify()
            self._report_ready()
            root.after(80, tick)
            root.mainloop()
        except Exception as exc:
            self._report_error(exc)

    def _request_stop(self):
        self._closed.set()
        threading.Thread(target=self._stop_callback, name="FishbotOverlayStop", daemon=True).start()

    def _snapshot(self):
        with self._lock:
            return (
                self._frame,
                self._percent,
                self._detected,
                self._magic_value,
                self._object_box,
                self._object_mode,
            )

    def _report_error(self, exc):
        if self._error_callback:
            self._error_callback(str(exc))

    def _report_ready(self):
        if self._ready_callback:
            self._ready_callback()

    def _normalize_bbox(self, bbox):
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            return [0, 0, 800, 600]
        left, right, top, bottom = [int(v) for v in bbox]
        return [min(left, right), min(top, bottom), max(left, right), max(top, bottom)]
