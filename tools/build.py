#!/usr/bin/env python3
"""Generates the dragon models + textures and packages the add-on.

    python3 tools/build.py            -> dist/DragonMod.mcaddon (+ dist/preview.png)

Models are described below as plain boxes. The script lays their textures out
automatically, paints them, writes the Bedrock geometry files and zips the two
packs into a single .mcaddon that Minecraft can import.
"""
import json
import random
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
RP = ROOT / "resource_pack"
BP = ROOT / "behavior_pack"
DIST = ROOT / "dist"

# ---------------------------------------------------------------- models ----
# Units are pixels (16 = one block). Front of the model is -Z, up is +Y.
# cube = (origin xyz, size xyz, paint style)


def dragon_bones():
    def leg(name, x, z):
        return dict(name=name, parent="body", pivot=[x + 2, 10, z + 2], cubes=[
            ([x, 2, z], [4, 8, 4], "scales"),
            ([x, 0, z - 1], [4, 2, 5], "claw"),
        ])

    def wing(side, s):
        # s = +1 for the left (+X) wing, -1 for the right
        inner_x = 5 if s > 0 else -19
        tip_x = 19 if s > 0 else -31
        return [
            dict(name=f"wing_{side}", parent="body", pivot=[5 * s, 18, -3], cubes=[
                ([inner_x, 17, -7], [14, 1, 13], "membrane"),
            ]),
            dict(name=f"wing_{side}_tip", parent=f"wing_{side}", pivot=[19 * s, 18, -3], cubes=[
                ([tip_x, 17, -6], [12, 1, 10], "membrane"),
            ]),
        ]

    return [
        dict(name="root", pivot=[0, 0, 0], cubes=[]),
        dict(name="body", parent="root", pivot=[0, 14, 0], cubes=[
            ([-5, 10, -8], [10, 9, 18], "body"),
            ([-1, 19, -6], [2, 2, 3], "spike"),
            ([-1, 19, 5], [2, 2, 3], "spike"),
        ]),
        dict(name="saddle", parent="body", pivot=[0, 19, 0], cubes=[
            ([-4, 19, -2], [8, 1, 7], "saddle"),
            ([-6, 14, 0], [1, 5, 3], "saddle"),
            ([5, 14, 0], [1, 5, 3], "saddle"),
        ]),
        dict(name="neck", parent="body", pivot=[0, 16, -8], cubes=[
            ([-2, 15, -12], [4, 11, 5], "body"),
        ]),
        dict(name="head", parent="neck", pivot=[0, 25, -10], cubes=[
            ([-3, 23, -17], [6, 6, 8], "head"),
            ([-2, 23, -22], [4, 4, 5], "snout"),
            ([-3, 29, -11], [1, 4, 1], "horn"),
            ([2, 29, -11], [1, 4, 1], "horn"),
        ]),
        dict(name="tail1", parent="body", pivot=[0, 15, 10], cubes=[
            ([-3, 11, 10], [6, 6, 8], "body"),
            ([-1, 17, 12], [2, 2, 3], "spike"),
        ]),
        dict(name="tail2", parent="tail1", pivot=[0, 13, 18], cubes=[
            ([-2, 10, 18], [4, 4, 8], "body"),
        ]),
        dict(name="tail3", parent="tail2", pivot=[0, 11, 26], cubes=[
            ([-1, 9, 26], [2, 2, 8], "scales"),
            ([-3, 10, 33], [6, 1, 5], "membrane"),
        ]),
        leg("leg_front_left", 3, -7),
        leg("leg_front_right", -7, -7),
        leg("leg_back_left", 3, 5),
        leg("leg_back_right", -7, 5),
        *wing("left", 1),
        *wing("right", -1),
    ]


def egg_bones():
    return [
        dict(name="egg", pivot=[0, 0, 0], cubes=[
            ([-3, 0, -3], [6, 1, 6], "egg"),
            ([-4, 1, -4], [8, 6, 8], "egg"),
            ([-3, 7, -3], [6, 3, 6], "egg"),
            ([-2, 10, -2], [4, 1, 4], "egg"),
        ]),
    ]


# -------------------------------------------------------------- palettes ----
PALETTES = {
    "forest_dragon": dict(
        scales=(58, 140, 60), dark=(34, 96, 44), belly=(232, 217, 138),
        membrane=(150, 200, 90), horn=(240, 232, 200), eye=(255, 190, 40),
        saddle=(122, 72, 38), saddle_trim=(214, 170, 60),
        egg=(232, 226, 192), egg_spot=(58, 140, 60),
    ),
}


def shade(c, f):
    return tuple(max(0, min(255, int(v * f))) for v in c) + (255,)


# ------------------------------------------------------------ uv packing ----
def pack(bones, tex_w):
    """Assign a box-UV position to every cube (simple shelf packing)."""
    cubes = [c for b in bones for c in b["cubes"]]
    order = sorted(range(len(cubes)), key=lambda i: -(cubes[i][1][1] + cubes[i][1][2]))
    uvs, x, y, row_h = {}, 0, 0, 0
    for i in order:
        w, h, d = cubes[i][1]
        iw, ih = 2 * (w + d), d + h
        if x + iw > tex_w:
            x, y, row_h = 0, y + row_h + 1, 0
        uvs[i] = (x, y)
        x += iw + 1
        row_h = max(row_h, ih)
    tex_h = 16
    while tex_h < y + row_h:
        tex_h *= 2
    flat, n = [], 0
    for b in bones:
        for c in b["cubes"]:
            flat.append((b, c, uvs[n]))
            n += 1
    return flat, tex_h


def face_rects(size, uv):
    """Texture rectangles (x, y, w, h) of each face of a box-UV cube."""
    w, h, d = size
    u, v = uv
    return {
        "side_a": (u, v + d, d, h),              # borders the front on its right edge
        "front": (u + d, v + d, w, h),
        "side_b": (u + d + w, v + d, d, h),      # borders the front on its left edge
        "back": (u + 2 * d + w, v + d, w, h),
        "top": (u + d, v, w, d),                 # bottom row touches the front
        "bottom": (u + d + w, v, w, d),
    }


# -------------------------------------------------------------- painting ----
def paint(flat, tex_w, tex_h, pal, seed):
    img = Image.new("RGBA", (tex_w, tex_h), (0, 0, 0, 0))
    px = img.load()
    rnd = random.Random(seed)

    def fill(rect, fn):
        x0, y0, w, h = rect
        for j in range(h):
            for i in range(w):
                px[x0 + i, y0 + j] = fn(i, j, w, h)

    def scales(i, j, w, h):
        base = pal["dark"] if rnd.random() < 0.22 else pal["scales"]
        return shade(base, rnd.uniform(0.92, 1.08))

    def flat_col(key, lo=0.94, hi=1.06):
        return lambda i, j, w, h: shade(pal[key], rnd.uniform(lo, hi))

    for bone, (origin, size, style), uv in flat:
        r = face_rects(size, uv)
        if style in ("body", "head", "snout", "scales"):
            for name in ("side_a", "side_b", "back", "top", "front"):
                fill(r[name], scales)
            fill(r["bottom"], flat_col("belly"))
            if style in ("body", "head", "snout"):
                # cream belly creeping up the sides, darker ridge down the back
                for name in ("side_a", "side_b", "front", "back"):
                    x0, y0, w, h = r[name]
                    band = max(1, h // 4)
                    fill((x0, y0 + h - band, w, band), flat_col("belly"))
                x0, y0, w, h = r["top"]
                mid = w // 2
                fill((x0 + mid - 1, y0, 2, h), flat_col("dark"))
            if style == "head":
                for name, ex in (("side_a", r["side_a"][2] - 3), ("side_b", 1)):
                    x0, y0, w, h = r[name]
                    for i in range(2):
                        px[x0 + ex + i, y0 + 1] = shade(pal["eye"], 1.0)
                        px[x0 + ex + i, y0 + 2] = shade(pal["eye"], 0.85)
                    pupil = ex if name == "side_b" else ex + 1
                    px[x0 + pupil, y0 + 1] = (20, 20, 20, 255)
                    px[x0 + pupil, y0 + 2] = (20, 20, 20, 255)
            if style == "snout":
                x0, y0, w, h = r["front"]
                px[x0, y0] = shade(pal["dark"], 0.6)
                px[x0 + w - 1, y0] = shade(pal["dark"], 0.6)
        elif style == "membrane":
            def mem(i, j, w, h):
                rib = (i % 4 == 0)
                return shade(pal["scales"] if rib else pal["membrane"], rnd.uniform(0.95, 1.05))
            for rect in r.values():
                fill(rect, mem)
        elif style in ("horn", "claw", "spike"):
            key = "dark" if style == "spike" else "horn"
            for rect in r.values():
                fill(rect, flat_col(key))
        elif style == "saddle":
            for rect in r.values():
                fill(rect, flat_col("saddle"))
            x0, y0, w, h = r["top"]
            for i in range(w):
                px[x0 + i, y0] = shade(pal["saddle_trim"], 1.0)
                px[x0 + i, y0 + h - 1] = shade(pal["saddle_trim"], 1.0)
        elif style == "egg":
            def egg(i, j, w, h):
                spot = rnd.random() < 0.18
                return shade(pal["egg_spot"] if spot else pal["egg"], rnd.uniform(0.93, 1.05))
            for rect in r.values():
                fill(rect, egg)
    return img


# -------------------------------------------------------------- geometry ----
def geometry(identifier, bones, flat, tex_w, tex_h, bounds):
    out_bones = []
    for b in bones:
        entry = {"name": b["name"], "pivot": b["pivot"]}
        if b.get("parent"):
            entry["parent"] = b["parent"]
        cubes = [{"origin": o, "size": s, "uv": list(uv)}
                 for bb, (o, s, _), uv in flat if bb is b]
        if cubes:
            entry["cubes"] = cubes
        out_bones.append(entry)
    return {
        "format_version": "1.12.0",
        "minecraft:geometry": [{
            "description": {
                "identifier": identifier,
                "texture_width": tex_w,
                "texture_height": tex_h,
                "visible_bounds_width": bounds[0],
                "visible_bounds_height": bounds[1],
                "visible_bounds_offset": [0, bounds[1] / 2, 0],
            },
            "bones": out_bones,
        }],
    }


# --------------------------------------------------------------- preview ----
def preview(flat, tex, scale=9, skip=("saddle",)):
    """Rough 3D picture of the model in its rest pose (not the in-game look)."""
    import math
    yaw, pitch = math.radians(35), math.radians(22)

    def proj(p):
        x, y, z = p
        x, z = x * math.cos(yaw) - z * math.sin(yaw), x * math.sin(yaw) + z * math.cos(yaw)
        y, z = y * math.cos(pitch) - z * math.sin(pitch), y * math.sin(pitch) + z * math.cos(pitch)
        return (x * scale, -y * scale, z)

    quads = []
    px = tex.load()
    for bone, (o, s, _), uv in flat:
        if bone["name"] in skip:
            continue
        x0, y0, z0 = o
        w, h, d = s
        r = face_rects(s, uv)
        # (rect, light, function texel(i,j) -> 4 corners in 3D)
        faces = [
            (r["front"], 0.85, lambda i, j: [(x0 + i + a, y0 + h - j - b, z0) for a, b in ((0, 0), (1, 0), (1, 1), (0, 1))]),
            (r["back"], 0.7, lambda i, j: [(x0 + w - i - a, y0 + h - j - b, z0 + d) for a, b in ((0, 0), (1, 0), (1, 1), (0, 1))]),
            (r["side_a"], 0.75, lambda i, j: [(x0, y0 + h - j - b, z0 + d - i - a) for a, b in ((0, 0), (1, 0), (1, 1), (0, 1))]),
            (r["side_b"], 0.75, lambda i, j: [(x0 + w, y0 + h - j - b, z0 + i + a) for a, b in ((0, 0), (1, 0), (1, 1), (0, 1))]),
            (r["top"], 1.0, lambda i, j: [(x0 + i + a, y0 + h, z0 + d - j - b) for a, b in ((0, 0), (1, 0), (1, 1), (0, 1))]),
            (r["bottom"], 0.55, lambda i, j: [(x0 + i + a, y0, z0 + d - j - b) for a, b in ((0, 0), (1, 0), (1, 1), (0, 1))]),
        ]
        for (rx, ry, rw, rh), light, corners in faces:
            for j in range(rh):
                for i in range(rw):
                    col = px[rx + i, ry + j]
                    if col[3] == 0:
                        continue
                    pts = [proj(p) for p in corners(i, j)]
                    depth = sum(p[2] for p in pts) / 4
                    quads.append((depth, [(p[0], p[1]) for p in pts], shade(col[:3], light)))
    quads.sort(key=lambda q: -q[0])
    xs = [p[0] for q in quads for p in q[1]]
    ys = [p[1] for q in quads for p in q[1]]
    pad = 20
    img = Image.new("RGBA", (int(max(xs) - min(xs)) + 2 * pad, int(max(ys) - min(ys)) + 2 * pad), (135, 190, 235, 255))
    draw = ImageDraw.Draw(img)
    for _, pts, col in quads:
        draw.polygon([(x - min(xs) + pad, y - min(ys) + pad) for x, y in pts], fill=col)
    return img


def pack_icon(pal):
    img = Image.new("RGBA", (64, 64), shade(pal["dark"], 0.8))
    d = ImageDraw.Draw(img)
    d.ellipse((18, 10, 46, 54), fill=shade(pal["egg"], 1.0))
    rnd = random.Random(7)
    for _ in range(14):
        x, y = rnd.randint(22, 40), rnd.randint(16, 46)
        d.rectangle((x, y, x + 2, y + 2), fill=shade(pal["egg_spot"], 1.0))
    return img.resize((256, 256), Image.NEAREST)


# ------------------------------------------------------------------ main ----
def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def build():
    DIST.mkdir(exist_ok=True)
    tex_dir = RP / "textures/entity/dragonmod"
    tex_dir.mkdir(parents=True, exist_ok=True)

    bones = dragon_bones()
    flat, tex_h = pack(bones, 128)
    write_json(RP / "models/entity/dragon.geo.json",
               geometry("geometry.dragonmod.dragon", bones, flat, 128, tex_h, (6, 4)))
    for name, pal in PALETTES.items():
        tex = paint(flat, 128, tex_h, pal, seed=name)
        tex.save(tex_dir / f"{name}.png")
        preview(flat, tex).save(DIST / f"preview_{name}.png")

    ebones = egg_bones()
    eflat, etex_h = pack(ebones, 64)
    write_json(RP / "models/entity/dragon_egg.geo.json",
               geometry("geometry.dragonmod.dragon_egg", ebones, eflat, 64, etex_h, (2, 2)))
    for name, pal in PALETTES.items():
        paint(eflat, 64, etex_h, pal, seed=name + "_egg").save(tex_dir / f"{name}_egg.png")

    icon = pack_icon(PALETTES["forest_dragon"])
    icon.save(RP / "pack_icon.png")
    icon.save(BP / "pack_icon.png")

    # every JSON file must parse before we ship it
    for f in list(RP.rglob("*.json")) + list(BP.rglob("*.json")):
        json.loads(f.read_text())

    out = DIST / "DragonMod.mcaddon"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, src in (("DragonMod_BP", BP), ("DragonMod_RP", RP)):
            for f in sorted(src.rglob("*")):
                if f.is_file():
                    z.write(f, f"{folder}/{f.relative_to(src).as_posix()}")
    print(f"built {out.relative_to(ROOT)} ({out.stat().st_size} bytes), dragon texture 128x{tex_h}")


if __name__ == "__main__":
    build()
