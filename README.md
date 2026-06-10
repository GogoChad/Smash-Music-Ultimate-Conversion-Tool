<p align="center">
  <img src="https://raw.githubusercontent.com/GogoChad/Smash-Music-Ultimate-Conversion-Tool/refs/heads/main/icon.ico" width="200">
</p>

# SMUCT - Smash Music Ultimate Conversion Tool

A tool for converting and managing custom music files for Super Smash Bros. Ultimate mods.

---

## What it does

### Download & Format Conversion :

    - Download audio from YouTube videos using yt-dlp
    - Convert audio to MP3 with selectable quality (128k, 192k, 320k)
    - Convert MP3 to NUS3Audio format for Super Smash Bros Ultimate

### Audio Processing :

    - Normalize volume using loudnorm filter (with customizable LUFS target)
    - Fast mode option to skip loudness measurement for speed
    - Loop detection and configuration for audio files

### Organization & Logging :

    - Automatic file naming sanitization
    - CSV logging of all processed tracks with metadata
    - Track conversion history with searchable database
    - Status tracking (Converted, Skipped, Failed)

### Performance :

    - Parallel downloads using ThreadPoolExecutor (configurable worker threads)
    - Progress tracking for both overall and per-song operations
    - Skip already-converted tracks to avoid duplicates

### Convenience :

    - Paste button for quick URL input
    - Quick access buttons to output folders
    - MP3-only mode (skip conversion to NUS3Audio)
    - Auto-update checker
    - Dark themed GUI with status indicators


---

## Requirements

- Windows 10 or later
- VGAudioCli.exe
- nus3audio.exe

Both tools need to be placed in the same folder as SMUCT.

---

## How to use

1. Download the latest release
2. Place VGAudioCli.exe and nus3audio.exe in the same folder
3. Run SMUCT.exe
4. Add your MP3 files
5. Set the loop points if needed
6. Click Convert

The output files will be saved in the folder you choose. SMUCT keeps the original MP3 files untouched.

---

## Output files

For each song SMUCT will generate:

- A .lopus file
- A .nus3audio file ready to use in your mod

---

## Installation

No installation needed. Download the exe from the releases page and run it.

---

## Credits

- VGAudio by thane98
- nus3audio by jam1garner
