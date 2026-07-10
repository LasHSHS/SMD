import httpx
from packaging import version as pkg_version
from .version import __version__

# Placeholder URL - User needs to update this!
UPDATE_URL = "https://example.com/smd_version.json"

def check_for_updates():
    """
    Checks for updates against a remote JSON file.
    Expected JSON format:
    {
        "version": "1.0.1",
        "url": "https://example.com/downloads/smd_v1.0.1.zip",
        "release_notes": "Fixed bugs..."
    }
    Returns a dict with update info if a newer version is available, else None.
    """
    try:
        # Short timeout to not block startup too long
        response = httpx.get(UPDATE_URL, timeout=3.0, follow_redirects=True)
        response.raise_for_status()
        data = response.json()
        
        remote_ver_str = data.get("version")
        download_url = data.get("url")
        
        if not remote_ver_str or not download_url:
            return None
            
        current_ver = pkg_version.parse(__version__)
        remote_ver = pkg_version.parse(remote_ver_str)
        
        if remote_ver > current_ver:
            return {
                "version": remote_ver_str,
                "url": download_url,
                "release_notes": data.get("release_notes", "New version available!")
            }
            
    except Exception:
        # Silently fail on network errors or invalid data to not annoy user
        pass
        
    return None
