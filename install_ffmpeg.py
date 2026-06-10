import os
import sys
import zipfile
import shutil
import winreg
import urllib.request
import json
import ctypes

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def get_latest_ffmpeg_url():
    print("Fetching latest FFmpeg version...")
    api_url = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
    req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
    
    for asset in data["assets"]:
        name = asset["name"]
        if "ffmpeg-master-latest-win64-gpl.zip" in name:
            return asset["browser_download_url"], name
    
    raise Exception("Could not find FFmpeg download URL")

def download_ffmpeg(url, filename):
    print(f"Downloading {filename}...")
    dest = os.path.join(os.environ["TEMP"], filename)
    
    def progress(count, block_size, total_size):
        percent = int(count * block_size * 100 / total_size)
        print(f"\r  Progress: {min(percent, 100)}%", end="")
    
    urllib.request.urlretrieve(url, dest, reporthook=progress)
    print()
    return dest

def extract_ffmpeg(zip_path):
    print("Extracting FFmpeg...")
    extract_dir = os.path.join(os.environ["TEMP"], "ffmpeg_extract")
    
    if os.path.exists(extract_dir):
        shutil.rmtree(extract_dir)
    
    with zipfile.ZipFile(zip_path, 'r') as z:
        z.extractall(extract_dir)
    
    # Find the bin folder inside extracted content
    for root, dirs, files in os.walk(extract_dir):
        if "ffmpeg.exe" in files:
            return root
    
    raise Exception("Could not find ffmpeg.exe in extracted files")

def install_ffmpeg(bin_source):
    install_path = r"C:\ffmpeg"
    bin_path     = r"C:\ffmpeg\bin"
    
    print(f"Installing to {bin_path}...")
    
    if os.path.exists(install_path):
        shutil.rmtree(install_path)
    
    os.makedirs(bin_path, exist_ok=True)
    
    # Copy all .exe files
    for f in os.listdir(bin_source):
        if f.endswith(".exe"):
            shutil.copy2(os.path.join(bin_source, f), bin_path)
            print(f"  Copied {f}")
    
    return bin_path

def add_to_system_path(new_path):
    print("Adding to Windows environment variables...")
    
    key = winreg.OpenKey(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        0,
        winreg.KEY_READ | winreg.KEY_WRITE
    )
    
    try:
        current_path, _ = winreg.QueryValueEx(key, "Path")
    except FileNotFoundError:
        current_path = ""
    
    if new_path.lower() not in current_path.lower():
        updated_path = current_path + ";" + new_path
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, updated_path)
        print(f"  Added {new_path} to PATH")
    else:
        print(f"  {new_path} already in PATH")
    
    winreg.CloseKey(key)
    
    # Notify Windows of the change
    ctypes.windll.user32.SendMessageTimeoutW(
        0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, None
    )

def verify_install():
    ffmpeg_exe = r"C:\ffmpeg\bin\ffmpeg.exe"
    if os.path.exists(ffmpeg_exe):
        print("\n FFmpeg installed successfully!")
        print(f"  Location : C:\\ffmpeg\\bin\\ffmpeg.exe")
        print(f"  PATH     : C:\\ffmpeg\\bin added to system")
        print("\n Restart your terminal for PATH changes to take effect.")
    else:
        print("\n Installation may have failed — ffmpeg.exe not found.")

def main():
    if not is_admin():
        print("Requesting admin privileges...")
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        sys.exit()
    
    print("=" * 45)
    print("     FFmpeg Auto Installer for Windows")
    print("=" * 45)
    
    try:
        url, filename   = get_latest_ffmpeg_url()
        zip_path        = download_ffmpeg(url, filename)
        bin_source      = extract_ffmpeg(zip_path)
        bin_path        = install_ffmpeg(bin_source)
        add_to_system_path(bin_path)
        verify_install()
        
        # Cleanup
        os.remove(zip_path)
        
    except Exception as e:
        print(f"\n Error: {e}")
    
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()
