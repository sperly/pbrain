"""Portrait OLED simulation using a one-bit framebuffer."""
from PIL import Image, ImageDraw, ImageFont, ImageTk

WIDTH, HEIGHT, SCALE = 128, 256, 2
BODY = ImageFont.load_default(size=10)
HEADER = ImageFont.load_default(size=12)
ROW = 14


def clipped(draw, text, width, font):
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "...", font=font) > width:
        text = text[:-1]
    return text + "..."


def wrap(draw, text, width):
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            yield ""
            continue
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if draw.textlength(candidate, font=BODY) <= width:
                line = candidate
                continue
            if line:
                yield line
                line = ""
            while draw.textlength(word, font=BODY) > width:
                end = 1
                while end < len(word) and draw.textlength(word[:end + 1], font=BODY) <= width:
                    end += 1
                yield word[:end]
                word = word[end:]
            line = word
        yield line


class OLED:
    def __init__(self, label):
        self.label = label
        self.photo = None
        self.max_scroll = 0

    def show(self, title, text, footer, scroll=0, menu=None, selected=0, progress=None):
        frame = Image.new("1", (WIDTH, HEIGHT))
        draw = ImageDraw.Draw(frame)
        draw.text((4, 3), clipped(draw, title, WIDTH - 8, HEADER), 1, font=HEADER)
        draw.line((0, 19, WIDTH, 19), 1)
        draw.line((0, HEIGHT - 21, WIDTH, HEIGHT - 21), 1)
        draw.text((4, HEIGHT - 17), clipped(draw, footer, WIDTH - 8, BODY), 1, font=BODY)
        rows = 14
        self.max_scroll = 0
        if menu is not None:
            start = max(0, selected - rows + 1)
            for index, caption in enumerate(menu[start:start + rows], start):
                y = 23 + ROW * (index - start)
                active = index == selected
                if active:
                    draw.rectangle((1, y - 1, WIDTH - 2, y + ROW - 2), fill=1)
                draw.text((4, y), clipped(draw, caption, WIDTH - 8, BODY), int(not active), font=BODY)
        else:
            lines = list(wrap(draw, text, WIDTH - 10))
            self.max_scroll = max(0, len(lines) - rows)
            start = self.max_scroll if scroll is None else min(scroll, self.max_scroll)
            for row, line in enumerate(lines[start:start + rows]):
                draw.text((4, 23 + row * ROW), line, 1, font=BODY)
            if self.max_scroll:
                y = 23 + int(start / self.max_scroll * 186)
                draw.line((126, y, 126, y + 8), 1)
        if progress is not None:
            draw.rectangle((5, HEIGHT - 35, WIDTH - 6, HEIGHT - 27), outline=1)
            end = int(progress * (WIDTH - 14))
            if end:
                draw.rectangle((7, HEIGHT - 33, 6 + end, HEIGHT - 29), fill=1)
        image = frame.resize((WIDTH * SCALE, HEIGHT * SCALE), Image.Resampling.NEAREST).convert("RGB")
        self.photo = ImageTk.PhotoImage(image)
        self.label.configure(image=self.photo)
