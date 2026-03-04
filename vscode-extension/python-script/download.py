"""
Dictionary download and cache (shared with VS Code extension).
"""

import logging
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from mmcif_types import DownloadError

logger = logging.getLogger(__name__)


def get_cache_dir() -> Path:
    """Return the cache directory for the validator (shared with the VS Code extension)."""
    return Path(tempfile.gettempdir()) / "mmcif-validator-cache"


def get_cached_dictionary_path() -> Path:
    """Return the path where the downloaded dictionary is cached (same as extension's cache)."""
    return get_cache_dir() / "mmcif_pdbx.dic"


def download_dictionary(url: str, cache_path: Optional[Path] = None) -> Path:
    """Download dictionary from URL and return path to the file.
    If cache_path is set, download to that path (used for shared cache with extension).
    Otherwise use a temporary file (for one-off validation with --url).
    Raises DownloadError on failure."""
    logger.info("Downloading dictionary from %s...", url)
    try:
        with urllib.request.urlopen(url) as response:
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, 'wb') as f:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                out_path = cache_path
                logger.info("Dictionary cached to: %s", out_path)
            else:
                with tempfile.NamedTemporaryFile(mode='wb', suffix='.dic', delete=False) as tmp_file:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        tmp_file.write(chunk)
                    out_path = Path(tmp_file.name)
                logger.info("Dictionary downloaded to temporary file: %s", out_path)
            return out_path
    except urllib.error.URLError as e:
        logger.error("Error downloading dictionary: %s", e)
        raise DownloadError(f"Failed to download dictionary: {e}") from e
    except Exception as e:
        logger.error("Error processing downloaded dictionary: %s", e)
        raise DownloadError(f"Error processing downloaded dictionary: {e}") from e
