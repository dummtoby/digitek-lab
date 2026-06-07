def pick_point():
    result = _run_picker("point")
    return [result["x"], result["y"]]


def pick_region():
    result = _run_picker("region")
    return [result["left"], result["right"], result["top"], result["bottom"]]


def _run_picker(mode):
    try:
        import tkinter as tk
    except Exception as exc:
        raise RuntimeError("Screen picker requires tkinter in DigiTek Lab's Python runtime.") from exc

    if mode not in {"point", "region"}:
        raise ValueError("Unsupported picker mode.")

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    root.attributes("-fullscreen", True)
    root.attributes("-alpha", 0.35)
    root.configure(bg="black")
    root.overrideredirect(True)

    width = root.winfo_screenwidth()
    height = root.winfo_screenheight()
    canvas = tk.Canvas(root, width=width, height=height, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)

    label = "Click the fishing bobber/click target" if mode == "point" else "Drag over the bobber detection region"
    canvas.create_text(
        width // 2,
        42,
        text=label + "  (Esc to cancel)",
        fill="white",
        font=("Segoe UI", 16, "bold"),
    )

    state = {"start": None, "rect": None, "result": None, "cancelled": False}

    def finish(value):
        state["result"] = value
        root.quit()

    def cancel(_event=None):
        state["cancelled"] = True
        root.quit()

    def on_down(event):
        if mode == "point":
            finish({"x": int(event.x_root), "y": int(event.y_root)})
            return
        state["start"] = (event.x_root, event.y_root)
        if state["rect"]:
            canvas.delete(state["rect"])
        state["rect"] = canvas.create_rectangle(
            event.x_root,
            event.y_root,
            event.x_root,
            event.y_root,
            outline="#44ff44",
            width=2,
            dash=(10, 5),
        )

    def on_drag(event):
        if mode != "region" or not state["start"] or not state["rect"]:
            return
        x1, y1 = state["start"]
        canvas.coords(state["rect"], x1, y1, event.x_root, event.y_root)

    def on_up(event):
        if mode != "region" or not state["start"]:
            return
        x1, y1 = state["start"]
        x2, y2 = event.x_root, event.y_root
        left, right = sorted((int(x1), int(x2)))
        top, bottom = sorted((int(y1), int(y2)))
        if right - left < 4 or bottom - top < 4:
            return
        finish({"left": left, "right": right, "top": top, "bottom": bottom})

    root.bind("<Escape>", cancel)
    canvas.bind("<ButtonPress-1>", on_down)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_up)
    root.deiconify()
    root.focus_force()
    root.mainloop()
    root.destroy()

    if state["cancelled"] or not state["result"]:
        raise RuntimeError("Picker cancelled.")
    return state["result"]
