"""Genera postit.ico (3 post-it impilati) senza librerie esterne."""
import math, struct, sys, zlib

def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

# (centro x, centro y, metà lato, angolo, colore corpo, colore banda, righe?)
NOTES = [
    (0.40, 0.38, 0.29, -14, hexc("#9fdcfb"), hexc("#4fb8ec"), False),
    (0.52, 0.49, 0.29, 9, hexc("#bfe58f"), hexc("#86c24a"), False),
    (0.57, 0.61, 0.29, -4, hexc("#fff176"), hexc("#f6cf2b"), True),
]
INK = hexc("#6b5a00")
RADIUS = 0.035

def rr_inside(lx, ly, half, r):
    qx = abs(lx) - (half - r)
    qy = abs(ly) - (half - r)
    if qx <= 0 and qy <= 0:
        return True
    return math.hypot(max(qx, 0), max(qy, 0)) <= r and max(qx, qy) <= r

def sample(x, y):
    """Colore RGBA (premoltiplicato) nel punto normalizzato (x, y)."""
    r = g = b = a = 0.0

    def over(cr, cg, cb, ca):
        nonlocal r, g, b, a
        r = cr * ca + r * (1 - ca)
        g = cg * ca + g * (1 - ca)
        b = cb * ca + b * (1 - ca)
        a = ca + a * (1 - ca)

    for cx, cy, half, ang, body, band, lines in NOTES:
        t = math.radians(ang)
        ct, st = math.cos(t), math.sin(t)
        # ombra
        dx, dy = x - cx - 0.018, y - cy - 0.026
        lx, ly = dx * ct + dy * st, -dx * st + dy * ct
        if rr_inside(lx, ly, half, RADIUS):
            over(0, 0, 0, 0.22)
        dx, dy = x - cx, y - cy
        lx, ly = dx * ct + dy * st, -dx * st + dy * ct
        if not rr_inside(lx, ly, half, RADIUS):
            continue
        col = band if ly < -half + 0.085 else body
        over(*col, 1.0)
        if lines:
            for yy, x1 in ((-0.06, 0.17), (0.06, 0.12), (0.18, 0.17)):
                # quadratino + riga
                if abs(ly - yy) < 0.035 and -0.20 < lx < -0.13:
                    if abs(ly - yy) > 0.018 or lx < -0.185 or lx > -0.145:
                        over(*INK, 0.85)
                if abs(ly - yy) < 0.016 and -0.09 < lx < x1:
                    over(*INK, 0.75)
    return r, g, b, a

def render(size):
    ss = 4 if size <= 64 else 3
    rows = []
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            R = G = B = A = 0.0
            for sy in range(ss):
                for sx in range(ss):
                    cr, cg, cb, ca = sample((px + (sx + 0.5) / ss) / size,
                                            (py + (sy + 0.5) / ss) / size)
                    R += cr; G += cg; B += cb; A += ca
            n = ss * ss
            R, G, B, A = R / n, G / n, B / n, A / n
            if A > 0:
                R, G, B = R / A, G / A, B / A
            row += bytes((round(R * 255), round(G * 255), round(B * 255), round(A * 255)))
        rows.append(bytes(row))
    return png(size, b"".join(rows))

def png(size, raw):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))

def main(out_ico, out_preview):
    sizes = [16, 24, 32, 48, 64, 256]
    imgs = [render(s) for s in sizes]
    head = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries, data = b"", b""
    for s, im in zip(sizes, imgs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(im), offset + len(data))
        data += im
    with open(out_ico, "wb") as f:
        f.write(head + entries + data)
    with open(out_preview, "wb") as f:
        f.write(imgs[-1])

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
