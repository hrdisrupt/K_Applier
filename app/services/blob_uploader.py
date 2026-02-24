"""
Azure Blob Storage Uploader for K_AutoApply

Handles uploading screenshots and CVs to Azure Blob Storage.
Falls back to local storage if Azure is not configured.
"""
from pathlib import Path
from typing import Optional
from ..core.config import get_settings

settings = get_settings()


class BlobUploader:
    """
    Uploads files to Azure Blob Storage.
    
    Structure on Blob:
        {container}/
            screenshots/
                app_{id}_{suffix}_{timestamp}.png
                app_{id}_{suffix}_{timestamp}.html
            cvs/
                cv_mario.pdf
    """
    
    def __init__(self):
        self._client = None
        self._container = None
        self._available = False
        self._init_client()
    
    def _init_client(self):
        """Initialize Azure Blob client if configured"""
        if not settings.azure_storage_connection_string:
            print("[AUTOAPPLY] Blob Storage not configured, using local storage only", flush=True)
            return
        
        try:
            from azure.storage.blob import BlobServiceClient
            self._client = BlobServiceClient.from_connection_string(
                settings.azure_storage_connection_string
            )
            self._container = self._client.get_container_client(
                settings.azure_container_name
            )
            # Create container if not exists
            try:
                self._container.get_container_properties()
            except:
                self._container.create_container()
                print(f"[AUTOAPPLY] Created blob container: {settings.azure_container_name}", flush=True)
            
            self._available = True
            print(f"[AUTOAPPLY] Blob Storage connected: {settings.azure_container_name}", flush=True)
        except ImportError:
            print("[AUTOAPPLY] azure-storage-blob not installed, using local storage only", flush=True)
        except Exception as e:
            print(f"[AUTOAPPLY] Blob Storage init failed: {e}, using local storage only", flush=True)
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    def upload_file(self, local_path: str, blob_folder: str) -> Optional[str]:
        """
        Upload a file to Azure Blob Storage.
        
        Args:
            local_path: Path to local file
            blob_folder: Folder in blob container (screenshots, cvs)
            
        Returns:
            Blob URL if uploaded, None if not available
        """
        if not self._available:
            return None
        
        try:
            local_file = Path(local_path)
            if not local_file.exists():
                print(f"[AUTOAPPLY] File not found for upload: {local_path}", flush=True)
                return None
            
            blob_name = f"{blob_folder}/{local_file.name}"
            blob_client = self._container.get_blob_client(blob_name)
            
            with open(local_file, "rb") as f:
                blob_client.upload_blob(f, overwrite=True)
            
            blob_url = blob_client.url
            print(f"[AUTOAPPLY] Uploaded to blob: {blob_name}", flush=True)
            return blob_url
            
        except Exception as e:
            print(f"[AUTOAPPLY] Blob upload failed for {local_path}: {e}", flush=True)
            return None
    
    def upload_bytes(self, data: bytes, filename: str, blob_folder: str = "screenshots") -> Optional[str]:
        """
        Upload bytes directly to Azure Blob Storage.
        
        Args:
            data: File content as bytes
            filename: Name for the blob
            blob_folder: Folder in blob container
            
        Returns:
            Blob URL if uploaded, None if not available
        """
        if not self._available:
            return None
        
        try:
            blob_name = f"{blob_folder}/{filename}"
            blob_client = self._container.get_blob_client(blob_name)
            blob_client.upload_blob(data, overwrite=True)
            
            blob_url = blob_client.url
            print(f"[AUTOAPPLY] Uploaded to blob: {blob_name}", flush=True)
            return blob_url
            
        except Exception as e:
            print(f"[AUTOAPPLY] Blob upload failed for {filename}: {e}", flush=True)
            return None


# Singleton instance
_uploader: Optional[BlobUploader] = None


def get_blob_uploader() -> BlobUploader:
    """Get or create the blob uploader singleton"""
    global _uploader
    if _uploader is None:
        _uploader = BlobUploader()
    return _uploader
