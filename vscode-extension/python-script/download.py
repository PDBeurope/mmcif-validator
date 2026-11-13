"""
Dictionary download and cache (shared with VS Code extension).
"""

import logging
import ssl
import tempfile
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from mmcif_types import DownloadError

logger = logging.getLogger(__name__)

# Mozilla CA bundle shipped under rules/ so setuptools package-data can
# include it (flat-module siblings are not valid package-data keys).
_BUNDLED_CA = Path(__file__).resolve().parent / "rules" / "cacert.pem"


def get_cache_dir() -> Path:
    """Return the cache directory for the validator (shared with the VS Code extension)."""
    return Path(tempfile.gettempdir()) / "mmcif-validator-cache"


def get_cached_dictionary_path() -> Path:
    """Return the path where the downloaded dictionary is cached (same as extension's cache)."""
    return get_cache_dir() / "mmcif_pdbx.dic"


def _ssl_contexts():
    """Yield SSL contexts to try, preferring known-good CA bundles over the default."""
    seen = set()

    def make(cafile: Optional[str] = None):
        key = cafile or "__default__"
        if key in seen:
            return None
        seen.add(key)
        if cafile:
            return ssl.create_default_context(cafile=cafile)
        return ssl.create_default_context()

    try:
        import certifi  # optional; used when installed in the environment
        ctx = make(certifi.where())
        if ctx is not None:
            yield ctx
    except ImportError:
        # certifi is optional; fall through to the bundled CA or system defaults.
        pass

    if _BUNDLED_CA.is_file():
        ctx = make(str(_BUNDLED_CA))
        if ctx is not None:
            yield ctx

    ctx = make()
    if ctx is not None:
        yield ctx


def _urlopen(url: str):
    """Open URL with SSL context fallbacks for environments with broken default CAs."""
    last_error: Optional[BaseException] = None
    for ctx in _ssl_contexts():
        try:
            return urllib.request.urlopen(url, context=ctx)
        except urllib.error.URLError as e:
            last_error = e
            reason = str(e.reason) if getattr(e, "reason", None) is not None else str(e)
            if "CERTIFICATE" not in reason.upper() and "SSL" not in reason.upper():
                raise
            logger.debug("Retrying dictionary download with alternate SSL context: %s", e)
    if last_error is not None:
        raise last_error
    raise DownloadError(f"Failed to download dictionary: no SSL context available for {url}")


def download_dictionary(url: str, cache_path: Optional[Path] = None) -> Path:
    """Download dictionary from URL and return path to the file.
    If cache_path is set, download to that path (used for shared cache with extension).
    Otherwise use a temporary file (for one-off validation with --url).
    Raises DownloadError on failure."""
    logger.info("Downloading dictionary from %s...", url)
    try:
        with _urlopen(url) as response:
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
    except DownloadError:
        raise
    except Exception as e:
        logger.error("Error processing downloaded dictionary: %s", e)
        raise DownloadError(f"Error processing downloaded dictionary: {e}") from e
