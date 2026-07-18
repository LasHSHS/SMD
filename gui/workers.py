"""Background QThread workers used by the SMD desktop GUI."""
from __future__ import annotations

import base64
import html
import json
import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import folium
from folium.plugins import MarkerCluster
from PIL import Image
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QPixmap


def _map_base_tile(*, dark: bool) -> str:
    return "CartoDB.DarkMatter" if dark else "OpenStreetMap"


def _add_map_layer_options(m: folium.Map, *, dark: bool) -> None:
    """Optional basemaps alongside the theme default (street / dark / satellite / terrain)."""
    if dark:
        folium.TileLayer(
            tiles="OpenStreetMap",
            name="Light map",
            overlay=False,
            control=True,
        ).add_to(m)
    else:
        folium.TileLayer(
            tiles="CartoDB.DarkMatter",
            name="Dark map",
            overlay=False,
            control=True,
        ).add_to(m)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Satellite',
        overlay=False,
        control=True,
    ).add_to(m)
    folium.TileLayer(
        tiles='OpenTopoMap',
        name='Terrain',
        overlay=False,
        control=True,
    ).add_to(m)


def _create_themed_map(
    location: list[float],
    zoom_start: int,
    *,
    dark: bool,
    control_scale: bool = False,
) -> folium.Map:
    """Create a folium map with theme-appropriate default tiles and alternates."""
    m = folium.Map(
        location=location,
        zoom_start=zoom_start,
        tiles=_map_base_tile(dark=dark),
        control_scale=control_scale,
    )
    _add_map_layer_options(m, dark=dark)
    return m


def generate_thumbnail_base64(media_path, max_size=150):
    """Base64 thumbnail for map popups (photo or video). Thread-safe:
    pure PIL/ffmpeg, no Qt objects, unique temp files per call."""
    path = Path(media_path)
    try:
        if path.suffix.lower() in ('.mp4', '.mov', '.m4v', '.mkv', '.avi'):
            return _video_frame_thumbnail_b64(path, max_size)
        img = Image.open(path)
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
                img = background
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        import io
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=90)
        img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        return f"data:image/jpeg;base64,{img_base64}"
    except Exception:
        return None


def _video_frame_thumbnail_b64(video_path: Path, max_size: int = 150):
    """Extract one frame with ffmpeg for map popup."""
    import uuid

    from smd.ffmpeg_bundle import resolve_ffmpeg
    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return None
    tmp = Path(tempfile.gettempdir()) / f"smd_thumb_{uuid.uuid4().hex[:12]}.jpg"
    try:
        startupinfo = None
        creationflags = 0
        if sys.platform.startswith('win'):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW
        subprocess.run(
            [
                ffmpeg, '-nostdin', '-y', '-ss', '0.5', '-i', str(video_path),
                '-vframes', '1', '-q:v', '2', str(tmp),
            ],
            capture_output=True,
            timeout=15,
            startupinfo=startupinfo,
            creationflags=creationflags,
            check=False,
        )
        if not tmp.is_file() or tmp.stat().st_size < 100:
            return None
        img = Image.open(tmp)
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        import io
        buffer = io.BytesIO()
        img.convert('RGB').save(buffer, format='JPEG', quality=90)
        return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('utf-8')}"
    except Exception:
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


class MapRenderWorker(QThread):
    """Background thread for rendering folium map (non-blocking)"""
    progress = pyqtSignal(int, str)  # progress_percent, status_text
    finished = pyqtSignal(str)  # html_file_path
    error = pyqtSignal(str)
    
    def __init__(self, locations, *, thumbnails=None, dark_mode=False):
        super().__init__()
        self.locations = locations
        self.thumbnails = thumbnails or {}
        self.dark_mode = dark_mode

    def _thumbnail_for(self, full_path: str):
        """Cached thumbnail lookup; generates in this worker thread on miss."""
        if full_path in self.thumbnails:
            return self.thumbnails[full_path]
        b64 = generate_thumbnail_base64(full_path)
        self.thumbnails[full_path] = b64
        return b64
    
    def run(self):
        try:
            from collections import defaultdict
            
            self.progress.emit(5, 'Building marker groups...')
            
            try:
                # Find the latest file to center map
                latest_location = max(self.locations, key=lambda x: x.get('modified', 0))
                center_lat = latest_location['coords'][0]
                center_lon = latest_location['coords'][1]
            except (ValueError, IndexError, KeyError) as e:
                print(f"DEBUG: Error finding map center: {e}")
                # Default to center of US
                center_lat, center_lon = 39.8283, -98.5795
            
            self.progress.emit(10, 'Creating base map...')
            
            try:
                dark = bool(self.dark_mode)
                m = _create_themed_map(
                    [center_lat, center_lon],
                    8,
                    dark=dark,
                    control_scale=True,
                )
            except Exception as e:
                print(f"DEBUG: Error creating folium map: {e}")
                self.error.emit(f'Failed to create map: {str(e)}')
                return
            
            # Create marker cluster
            try:
                self.progress.emit(25, '📍 Creating marker cluster...')
                marker_cluster = MarkerCluster(
                    name='Photos/Videos',
                    overlay=True,
                    control=False,
                    show=True
                ).add_to(m)
            except Exception as e:
                print(f"DEBUG: Error creating marker cluster: {e}")
                marker_cluster = None
                self.error.emit(f'Warning: Could not create marker cluster: {str(e)}')
            
            # Group locations by coordinates
            try:
                self.progress.emit(30, '🧮 Grouping locations...')
                grouped_locations = defaultdict(list)
                for loc in self.locations:
                    try:
                        coord_key = (round(loc['coords'][0], 5), round(loc['coords'][1], 5))
                        grouped_locations[coord_key].append(loc)
                    except (KeyError, TypeError) as e:
                        print(f"DEBUG: Error processing location: {e}, loc: {loc}")
                        continue
            except Exception as e:
                print(f"DEBUG: Error grouping locations: {e}")
                self.error.emit(f'Error processing locations: {str(e)}')
                return
            
            total_groups = len(grouped_locations)
            if total_groups == 0:
                print("DEBUG: No locations to display on map")
                self.error.emit('No valid locations found to display on map')
                return
            
            current_group = 0
            
            # Add markers
            all_files_json = {}
            
            for coord_key, loc_group in grouped_locations.items():
                try:
                    current_group += 1
                    progress_val = 30 + int((current_group / total_groups) * 60)
                    self.progress.emit(progress_val, f'📌 Adding markers ({current_group}/{total_groups})...')
                    
                    primary_loc = loc_group[0]
                    
                    # Thumbnails generated here in the worker thread (pure PIL/ffmpeg, no Qt).
                    thumbnail_b64 = None
                    for loc in loc_group:
                        try:
                            thumbnail_b64 = self._thumbnail_for(loc['full_path'])
                            if thumbnail_b64:
                                break
                        except Exception as thumb_err:
                            print(f"DEBUG: Error generating thumbnail: {thumb_err}")
                    
                    # Create popup HTML
                    try:
                        file_list = '<br>'.join([f"• {html.escape(loc['filename'])}" for loc in loc_group[:10]])
                        if len(loc_group) > 10:
                            file_list += f"<br>• ... and {len(loc_group) - 10} more"
                        
                        safe_file_path = primary_loc['full_path'].replace('\\', '/').replace("'", "\\'").replace('"', '\\"')
                        thumb_html = ""
                        if thumbnail_b64:
                            thumb_html = f'<img src="{thumbnail_b64}" style="max-width:180px;max-height:120px;border-radius:4px;margin-bottom:6px;"><br>'

                        popup_html = f"""
                            <div style="min-width:200px; max-width:300px;" data-filepath="{safe_file_path}">
                                {thumb_html}
                                <b style="font-size:14px;">{len(loc_group)} file(s) at this location</b><br>
                                <div style="margin-top:8px; max-height:120px; overflow-y:auto; font-size:11px;">
                                    {file_list}
                                </div>
                                <small style="color:#999; margin-top:5px; display:block; font-size:10px;">
                                    📍 {primary_loc['coords'][0]:.6f}, {primary_loc['coords'][1]:.6f}
                                </small>
                            </div>
                        """
                    except Exception as popup_err:
                        print(f"DEBUG: Error creating popup HTML: {popup_err}")
                        popup_html = f"""
                            <div style="min-width:200px; max-width:300px;">
                                <b>{len(loc_group)} file(s) at this location</b>
                            </div>
                        """
                    
                    # Create tooltip
                    try:
                        safe_filename = html.escape(primary_loc['filename'])
                        if thumbnail_b64:
                            tooltip_html = f"""
                            <div style="text-align:center; background:white; padding:5px; border-radius:5px;">
                                <img src="{thumbnail_b64}" style="max-width:150px; max-height:150px; border-radius:3px;"><br>
                                <small style="color:#333; margin-top:3px; display:block;"><b>{safe_filename}</b></small>
                                <small style="color:#666; font-size:9px;">{len(loc_group)} file(s) here</small>
                            </div>
                            """
                            tooltip = folium.Tooltip(tooltip_html, sticky=True)
                        else:
                            tooltip_text = f"{len(loc_group)} files: {safe_filename}"
                            tooltip = folium.Tooltip(tooltip_text, sticky=True)
                    except Exception as tooltip_err:
                        print(f"DEBUG: Error creating tooltip: {tooltip_err}")
                        tooltip = folium.Tooltip(f"{len(loc_group)} files at location", sticky=True)
                    
                    # Add marker
                    try:
                        folium.Marker(
                            location=primary_loc['coords'],
                            popup=folium.Popup(popup_html, max_width=350),
                            tooltip=tooltip,
                            icon=folium.Icon(
                                color='red' if primary_loc.get('type') == 'image' else 'blue',
                                icon='camera' if primary_loc.get('type') == 'image' else 'video-camera',
                                prefix='fa'
                            )
                        ).add_to(marker_cluster if marker_cluster else m)
                    except Exception as marker_err:
                        print(f"DEBUG: Error adding marker: {marker_err}")
                        # Skip this marker but continue
                        pass
                    
                    # Store file data for click handling
                    try:
                        coord_str = f"{coord_key[0]:.5f},{coord_key[1]:.5f}"
                        all_files_json[coord_str] = [{'path': loc['full_path'], 'name': loc['filename']} for loc in loc_group]
                    except Exception as data_err:
                        print(f"DEBUG: Error storing file data: {data_err}")
                        pass
                
                except Exception as e:
                    print(f"DEBUG: Error processing marker group: {e}")
                    continue
            
            try:
                self.progress.emit(92, '🔗 Adding layer controls...')
                folium.LayerControl().add_to(m)
            except Exception as e:
                print(f"DEBUG: Error adding layer controls: {e}")
                pass
            
            try:
                self.progress.emit(95, 'Generating HTML...')
                
                # Add JavaScript with file data
                all_files_json_str = json.dumps(all_files_json)
                from smd.theme import LIGHT_SECONDARY, LIGHT_SECONDARY_HOVER

                custom_js = f"""
                <script>
                window.fileData = {all_files_json_str};
                
                window.addEventListener('resize', function() {{
                    if (typeof map !== 'undefined') {{
                        map.invalidateSize();
                    }}
                }});
                </script>
                <style>
                .leaflet-popup-content {{
                    margin: 13px 19px;
                    line-height: 1.4;
                }}
                .leaflet-popup-content button:hover {{
                    background-color: {LIGHT_SECONDARY_HOVER} !important;
                    transform: scale(1.02);
                    transition: all 0.2s;
                }}
                .leaflet-tooltip {{
                    background-color: rgba(255, 255, 255, 0.95);
                    border: 2px solid {LIGHT_SECONDARY};
                    border-radius: 8px;
                    padding: 8px;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
                }}
                </style>
                """
                m.get_root().html.add_child(folium.Element(custom_js))
            except Exception as e:
                print(f"DEBUG: Error adding custom JavaScript: {e}")
                pass
            
            try:
                # Save map to file
                self.progress.emit(98, 'Saving map file...')
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.html', mode='w', encoding='utf-8')
                temp_path = temp_file.name
                temp_file.close()
                
                m.save(temp_path)
                
                print(f"DEBUG: Map saved to {temp_path}")
                
                # Inject JavaScript for auto-opening files
                try:
                    with open(temp_path, 'r', encoding='utf-8') as f:
                        html_content = f.read()
                    
                    # Add script before closing body tag
                    auto_open_script = """
                    <script>
                    // Auto-open file when a marker's popup opens
                    document.addEventListener('DOMContentLoaded', function() {
                        if (typeof map !== 'undefined') {
                            map.on('popupopen', function(e) {
                                try {
                                    var content = e.popup.getContent();
                                    var div = document.createElement('div');
                                    div.innerHTML = content;
                                    var target = div.querySelector('div[data-filepath]');
                                    if (target) {
                                        var filepath = target.getAttribute('data-filepath');
                                        if (filepath) {
                                            console.log('Auto-opening file:', filepath);
                                            window.pyOpenFile = filepath;
                                        }
                                    }
                                } catch (err) {
                                    console.log('popupopen handler error', err);
                                }
                            });
                        }
                    });
                    </script>
                    """
                    html_content = html_content.replace('</body>', auto_open_script + '</body>')
                    
                    with open(temp_path, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    
                    print("DEBUG: Auto-open JavaScript injected into map HTML")
                except Exception as inject_err:
                    print(f"WARNING: Could not inject auto-open JavaScript: {inject_err}")
                
                self.progress.emit(100, 'Map rendered!')
                self.finished.emit(temp_path)
            except Exception as save_err:
                print(f"DEBUG: Error saving map: {save_err}")
                self.error.emit(f'Failed to save map: {str(save_err)}')
                return
            
        except Exception as e:
            print(f"DEBUG: Unexpected error in MapRenderWorker: {e}")
            import traceback
            traceback.print_exc()
            self.error.emit(f'Unexpected error rendering map: {str(e)}')

class ScanWorker(QThread):
    finished = pyqtSignal(int)
    output = pyqtSignal(str)
    progress = pyqtSignal(int)
    
    @staticmethod
    def detect_file_type(file_path: Path):
        """Detect actual file type from magic bytes/file header using smd.utils"""
        from smd.utils import detect_ext_from_bytes
        try:
            with open(file_path, 'rb') as f:
                header = f.read(32) # Read enough bytes
            ext = detect_ext_from_bytes(header)
            return ext.replace('.', '') if ext else None
        except Exception:
            return None

    
    def __init__(self, folder, dry_run=False):
        super().__init__()
        self.folder = folder
        self.dry_run = bool(dry_run)
        self.renamed_count = 0
        self.total_scanned = 0
        self.planned_count = 0
    
    def run(self):
        try:
            folder_path = Path(self.folder)
            if not folder_path.exists() or not folder_path.is_dir():
                self.output.emit(f'Error: Folder not found or not a directory: {folder_path}')
                self.finished.emit(1)
                return

            files = [p for p in sorted(folder_path.rglob('*'))
                     if p.is_file() and p.suffix.lower() in {'.jpg', '.jpeg', '.png', '.heic', '.mp4', '.mov', '.m4v'}]
            total = len(files)
            self.total_scanned = total

            self.output.emit('\n' + '=' * 72)
            title = 'File Extension Checker - Read-Only Report' if self.dry_run else 'File Extension Fixer - Magic Byte Scanner'
            self.output.emit(title)
            self.output.emit('=' * 72)
            self.output.emit(f'\nScanning folder: {folder_path}')

            if total == 0:
                self.output.emit('No .jpg/.jpeg/.mp4/.m4v files found to scan.')
                self.progress.emit(100)
                self.finished.emit(0)
                return

            renamed_count = 0
            already_correct = 0
            unrecognized = 0
            errors = 0

            for idx, file_path in enumerate(files, start=1):
                actual_type = self.detect_file_type(file_path)

                if actual_type is None:
                    unrecognized += 1
                    self.output.emit(f'[!] {file_path.name:50} - [unrecognized]')
                else:
                    suffix = file_path.suffix.lower()
                    if (actual_type == 'jpg' and suffix in ['.jpg', '.jpeg']) or \
                       (actual_type == 'mp4' and suffix in ['.mp4', '.m4v']):
                        already_correct += 1
                    else:
                        new_suffix = '.jpg' if actual_type == 'jpg' else '.mp4'
                        new_name = file_path.stem + new_suffix
                        new_path = file_path.parent / new_name

                        if new_path.exists():
                            self.output.emit(f'[!] {file_path.name:50} -> {new_name} (target exists, skipped)')
                            errors += 1
                        else:
                            if self.dry_run:
                                self.planned_count += 1
                                self.output.emit(f'[~] {file_path.name:50} -> {new_name} (planned)')
                            else:
                                try:
                                    file_path.rename(new_path)
                                    renamed_count += 1
                                    self.output.emit(f'[+] {file_path.name:50} -> {new_name}')
                                except Exception as e:
                                    errors += 1
                                    self.output.emit(f'[E] {file_path.name:50} - Error: {e}')

                progress = int((idx / total) * 100)
                self.progress.emit(progress)

            # Summary
            self.output.emit('\n' + '=' * 72)
            self.output.emit('Summary')
            self.output.emit('=' * 72)
            self.output.emit(f'  [+] Renamed:      {renamed_count} files')
            if self.dry_run:
                self.output.emit(f'  [~] Planned:       {self.planned_count} files')
            self.output.emit(f'  [*] Correct:       {already_correct} files')
            self.output.emit(f'  [!] Unrecognized: {unrecognized} files')
            self.output.emit(f'  [E] Errors:       {errors} files')
            self.output.emit(f'  [*] Total:        {total} files scanned')

            self.renamed_count = renamed_count

            if self.dry_run:
                if self.planned_count > 0:
                    self.output.emit(
                        f'\n[~] {self.planned_count} file(s) have a mismatched extension. '
                        'This is a read-only report - nothing was renamed.'
                    )
                else:
                    self.output.emit('\n[*] All files appear correctly labeled!')
            else:
                if renamed_count > 0:
                    self.output.emit(f'\n[+] {renamed_count} files renamed successfully!')
                else:
                    self.output.emit('\n[*] All files have correct extensions!')

            self.finished.emit(0)
        except Exception as e:
            self.output.emit(f'[E] Error: {str(e)}')
            self.finished.emit(1)

class MapWorker(QThread):
    finished = pyqtSignal(list, int, int)  # locations, total_images, total_videos
    progress = pyqtSignal(int, int, int, str, float)  # current, total, found, eta, speed
    file_detail = pyqtSignal(str, str, dict)  # filename, status, metadata
    error = pyqtSignal(str)
    
    def __init__(self, folder, parent_gui, json_path=None):
        super().__init__()
        self.folder = folder
        self.parent_gui = parent_gui
        self.json_path = json_path
        self.cancelled = False
        self.json_coords_lookup = {}  # {filename_stem: (lat, lon)}
        self.scan_report: dict = {}
    
    def process_file(self, file_path):
        """Scan one media file for GPS, extension label, and stats."""
        from smd.map_gps import lookup_json_coords
        from smd.media_types import (
            IMAGE_EXTENSIONS,
            MAGIC_CHECK_EXTENSIONS,
            VIDEO_EXTENSIONS,
            extension_matches_magic,
        )

        suffix = file_path.suffix.lower()
        file_type = None
        embedded_coords = None

        dimensions = None
        if suffix in IMAGE_EXTENSIONS:
            from smd.metadata import extract_gps_image
            embedded_coords = extract_gps_image(file_path)
            file_type = 'image'
            dimensions = _image_dimensions(file_path)
        elif suffix in VIDEO_EXTENSIONS:
            from smd.metadata import extract_gps_video
            embedded_coords = extract_gps_video(file_path)
            file_type = 'video'
        else:
            return None

        coords = embedded_coords
        gps_source = 'embedded' if coords else None
        if not coords and self.json_coords_lookup:
            coords = lookup_json_coords(self.json_coords_lookup, file_path)
            if coords:
                gps_source = 'json'

        extension_mismatch = False
        if suffix in MAGIC_CHECK_EXTENSIONS:
            actual_type = ScanWorker.detect_file_type(file_path)
            extension_mismatch = not extension_matches_magic(suffix, actual_type)

        file_size = file_path.stat().st_size
        base = {
            'filename': file_path.name,
            'path': file_path.as_posix(),
            'full_path': str(file_path),
            'type': file_type,
            'size': file_size,
            'modified': file_path.stat().st_mtime,
            'gps_source': gps_source,
            'extension_mismatch': extension_mismatch,
            'dimensions': dimensions,
        }
        if coords:
            base['coords'] = coords
            base['gps_source'] = gps_source
        return base
    
    def run(self):
        try:
            folder_path = Path(self.folder)
            
            # Build JSON lookup if provided
            if self.json_path and Path(self.json_path).exists():
                try:
                    from smd.map_gps import build_json_coord_lookup
                    from smd.utils import load_memories

                    print(f"DEBUG: MapWorker loading JSON: {self.json_path}")
                    memories = load_memories(Path(self.json_path))
                    self.json_coords_lookup = build_json_coord_lookup(memories)
                except Exception as e:
                    print(f"ERROR loading JSON for mapping: {e}")

            from smd.media_types import MEDIA_EXTENSIONS

            # Collect all media files first
            all_files = [
                f for f in folder_path.rglob('*')
                if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
            ]

            total_files = len(all_files)
            if total_files == 0:
                self.error.emit('No supported media files found')
                self.scan_report = {}
                self.finished.emit([], 0, 0)
                return

            locations = []
            total_images = 0
            total_videos = 0
            file_types: dict[str, dict[str, int]] = {}
            extension_mismatches = 0
            resolution_counts: dict[str, int] = {}
            gps_embedded = {'image': 0, 'video': 0}
            gps_json = {'image': 0, 'video': 0}
            gps_missing = {'image': 0, 'video': 0}
            processed = 0
            start_time = time.time()
            last_progress_time = start_time
            
            # Adaptive threading from system profile (GPS scan)
            cpu_count = os.cpu_count() or 2
            perf_mode = getattr(self.parent_gui, 'performance_mode', 'balanced')
            from smd.system_profile import compute_workers, get_system_profile

            settings = compute_workers(perf_mode, get_system_profile(), task="gps")
            max_workers = settings.max_workers
            
            # Adaptive batch processing for ultra-large file sets
            batch_size = min(max_workers * 50, 1000)  # Process in batches to reduce memory pressure
            
            # Adaptive batch processing: prevents memory overflow on ultra-large datasets
            # while maintaining maximum throughput
            batches = [all_files[i:i + batch_size] for i in range(0, len(all_files), batch_size)]
            
            # Track performance metrics for dynamic adjustment
            batch_times = []
            
            for batch_idx, batch in enumerate(batches):
                batch_start_time = time.time()
                
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit batch for processing
                    future_to_file = {executor.submit(self.process_file, f): f for f in batch}
                    
                    # Process results as they complete
                    for future in as_completed(future_to_file):
                        if self.cancelled:
                            executor.shutdown(wait=False, cancel_futures=True)
                            self.error.emit('Scan cancelled by user')
                            self.scan_report = {
                                'total_media': total_images + total_videos,
                                'total_images': total_images,
                                'total_videos': total_videos,
                                'file_types': file_types,
                                'extension_mismatches': extension_mismatches,
                                'resolution_counts': resolution_counts,
                                'gps_embedded': gps_embedded,
                                'gps_json': gps_json,
                                'gps_missing': gps_missing,
                            }
                            self.finished.emit(locations, total_images, total_videos)
                            return
                        
                        file_path = future_to_file[future]
                        processed += 1
                        
                        try:
                            result = future.result()
                            if not result:
                                continue

                            suffix = file_path.suffix.lower()
                            file_type = result['type']
                            file_size = result['size']
                            if file_type == 'image':
                                total_images += 1
                            else:
                                total_videos += 1

                            ext_key = suffix or 'no_extension'
                            if ext_key not in file_types:
                                file_types[ext_key] = {'count': 0, 'size': 0}
                            file_types[ext_key]['count'] += 1
                            file_types[ext_key]['size'] += file_size

                            if result.get('extension_mismatch'):
                                extension_mismatches += 1

                            dims = result.get('dimensions')
                            if dims:
                                res_key = f"{dims[0]}x{dims[1]}"
                                resolution_counts[res_key] = resolution_counts.get(res_key, 0) + 1

                            file_modified = datetime.fromtimestamp(result['modified'])
                            metadata = {
                                'size': file_size,
                                'size_mb': file_size / (1024 * 1024),
                                'modified': file_modified.strftime('%Y-%m-%d %H:%M:%S'),
                                'type': suffix,
                            }

                            gps_source = result.get('gps_source')
                            if gps_source == 'embedded':
                                gps_embedded[file_type] += 1
                            elif gps_source == 'json':
                                gps_json[file_type] += 1
                            else:
                                gps_missing[file_type] += 1

                            if 'coords' in result:
                                locations.append(result)
                                metadata['coords'] = result['coords']
                                metadata['lat'] = f"{result['coords'][0]:.6f}"
                                metadata['lon'] = f"{result['coords'][1]:.6f}"
                                metadata['gps_source'] = gps_source
                                self.file_detail.emit(result['filename'], 'found', metadata)
                            else:
                                self.file_detail.emit(file_path.name, 'no-gps', metadata)
                        except Exception:
                            pass
                        
                        # Calculate ETA and speed
                        elapsed = time.time() - start_time
                        if processed > 10:
                            avg_time_per_file = elapsed / processed
                            remaining_files = total_files - processed
                            eta_seconds = avg_time_per_file * remaining_files
                            if eta_seconds > 60:
                                eta_str = f"{int(eta_seconds / 60)}m {int(eta_seconds % 60)}s"
                            else:
                                eta_str = f"{int(eta_seconds)}s"
                            
                            # Calculate speed (files/sec)
                            files_per_sec = processed / elapsed if elapsed > 0 else 0
                        else:
                            eta_str = "calculating..."
                            files_per_sec = 0
                        
                        # Emit progress every 10 files or at completion
                        if processed % 10 == 0 or processed == total_files:
                            self.progress.emit(processed, total_files, len(locations), eta_str, files_per_sec)
                
                # Track batch performance
                batch_elapsed = time.time() - batch_start_time
                batch_times.append(batch_elapsed)
                
                # Dynamic thread adjustment: if processing is too slow, warn user
                if len(batch_times) >= 2 and perf_mode == 'maximum':
                    avg_batch_time = sum(batch_times) / len(batch_times)
                    # If batches are taking longer than expected, system might be bottlenecked
                    if avg_batch_time > 10 and cpu_count >= 8:
                        # High-end system but slow processing = likely I/O bottleneck
                        pass  # Continue with current settings
            
            self.scan_report = {
                'total_media': total_images + total_videos,
                'total_images': total_images,
                'total_videos': total_videos,
                'file_types': file_types,
                'extension_mismatches': extension_mismatches,
                'resolution_counts': resolution_counts,
                'gps_embedded': gps_embedded,
                'gps_json': gps_json,
                'gps_missing': gps_missing,
            }
            self.finished.emit(locations, total_images, total_videos)
        except Exception as e:
            self.error.emit(str(e))
            self.scan_report = {}
            self.finished.emit([], 0, 0)

class StagingCheckWorker(QThread):
    """Verify staging folder can be safely deleted."""
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, account_dir):
        super().__init__()
        self.account_dir = Path(account_dir)

    def run(self):
        try:
            from smd.account_layout import resolve_account_paths
            from smd.staging_check import check_staging_readiness, save_staging_readiness_report

            paths = resolve_account_paths(self.account_dir, migrate=False, create=False)
            report = check_staging_readiness(self.account_dir, layout=paths)
            save_staging_readiness_report(paths, report)
            self.finished.emit(report)
        except Exception as exc:
            self.error.emit(str(exc))


class DuplicateScanWorker(QThread):
    """Hash merged/ off the UI thread so 'Review duplicates' never freezes
    the window, even on large libraries."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, paths):
        super().__init__()
        self.paths = paths

    def run(self):
        try:
            from smd.duplicates import scan_content_duplicates

            report = scan_content_duplicates(
                self.paths,
                move_to_folder=False,
                status_callback=self.progress.emit,
            )
            self.finished.emit(report)
        except Exception as exc:
            self.error.emit(str(exc))


class StagingVerifyWorker(QThread):
    """Runs the post-run staging integrity check off the UI thread.

    check_staging_readiness() ffprobes *every* video by design (an earlier
    fix traded a 25-file sample for full certainty before staging/ gets
    deleted) - for a library with thousands of videos that can take minutes,
    and running it directly on the GUI thread made SMD look frozen right
    after a run finished, even though every file was already saved safely."""
    finished_ok = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, account_dir, paths, require_raw):
        super().__init__()
        self.account_dir = account_dir
        self.paths = paths
        self.require_raw = require_raw

    def run(self):
        try:
            from smd.staging_check import check_staging_readiness

            readiness = check_staging_readiness(
                self.account_dir, layout=self.paths, require_raw=self.require_raw
            )
            self.finished_ok.emit(readiness)
        except Exception as exc:
            self.error.emit(str(exc))


class CompletionFinalizeWorker(QThread):
    """Delete staging (when safe) and build the session report off the UI thread.

    build_session_report() Pillow-validates every merged photo and walks the
    output tree for folder sizes - minutes of work on large libraries if run
    on the GUI thread right after StagingVerifyWorker returns."""
    finished_ok = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, paths, stats, keep_raw, readiness, skipped_by_setting, *, success=True):
        super().__init__()
        self.paths = paths
        self.stats = stats
        self.keep_raw = keep_raw
        self.readiness = readiness
        self.skipped_by_setting = skipped_by_setting
        self.success = success

    def run(self):
        try:
            from smd.account_layout import format_bytes
            from smd.session_report import build_session_report, save_session_report
            from smd.staging_check import delete_staging_folder

            staging_deleted = False
            staging_freed = ""
            if (
                not self.skipped_by_setting
                and self.readiness is not None
                and self.readiness.safe_to_delete
            ):
                ok, _msg = delete_staging_folder(
                    self.paths.account_dir, report=self.readiness, layout=self.paths
                )
                if ok:
                    staging_deleted = True
                    staging_freed = format_bytes(self.readiness.staging_bytes)

            report = build_session_report(
                self.paths.account_dir,
                stats=self.stats,
                success=self.success,
                require_raw=self.keep_raw,
                staging_deleted=staging_deleted,
                staging_freed=staging_freed,
                layout=self.paths,
                readiness=self.readiness,
                skip_staging_check=self.skipped_by_setting,
            )
            save_session_report(self.paths, report)
            self.finished_ok.emit(report)
        except Exception as exc:
            self.error.emit(str(exc))


class TechnicalStorageWorker(QThread):
    """Scan technical folder sizes off the UI thread (Technical view only)."""
    finished_ok = pyqtSignal(object, object)
    error = pyqtSignal(str)

    def __init__(self, paths, account_name: str):
        super().__init__()
        self.paths = paths
        self.account_name = account_name

    def run(self):
        try:
            from smd.account_layout import technical_storage_summary

            rows = technical_storage_summary(self.paths)
            self.finished_ok.emit(self.account_name, rows)
        except Exception as exc:
            self.error.emit(str(exc))


class DuplicatePreviewWorker(QThread):
    """Load duplicate-review thumbnails and captions off the UI thread."""
    preview_ready = pyqtSignal(str, object, str)
    finished_all = pyqtSignal()

    def __init__(self, media_jobs: list[tuple[Path, int]]):
        super().__init__()
        self.media_jobs = media_jobs

    def run(self):
        for media_path, max_dim in self.media_jobs:
            key = str(media_path)
            try:
                img = _pil_preview_image(media_path, max_dim)
                caption = _media_caption(media_path)
            except Exception:
                img = None
                caption = ''
            self.preview_ready.emit(key, img, caption)
        self.finished_all.emit()


def _video_frame_pil_image(video_path: Path) -> Image.Image | None:
    """Extract a single preview frame from a video file."""
    from smd.ffmpeg_bundle import resolve_ffmpeg

    ffmpeg = resolve_ffmpeg()
    if not ffmpeg:
        return None
    tmp = Path(tempfile.gettempdir()) / f"smd_dup_thumb_{video_path.stem[:24]}.jpg"
    try:
        startupinfo = None
        creationflags = 0
        if sys.platform.startswith('win'):
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            creationflags = subprocess.CREATE_NO_WINDOW
        subprocess.run(
            [
                ffmpeg, '-nostdin', '-y', '-ss', '0.5', '-i', str(video_path),
                '-vframes', '1', '-q:v', '2', str(tmp),
            ],
            capture_output=True,
            timeout=20,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        if tmp.is_file() and tmp.stat().st_size > 0:
            return Image.open(tmp)
    except Exception:
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return None


def _image_dimensions(image_path: Path) -> tuple[int, int] | None:
    """Cheap (width, height) read - Image.open() only parses the header, it
    does not decode pixel data, so this is safe to call for every photo
    during a File Checker scan without a meaningful speed cost.

    Deliberately image-only: getting video dimensions needs a dedicated
    ffprobe subprocess per file, which would meaningfully slow down
    scanning a library with thousands of videos, for a "fun stats" feature.
    """
    try:
        with Image.open(image_path) as img:
            return img.size
    except Exception:
        return None


def _pil_preview_image(media_path: Path, max_dim: int) -> Image.Image | None:
    """Load a photo or video frame scaled for on-screen preview."""
    if not media_path.is_file():
        return None
    ext = media_path.suffix.lower()
    try:
        if ext in ('.mp4', '.mov', '.m4v', '.mkv', '.avi'):
            img = _video_frame_pil_image(media_path)
        elif ext in ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp'):
            img = Image.open(media_path)
        else:
            return None
        if img is None:
            return None
        if img.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'P':
                img = img.convert('RGBA')
            if img.mode in ('RGBA', 'LA'):
                background.paste(img, mask=img.split()[-1])
                img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')
        img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
        return img
    except Exception:
        return None


def _qpixmap_from_pil(img: Image.Image) -> QPixmap | None:
    """Convert a PIL image to QPixmap on the GUI thread."""
    try:
        from PIL import ImageQt

        pix = ImageQt.toqpixmap(img)
        if pix is not None and not pix.isNull():
            return pix
    except Exception:
        pass
    try:
        import io

        from PyQt5.QtGui import QImage

        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=90)
        qimg = QImage.fromData(buf.getvalue(), 'JPEG')
        if qimg.isNull():
            return None
        return QPixmap.fromImage(qimg)
    except Exception:
        return None


def _pixmap_for_media(media_path: Path, max_dim: int) -> QPixmap | None:
    img = _pil_preview_image(media_path, max_dim)
    if img is None:
        return None
    return _qpixmap_from_pil(img)


def _video_duration_seconds(video_path: Path) -> float | None:
    """Clip length in seconds via ffprobe, or None if unavailable."""
    from smd.ffmpeg_bundle import resolve_ffprobe
    from smd.procutil import subprocess_flags

    ffprobe = resolve_ffprobe()
    if not ffprobe:
        return None
    try:
        startupinfo, creationflags = subprocess_flags()
        result = subprocess.run(
            [
                ffprobe, '-v', 'quiet', '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1', str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            startupinfo=startupinfo,
            creationflags=creationflags,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


def _format_clip_duration(seconds: float) -> str:
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _media_caption(media_path: Path) -> str:
    """One-line size (+ duration for videos) caption for a media card."""
    from smd.media_types import format_bytes, is_video_file

    try:
        size_text = format_bytes(media_path.stat().st_size)
    except OSError:
        size_text = '? size'
    if is_video_file(media_path):
        duration = _video_duration_seconds(media_path)
        if duration is not None:
            return f"{_format_clip_duration(duration)} - {size_text}"
    return size_text


class LocalExportWorker(QThread):
    """Process bundled Snapchat exports (media inside ZIP, fully offline)."""
    finished = pyqtSignal(int)
    output = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(
        self,
        seed_path,
        account_dir,
        json_path=None,
        merge_overlays=True,
        keep_raw=True,
        repair_videos=True,
        performance_mode="balanced",
        zip_paths=None,
        paths=None,
    ):
        super().__init__()
        self.seed_path = Path(seed_path)
        self.account_dir = Path(account_dir)
        self.paths = paths
        self.json_path = Path(json_path) if json_path else None
        self.merge_overlays = merge_overlays
        self.keep_raw = keep_raw
        self.repair_videos = repair_videos
        self.performance_mode = performance_mode
        self.zip_paths = [Path(p) for p in zip_paths] if zip_paths else None
        self.limit = 0
        self._should_cancel = False

    def cancel(self):
        self._should_cancel = True
        self.output.emit('[*] Cancelling processing...')

    def run(self):
        import re
        import threading
        from smd.local_pipeline import process_bundled_export
        from smd.account_layout import resolve_account_paths

        paths = self.paths or resolve_account_paths(self.account_dir, migrate=True)

        self._heartbeat_running = True
        self._last_status = ""

        def heartbeat():
            while self._heartbeat_running and not self._should_cancel:
                time.sleep(10)
                if self._last_status:
                    self.output.emit(f"⏳ Still working… {self._last_status}")

        threading.Thread(target=heartbeat, daemon=True).start()

        try:
            from smd.system_profile import compute_workers, get_system_profile

            profile = get_system_profile()
            settings = compute_workers(self.performance_mode, profile, task="export")
            self.output.emit(f"⚙️ {profile.summary()}")
            self.output.emit(
                f"⚙️ {settings.reason}: {settings.max_workers} parallel jobs, "
                f"max {settings.max_ffmpeg} ffmpeg × {settings.ffmpeg_threads} threads"
            )

            checkpoint = paths.checkpoint_path

            def status_callback(msg):
                self._last_status = msg
                m = re.search(r"Processing (\d+)/(\d+)", msg)
                if m:
                    current = int(m.group(1))
                    total_n = int(m.group(2))
                    self.progress.emit(current, total_n)
                    # Log every 25 files to avoid flooding Qt (was crashing GUI)
                    if current <= 3 or current % 25 == 0:
                        self.output.emit(msg)
                elif msg.startswith("⏳"):
                    pass  # heartbeat handled separately
                else:
                    self.output.emit(msg)

            stats = process_bundled_export(
                self.seed_path,
                self.account_dir,
                merge_overlays=self.merge_overlays,
                keep_raw=self.keep_raw,
                repair_videos=self.repair_videos,
                limit=self.limit,
                apply_meta=True,
                json_path=self.json_path or paths.json_path,
                status_callback=status_callback,
                should_stop=lambda: self._should_cancel,
                checkpoint_path=checkpoint,
                max_workers=settings.max_workers,
                max_ffmpeg=settings.max_ffmpeg,
                ffmpeg_threads=settings.ffmpeg_threads,
                zip_paths=self.zip_paths,
                layout=paths,
            )
            self.run_stats = stats
            for line in stats.summary_lines():
                self.output.emit(line)
            self.finished.emit(0 if not self._should_cancel else 1)
        except Exception as e:
            self.output.emit(f"Error in local export: {e}")
            import traceback
            tb = traceback.format_exc()
            self.output.emit(tb)
            try:
                log = paths.logs_dir / "processing_error.log"
                log.write_text(tb, encoding="utf-8")
            except OSError:
                pass
            self.finished.emit(1)
        finally:
            self._heartbeat_running = False
