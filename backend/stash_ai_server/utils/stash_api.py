import logging
from typing import Any, Dict
from urllib.parse import urlparse
from stash_ai_server.core.system_settings import get_value as sys_get
from stashapi.stashapp import StashInterface

_log = logging.getLogger(__name__)

class StashAPI:
    stash_url: str
    api_key: str | None
    stash_interface: StashInterface | None = None
    tag_id_cache: Dict[str, int] = {}
    tag_name_cache: Dict[int, str] = {}

    def __init__(self) -> None:
        self.stash_url = sys_get("STASH_URL")
        self.api_key = sys_get("STASH_API_KEY")
        if self.stash_url:
            self.stash_interface = _construct_stash_interface(self.stash_url, self.api_key)
        else:
            _log.error("STASH_URL not configured; Stash interface not available")

    # Tags
    
    def fetch_tag_id(self, tag_name: str, parent_id: int | None = None, create_if_missing: bool = False, use_cache: bool = True, add_to_cache: Dict[str, int] = None) -> int | None:
        if use_cache and tag_name in self.tag_id_cache:
            return self.tag_id_cache[tag_name]
        
        if create_if_missing:
            if parent_id is None:
                tag = self.stash_interface.find_tag(tag_name, create=True)["id"]
            else:
                tag = self.stash_interface.find_tag(tag_name)
                if tag is None:
                    tag = self.stash_interface.create_tag({"name":tag_name, "ignore_auto_tag": True, "parent_ids":[parent_id]})
                tag = tag["id"] if tag else None
        else:
            tag = self.stash_interface.find_tag(tag_name)
            tag = tag["id"]  if tag else None
        if tag:
            self.tag_id_cache[tag_name] = tag
            self.tag_name_cache[tag] = tag_name 
            if add_to_cache is not None and tag_name not in add_to_cache:
                add_to_cache[tag_name] = tag
            return tag
        return None

    def get_tags_with_parent(self, parent_tag_id: int) -> Dict[str, int]:
        return {item['name']: item['id'] for item in self.stash_interface.find_tags(f={"parents": {"value":parent_tag_id, "modifier":"INCLUDES"}}, fragment="id name")}

    def get_stash_tag_name(self, tag_id: int) -> str | None:
        """Get the tag name for a given tag ID from Stash."""
        if tag_id in self.tag_name_cache:
            return self.tag_name_cache[tag_id]
        try:
            tag_data = self.stash_interface.find_tag(tag_id)
            if tag_data and "name" in tag_data:
                self.tag_name_cache[tag_id] = tag_data["name"]
                self.tag_id_cache[tag_data["name"]] = tag_id
                return tag_data["name"]
            return None
        except Exception:
            _log.exception("Failed to get tag name for tag_id=%s", tag_id)
            return None

    # Images    

    def remove_tags_from_images(self, image_ids: list[int], tag_ids: list[int]) -> bool:
        self.stash_interface.update_images({"ids": image_ids, "tag_ids": {"ids": tag_ids, "mode": "REMOVE"}})

    def add_tags_to_images(self, image_ids: list[int], tag_ids: list[int]) -> bool:
        self.stash_interface.update_images({"ids": image_ids, "tag_ids": {"ids": tag_ids, "mode": "ADD"}})

    def get_image_paths(self, images_ids: list[int]) -> Dict[int, str]:
        """Fetch image paths for given image IDs."""
        out: Dict[int, str] = {}
        if not self.stash_interface:
            _log.warning("Stash interface not configured; returning empty image path map")
            return out
        try:
            images = self.stash_interface.find_images(image_ids=images_ids, fragment="id files {path}")
            _log.warning(f"Images: {images}")
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("Failed to fetch images for ids=%s: %s", images_ids, exc)
            return out
        for img in images or []:
            try:
                out[int(img["id"])] = img["files"][0]["path"]
            except Exception:
                # defensive: skip malformed entries
                continue
        _log.warning("Fetched image paths for ids=%s -> %s", images_ids, out)
        return out

    # Scenes

    def get_scene_path_and_tags(self, scene_id: int):
        scene_result = self.stash_interface.find_scene(id=scene_id, fragment="files {path} tags {id}")
        if not scene_result or 'files' not in scene_result or not scene_result['files']:
            return None, []
        path = scene_result['files'][0]['path']
        tags = [tag['id'] for tag in scene_result.get('tags', []) if 'id' in tag]
        return path, tags

    def add_tags_to_scene(self, scene_id: int, tag_ids: list[int]) -> None:
        if not tag_ids:
            return
        payload = {
            "ids": [scene_id],
            "tag_ids": {
                "ids": tag_ids,
                "mode": "ADD",
            },
        }
        self.stash_interface.update_scenes(payload)

    def remove_tags_from_scene(self, scene_id: int, tag_ids: list[int]) -> None:
        if not tag_ids:
            return
        payload = {
            "ids": [scene_id],
            "tag_ids": {
                "ids": tag_ids,
                "mode": "REMOVE",
            },
        }
        self.stash_interface.update_scenes(payload)
    
    # Scene Markers

    def destroy_scene_markers(self, marker_ids: list[int]):
        self.stash_interface.destroy_markers(marker_ids)

    def destroy_markers_with_tags(self, scene_id, tag_ids: list[int]):
        markers = self.stash_interface.find_scene_markers(
            scene_marker_filter={
                "tags": {"value": tag_ids, "modifier": "INCLUDES"},
                "scenes": {"value": [scene_id], "modifier": "EQUALS"}
            },
            fragment="id"
        )
        marker_ids = [marker['id'] for marker in markers] if markers else []
        if marker_ids:
            self.destroy_scene_markers(marker_ids)

    def create_scene_markers(self, scene_id: int,timespans: Dict[tuple[int, str], list[tuple[float, float]]]):
        for (tag_id, tag_name), spans in timespans.items():
            for start, end in spans:
                marker_data = {
                    "scene_id": scene_id,
                    "seconds": start,
                    "end_seconds": end,
                    "primary_tag_id": tag_id,
                    "tag_ids": [tag_id],
                    "title": tag_name,
                }
                self.stash_interface.create_scene_marker(marker_data)
        

def _have_valid_api_key(api_key) -> bool:
    return bool(api_key and api_key != 'REPLACE_WITH_API_KEY' and api_key.strip() != '')

def _construct_stash_interface(url: str, api_key: str = None) -> StashInterface:
    """Construct a StashInterface from environment variables."""
    parsed = urlparse(url)
    scheme = parsed.scheme or 'http'
    # Extract hostname and port separately so stashapi doesn't append default port again
    hostname = parsed.hostname or 'localhost'
    port = parsed.port if parsed.port else 3000
    conn: Dict[str, Any] = {
        'Scheme': scheme,
        'Host': hostname,
        'Port': port,
    }
    if _have_valid_api_key(api_key):
        conn['ApiKey'] = api_key
    return StashInterface(conn)

stash_api = StashAPI()