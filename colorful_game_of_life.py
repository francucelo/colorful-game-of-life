import colorsys
import tkinter as tk
from tkinter import messagebox, simpledialog
from numba import njit
import numpy as np
import pygame
import zlib

root = tk.Tk()
root.withdraw()

# --- Configuration Parameters ---
COLOR_BG = np.array([16, 16, 16], dtype=np.uint8)
PAUSE_FPS = 24
DENSITY = 3 / 8
S, V = 0.6, 0.9

# Display help dialog with keybindings and controls.
def show_help() -> None:
    messagebox.showinfo(
        "Help",
        "H = Help\n"
        "I = Info\n"
        "A = AutoReset\n"
        "Q = AutoPause\n"
        "C = Clear\n"
        "R = Generate\n"
        "F = Change FPS\n"
        "S = Change Size\n"
        "Y = Change Factions Number\n"
        "P = Screenshot\n"
        "W = Switch screen mode\n"
        "F11 = Toggle Fullscreen\n"
        "Space = Pause\n"
        "Enter = Next generation\n"
        "Mouse Left = Spawn cell\n"
        "Mouse Right = Erase cell\n"
        "1~9 or Z = Select Faction Color\n"
        "0 = Random Faction Color\n",
    )

# Generate a color palette matrix containing background color (index 0) and RGB colors for each faction (indices 1 to N).
def create_palette(num_factions: int) -> np.ndarray:
    palette = np.zeros((num_factions + 1, 3), dtype=np.uint8)
    palette[0] = COLOR_BG  # Index 0 represents the background color

    for i in range(1, num_factions + 1):
        r, g, b = colorsys.hsv_to_rgb((i - 1) / num_factions, S, V)
        palette[i] = [int(r * 255), int(g * 255), int(b * 255)]

    return palette

def create_palette_32(palette_rgb: np.ndarray, surface: pygame.Surface) -> np.ndarray:
    return np.array([surface.map_rgb(c) for c in palette_rgb], dtype=np.uint32)

# Generate a random living grid and faction matrix (0 = dead, 1..num_factions = faction ID).
def random_grid(width: int, height: int, num_factions: int) -> tuple[np.ndarray, np.ndarray]:
    grid = np.random.random((width, height)) < DENSITY
    factions = np.zeros((width, height), dtype=np.int16)

    # Assign random faction IDs (1 to num_factions) only to living cells
    factions[grid] = np.random.randint(1, num_factions + 1, size=int(np.sum(grid)))
    return grid, factions

@njit(fastmath=True)
def render_numba(factions: np.ndarray, palette_32: np.ndarray, out_pixels: np.ndarray):
    width, height = factions.shape
    for x in range(width):
        for y in range(height):
            out_pixels[x, y] = palette_32[factions[x, y]]

# Update grid state and faction ownership for the next generation based on Conway's rules.
@njit(fastmath=True)
def update_grid(
    grid: np.ndarray,
    factions: np.ndarray,
    next_grid: np.ndarray,
    next_factions: np.ndarray,
    num_factions: int,
) -> None:
    width, height = grid.shape

    # Relative offset coordinates of 8 neighbors
    dx = (-1, -1, -1, 0, 0, 1, 1, 1)
    dy = (-1, 0, 1, -1, 1, -1, 0, 1)

    # Used to count the votes for each faction in the area (1 to num_factions)
    faction_counts = np.zeros(num_factions + 1, dtype=np.int32)

    for x in range(width):
        for y in range(height):
            alive_neighbors = 0
            faction_counts.fill(0)

            for k in range(8):
                # Wrap-around boundary
                nx = (x + dx[k]) % width
                ny = (y + dy[k]) % height

                if grid[nx, ny]:
                    alive_neighbors += 1
                    f_id = factions[nx, ny]
                    if f_id > 0:
                        faction_counts[f_id] += 1

            # Classic Life-and-Death Rules
            is_alive = grid[x, y]
            will_live = (alive_neighbors == 3) or (is_alive and alive_neighbors == 2)

            if will_live:
                next_grid[x, y] = True

                # Find the faction with the highest number of nearby units
                max_count = 0
                for f in range(1, num_factions + 1):
                    if faction_counts[f] > max_count:
                        max_count = faction_counts[f]

                if max_count == 0:
                    # Isolated cells retain their original faction.
                    next_factions[x, y] = factions[x, y]
                else:
                    # Count the number of factions with the highest number
                    candidate_count = 0
                    for f in range(1, num_factions + 1):
                        if faction_counts[f] == max_count:
                            candidate_count += 1

                    if candidate_count == 1:
                        for f in range(1, num_factions + 1):
                            if faction_counts[f] == max_count:
                                next_factions[x, y] = f
                                break
                    else:
                        # In the event of a tie, a winner will be selected at random.
                        r = np.random.randint(0, candidate_count)
                        curr = 0
                        for f in range(1, num_factions + 1):
                            if faction_counts[f] == max_count:
                                if curr == r:
                                    next_factions[x, y] = f
                                    break
                                curr += 1
            else:
                next_grid[x, y] = False
                next_factions[x, y] = 0


def main() -> None:
    show_help()

    width, height = 64, 64

    pygame.init()
    screen = pygame.display.set_mode(
        (width, height), pygame.RESIZABLE | pygame.SCALED
    )
    is_scaled = True
    pygame.display.set_caption(f"Colorful Game of Life {width}x{height}")
    clock = pygame.time.Clock()

    num_factions: int = 6
    palette = create_palette(num_factions)

    grid_curr, factions_curr = random_grid(width, height, num_factions)
    grid_next = np.zeros_like(grid_curr)
    factions_next = np.zeros_like(factions_curr)
    history = set()

    running = True
    paused = True
    auto_reset = True
    auto_pause = not auto_reset

    fps = 12
    generation = 0

    # Selected brush faction (-1 for random, 1..N for fixed faction)
    selected_faction = 1

    grid_surface = pygame.Surface((width, height), depth=32)

    palette_32 = create_palette_32(palette, grid_surface)

    # Numba Warm-up
    update_grid(grid_curr, factions_curr, grid_next, factions_next, num_factions)
    pixels_temp = pygame.surfarray.pixels2d(grid_surface)
    render_numba(factions_curr, palette_32, pixels_temp)
    del pixels_temp

    while running:
        # Event processing loop
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                match event.key:
                    case pygame.K_SPACE:  # Toggle pause
                        paused = not paused
                    case pygame.K_RETURN: # Step next generation manually
                        if paused:
                            update_grid(
                                grid_curr, factions_curr, grid_next, factions_next, num_factions
                            )
                            generation += 1
                    case pygame.K_a:  # Toggle auto-reset on loop detection
                        auto_reset = not auto_reset
                        auto_pause = False
                        history.clear()
                    case pygame.K_q:  # Toggle auto-pause on loop detection
                        auto_pause = not auto_pause
                        auto_reset = False
                    case pygame.K_c:  # Clear grid
                        grid_curr.fill(False)
                        factions_curr.fill(0)
                        history.clear()
                        generation = 0
                    case pygame.K_r:  # Generate new random grid
                        grid_curr, factions_curr = random_grid(width, height, num_factions)
                        history.clear()
                        generation = 0

                    case pygame.K_f:  # Change simulation FPS
                        new_fps = simpledialog.askinteger(
                            "Enter a value",
                            "FPS (0 = No limitation)",
                            minvalue=0,
                        )
                        fps = new_fps if new_fps is not None else fps

                    case pygame.K_y:  # Change number of factions
                        new_num = simpledialog.askinteger(
                            "Enter a value",
                            "Number of Factions",
                            minvalue=1,
                            maxvalue=24,
                        )
                        if new_num:
                            num_factions = new_num
                            palette = create_palette(num_factions)
                            palette_32 = create_palette_32(palette, grid_surface)
                            grid_curr, factions_curr = random_grid(width, height, num_factions)
                            history.clear()
                            generation = 0

                    case pygame.K_s:  # Change grid dimensions
                        new_width = simpledialog.askinteger("Enter a value", "Width", minvalue=2)
                        new_height = simpledialog.askinteger("Enter a value", "Height", minvalue=2)

                        if new_width and new_height:
                            width, height = new_width, new_height
                            pygame.display.set_caption(f"Colorful Game of Life {width}x{height}")
                            grid_surface = pygame.Surface((width, height), depth=32)
                            palette_32 = create_palette_32(palette, grid_surface)
                            
                            grid_curr, factions_curr = random_grid(width, height, num_factions)
                            grid_next = np.zeros_like(grid_curr)
                            factions_next = np.zeros_like(factions_curr)

                            history.clear()
                            generation = 0
                            paused = True
                            screen = (
                                pygame.display.set_mode(
                                    (width, height),
                                    pygame.RESIZABLE | pygame.SCALED,
                                )
                                if is_scaled
                                else pygame.display.set_mode((width, height))
                            )

                    case pygame.K_p:  # Save screenshot
                        filename : str = f"screenshot_{zlib.crc32(np.packbits(grid_curr).tobytes()):08x}.png"
                        pygame.image.save(screen, filename)
                        messagebox.showinfo(filename, "You have taken a screenshot")

                    case pygame.K_w: # Toggle display scaling mode
                        is_scaled = not is_scaled
                        screen = (
                            pygame.display.set_mode(
                                (width, height),
                                pygame.RESIZABLE | pygame.SCALED,
                            )
                            if is_scaled
                            else pygame.display.set_mode((width, height))
                        )

                    case pygame.K_F11: # Toggle fullscreen
                        if not (screen.get_flags() & pygame.FULLSCREEN):
                            is_scaled = True
                            screen = pygame.display.set_mode((width, height), pygame.RESIZABLE | pygame.SCALED)
                        pygame.display.toggle_fullscreen()

                    case pygame.K_h: # Show help menu
                        show_help()

                    case pygame.K_i:  # Show info
                        messagebox.showinfo(
                            "Info",
                            f"FPS: {fps}\n"
                            f"Generation: {generation}\n"
                            f"Initial Factions: {num_factions}\n"
                            f"AutoReset: {auto_reset}\n"
                            f"AutoPause: {auto_pause}",
                        )

                    # Shortcut keys to select factions (1-9 map to factions 1-9, 0 maps to random)
                    case (
                        pygame.K_1
                        | pygame.K_2
                        | pygame.K_3
                        | pygame.K_4
                        | pygame.K_5
                        | pygame.K_6
                        | pygame.K_7
                        | pygame.K_8
                        | pygame.K_9
                    ):
                        idx = event.key - pygame.K_0
                        selected_faction = min(idx, num_factions)

                    case pygame.K_0 | pygame.K_KP0:
                        selected_faction = -1

                    # Dialog prompt to select faction ID
                    case pygame.K_z:
                        idx = simpledialog.askinteger("Enter a value", "Select Faction", minvalue=0, maxvalue=num_factions)
                        if idx is not None:
                            selected_faction = idx if idx != 0 else -1

        # Logic update loop
        if not paused:
            generation += 1
            if auto_reset or auto_pause:
                current_hash = hash(np.packbits(grid_curr).tobytes())
                if current_hash in history:
                    if auto_reset:
                        grid_curr, factions_curr = random_grid(width, height, num_factions)
                        history.clear()
                        generation = 0
                    elif auto_pause:
                        paused = True
                else:
                    history.add(current_hash)

            update_grid(grid_curr, factions_curr, grid_next, factions_next, num_factions)
            grid_curr, grid_next = grid_next, grid_curr
            factions_curr, factions_next = factions_next, factions_curr
            clock.tick(fps)
        else:
            # Mouse drawing and erasing when paused
            mouse_pressed = pygame.mouse.get_pressed()
            if mouse_pressed[0] or mouse_pressed[2]:
                x, y = pygame.mouse.get_pos()
                if 0 <= x < width and 0 <= y < height:
                    if mouse_pressed[0]:  # Left-click to draw cell
                        grid_curr[x, y] = True
                        factions_curr[x, y] = (
                            np.random.randint(1, num_factions + 1)
                            if selected_faction == -1
                            else selected_faction
                        )
                    elif mouse_pressed[2]:  # Right-click to erase cell
                        grid_curr[x, y] = False
                        factions_curr[x, y] = 0
                    history.clear()
                clock.tick(360)
            else:
                clock.tick(PAUSE_FPS)

        # --- Color Rendering ---
        # Direct mapping using palette matrix: Index 0 maps to COLOR_BG, indices 1..N map to faction colors
        pixels = pygame.surfarray.pixels2d(grid_surface)
        render_numba(factions_curr, palette_32, pixels)
        del pixels

        screen.blit(grid_surface, (0, 0))
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
