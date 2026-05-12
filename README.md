# yt-cli-player

Terminal-based YouTube audio player. Search YouTube, download as MP3, play — all from the terminal.

---

## TL;DR

```bash
# 1. Install system dependency
sudo apt install ffmpeg

# 2. Set up Python environment
bash init.sh

# 3. Run
bash start.sh
```

On first launch with an empty library, the search screen opens automatically.  
Type a song name → `Enter` to play, `Esc` to close search.

---

## Keybindings

### Main screen

| Key | Action |
|---|---|
| `p` | Play / Pause |
| `n` | Next |
| `a` | Toggle autoplay |
| `r` | Toggle recommended mode |
| `R` | Fetch recommendation for current song |
| `Ctrl+F` | Search |
| `Ctrl+P` / `↓` | Playlist |
| `Ctrl+L` | Library |
| `Ctrl+Shift+L` | Fill queue with 20 random local songs |
| `q` | Quit |

### Search (`Ctrl+F`)

| Key | Action |
|---|---|
| Type | Filter local + search YouTube (debounced 400ms) |
| `↑↓` | Navigate results |
| `Space` | Check/uncheck item |
| `Enter` | Play highlighted / add checked to queue |
| `Ctrl+Space` | Add checked as play next |
| `Tab` | Focus list |
| `Esc` | Close |

### Playlist (`Ctrl+P`)

| Key | Action |
|---|---|
| `↑↓` | Navigate |
| `Ctrl+↑` | Move song up |
| `Ctrl+↓` | Move song down |
| `Enter` | Jump to and play selected |
| `d` | Delete selected |
| `Ctrl+D` | Clear all |
| `Esc` | Close |

### Library (`Ctrl+L`)

| Key | Action |
|---|---|
| Type | Filter |
| `↑↓` | Navigate |
| `Space` | Add to end of queue / remove |
| `Ctrl+Space` | Add as play next / remove |
| `Tab` | Focus list |
| `Esc` | Close |

---

## How it works

- Downloads audio via `yt-dlp` in native format (opus/webm preferred, m4a fallback)
- Plays offline with `ffplay` after download
- Downloads saved to `downloads/`, recommended songs to `downloads/recommended/`
- Queue auto-refills: 4 random local songs in normal mode, YouTube recommendations in recommended mode

---

## Requirements

| Dependency | Install |
|---|---|
| `ffplay` | `sudo apt install ffmpeg` |
| `python3-venv` | `sudo apt install python3.13-venv` |
| `textual`, `yt-dlp` | installed automatically by `init.sh` |
