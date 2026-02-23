"""
Generate original 16x16 pixel-art PNG textures for the MCBE AI Commander frontend.
These are ORIGINAL pixel art inspired by Minecraft aesthetic, NOT Mojang copyrighted textures.
Each texture uses a deterministic seed based on its name for reproducibility.
"""

import os
import random
import hashlib
from PIL import Image

OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "frontend", "public", "textures"
)
SIZE = 16

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

def get_seed(name):
    return int(hashlib.md5(name.encode()).hexdigest()[:8], 16)

def generate_noise_texture(name, colors):
    seed = get_seed(name)
    rng = random.Random(seed)
    rgb_colors = [hex_to_rgb(c) for c in colors]
    img = Image.new("RGB", (SIZE, SIZE))
    for y in range(SIZE):
        for x in range(SIZE):
            color = rng.choice(rgb_colors)
            img.putpixel((x, y), color)
    return img

def generate_brick_texture(name, colors):
    seed = get_seed(name)
    rng = random.Random(seed)
    rgb_colors = [hex_to_rgb(c) for c in colors]
    mortar_base = hex_to_rgb(colors[-1])
    mortar_color = tuple(max(0, c - 30) for c in mortar_base)
    img = Image.new("RGB", (SIZE, SIZE))
    brick_height = 4
    brick_width = 8
    num_rows = SIZE // brick_height
    for row in range(num_rows):
        y_start = row * brick_height
        x_offset = (brick_width // 2) if (row % 2 == 1) else 0
        for y in range(y_start, y_start + brick_height):
            for x in range(SIZE):
                is_h_mortar = (y == y_start + brick_height - 1)
                adjusted_x = (x + x_offset) % SIZE
                is_v_mortar = (adjusted_x % brick_width == 0)
                if is_h_mortar or is_v_mortar:
                    img.putpixel((x, y), mortar_color)
                else:
                    brick_id = ((x + x_offset) // brick_width) + row * 10
                    brick_rng = random.Random(seed + brick_id)
                    base_color = brick_rng.choice(rgb_colors)
                    variation = rng.randint(-5, 5)
                    final_color = tuple(max(0, min(255, c + variation)) for c in base_color)
                    img.putpixel((x, y), final_color)
    return img

def generate_plank_texture(name, colors):
    seed = get_seed(name)
    rng = random.Random(seed)
    rgb_colors = [hex_to_rgb(c) for c in colors]
    img = Image.new("RGB", (SIZE, SIZE))
    plank_height = 4
    for plank in range(SIZE // plank_height):
        base_color = rng.choice(rgb_colors)
        y_start = plank * plank_height
        for y in range(y_start, y_start + plank_height):
            row_offset = rng.randint(-8, 8)
            is_divider = (y == y_start)
            for x in range(SIZE):
                if is_divider:
                    divider_color = tuple(max(0, c - 25) for c in base_color)
                    img.putpixel((x, y), divider_color)
                else:
                    pixel_noise = rng.randint(-6, 6)
                    total_offset = row_offset + pixel_noise
                    final_color = tuple(max(0, min(255, c + total_offset)) for c in base_color)
                    img.putpixel((x, y), final_color)
    return img

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    textures = [
        ("dirt.png", generate_noise_texture, ["#6B4226", "#7B5230", "#5A3420"]),
        ("stone_bricks.png", generate_brick_texture, ["#808080", "#909090", "#707070"]),
        ("oak_planks.png", generate_plank_texture, ["#B88A50", "#A47840"]),
        ("dark_oak_planks.png", generate_plank_texture, ["#4A3220", "#3B2716"]),
        ("smooth_stone.png", generate_noise_texture, ["#A0A0A0", "#909090"]),
        ("bedrock.png", generate_noise_texture, ["#2A2A2A", "#1A1A1A"]),
        ("grass_block_top.png", generate_noise_texture, ["#5B8731", "#6B9741"]),
    ]
    print("Output directory: {}".format(OUTPUT_DIR))
    print("Generating {} textures ({}x{} pixels each)...".format(len(textures), SIZE, SIZE))
    print()
    for filename, generator, colors in textures:
        name = filename.replace(".png", "")
        img = generator(name, colors)
        output_path = os.path.join(OUTPUT_DIR, filename)
        img.save(output_path)
        file_size = os.path.getsize(output_path)
        print("  [OK] {:25s} ({:>5d} bytes) - colors: {}".format(filename, file_size, ", ".join(colors)))
    print()
    print("All {} textures generated successfully.".format(len(textures)))

if __name__ == "__main__":
    main()
