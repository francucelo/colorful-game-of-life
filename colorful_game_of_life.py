import colorsys
import tkinter as tk
from tkinter import messagebox, simpledialog
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

# Generate a random living grid and faction matrix (0 = dead, 1..num_factions = faction ID).
def random_grid(width: int, height: int, num_factions: int) -> tuple[np.ndarray, np.ndarray]:
    grid = np.random.random((width, height)) < DENSITY
    factions = np.zeros((width, height), dtype=np.int16)

    # Assign random faction IDs (1 to num_factions) only to living cells
    factions[grid] = np.random.randint(1, num_factions + 1, size=int(np.sum(grid)))
    return grid, factions

# Update grid state and faction ownership for the next generation based on Conway's rules.
def update_grid(grid: np.ndarray, factions: np.ndarray, num_factions: int) -> tuple[np.ndarray, np.ndarray]:
    # Periodic boundary padding: Must cast to uint8 to prevent bitwise OR behavior with boolean arrays
    padded = np.pad(grid.astype(np.uint8), pad_width=1, mode='wrap')
    neighbors_count = (
        padded[:-2, :-2] + padded[:-2, 1:-1] + padded[:-2, 2:] +
        padded[1:-1, :-2]                     + padded[1:-1, 2:] +
        padded[2:, :-2]  + padded[2:, 1:-1]  + padded[2:, 2:]
    )

    # Conway's classic life/death rules
    next_grid = (neighbors_count == 3) | (grid & (neighbors_count == 2))

    next_factions = np.zeros_like(factions)

    # Calculate faction assignment only for surviving/newborn cells in the next frame
    padded_factions = np.pad(factions, pad_width=1, mode="wrap")

    # Extract neighbor faction IDs for all K surviving cells, shape: (K, 8)
    surviving_neighbors = np.stack(
        [
            padded_factions[:-2, :-2][next_grid],
            padded_factions[:-2, 1:-1][next_grid],
            padded_factions[:-2, 2:][next_grid],
            padded_factions[1:-1, :-2][next_grid],
            padded_factions[1:-1, 2:][next_grid],
            padded_factions[2:, :-2][next_grid],
            padded_factions[2:, 1:-1][next_grid],
            padded_factions[2:, 2:][next_grid],
        ],
        axis=1,
    )

    # Broadcast comparison to calculate vote counts for each faction, shape: (K, N)
    faction_ids = np.arange(1, num_factions + 1)
    counts = (surviving_neighbors[:, :, None] == faction_ids).sum(axis=1)

    # Add small random noise to break ties
    noise = np.random.uniform(0.0, 0.01, size=counts.shape)
    winning_factions = np.argmax(counts + noise, axis=1) + 1

    # Handle isolated cells: retain original faction if no neighbors are present
    max_counts = counts.max(axis=1)
    orig_factions = factions[next_grid]
    final_factions = np.where(max_counts > 0, winning_factions, orig_factions)

    # Map back to the next generation faction matrix
    next_factions[next_grid] = final_factions

    return next_grid, next_factions


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

    num_factions: int = 8
    palette = create_palette(num_factions)

    grid, factions = random_grid(width, height, num_factions)
    history = set()

    running = True
    paused = True
    auto_reset = True
    auto_pause = not auto_reset

    fps = 12
    generation = 0

    # Selected brush faction (-1 for random, 1..N for fixed faction)
    selected_faction = 1

    grid_surface = pygame.Surface((width, height))

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
                            grid, factions = update_grid(
                                grid, factions, num_factions
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
                        grid = np.zeros((width, height), dtype=bool)
                        factions = np.zeros((width, height), dtype=np.int16)
                        history.clear()
                        generation = 0
                    case pygame.K_r:  # Generate new random grid
                        grid, factions = random_grid(
                            width, height, num_factions
                        )
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
                            grid, factions = random_grid(
                                width, height, num_factions
                            )
                            history.clear()
                            generation = 0

                    case pygame.K_s:  # Change grid dimensions
                        new_width = simpledialog.askinteger(
                            "Enter a value", "Width", minvalue=2
                        )
                        new_height = simpledialog.askinteger(
                            "Enter a value", "Height", minvalue=2
                        )

                        if new_width and new_height:
                            width, height = new_width, new_height
                            pygame.display.set_caption(
                                f"Colorful Game of Life {width}x{height}"
                            )
                            grid_surface = pygame.Surface((width, height))
                            grid, factions = random_grid(
                                width, height, num_factions
                            )
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
                        filename : str = f"screenshot_{zlib.crc32(np.packbits(grid).tobytes()):08x}.png"
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
                current_hash = hash(np.packbits(grid).tobytes())
                if current_hash in history:
                    if auto_reset:
                        grid, factions = random_grid(width, height, num_factions)
                        history.clear()
                        generation = 0
                    elif auto_pause:
                        paused = True
                else:
                    history.add(current_hash)

            grid, factions = update_grid(grid, factions, num_factions)
            clock.tick(fps)
        else:
            # Mouse drawing and erasing when paused
            mouse_pressed = pygame.mouse.get_pressed()
            if mouse_pressed[0] or mouse_pressed[2]:
                x, y = pygame.mouse.get_pos()
                if 0 <= x < width and 0 <= y < height:
                    if mouse_pressed[0]:  # Left-click to draw cell
                        grid[x, y] = True
                        factions[x, y] = (
                            np.random.randint(1, num_factions + 1)
                            if selected_faction == -1
                            else selected_faction
                        )
                    elif mouse_pressed[2]:  # Right-click to erase cell
                        grid[x, y] = False
                        factions[x, y] = 0
                    history.clear()
                clock.tick(360)
            else:
                clock.tick(PAUSE_FPS)

        # --- Color Rendering ---
        # Direct mapping using palette matrix: Index 0 maps to COLOR_BG, indices 1..N map to faction colors
        rgb_frame = palette[factions]
        pygame.surfarray.blit_array(grid_surface, rgb_frame)

        screen.blit(grid_surface, (0, 0))
        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
