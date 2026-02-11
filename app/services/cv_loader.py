"""
CV Loader - Factory pattern per caricare CV da diverse sorgenti
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Tuple
import httpx

from ..core.config import get_settings

settings = get_settings()


class CVLoader(ABC):
    """Abstract base class per CV loaders"""
    
    @abstractmethod
    def load(self, reference: str) -> Tuple[bytes, str]:
        """
        Carica il CV dalla sorgente.
        
        Args:
            reference: Percorso/URL/ID del CV
            
        Returns:
            Tuple[bytes, str]: (contenuto_file, filename)
        """
        pass
    
    @abstractmethod
    def exists(self, reference: str) -> bool:
        """Verifica se il CV esiste"""
        pass


class LocalCVLoader(CVLoader):
    """Carica CV da filesystem locale"""
    
    def __init__(self, base_path: str = None):
        self.base_path = Path(base_path or settings.cv_base_path)
    
    def _resolve_path(self, reference: str) -> Path:
        """Risolve il percorso del file"""
        path = Path(reference)
        if path.is_absolute():
            return path
        return self.base_path / reference
    
    def load(self, reference: str) -> Tuple[bytes, str]:
        path = self._resolve_path(reference)
        if not path.exists():
            raise FileNotFoundError(f"CV not found: {path}")
        
        with open(path, 'rb') as f:
            content = f.read()
        
        return content, path.name
    
    def exists(self, reference: str) -> bool:
        return self._resolve_path(reference).exists()


class URLCVLoader(CVLoader):
    """Carica CV da URL pubblico"""
    
    def load(self, reference: str) -> Tuple[bytes, str]:
        response = httpx.get(reference, follow_redirects=True, timeout=30)
        response.raise_for_status()
        
        # Estrai filename da URL o header
        filename = reference.split('/')[-1].split('?')[0]
        if not filename.endswith('.pdf'):
            filename = 'cv.pdf'
        
        return response.content, filename
    
    def exists(self, reference: str) -> bool:
        try:
            response = httpx.head(reference, follow_redirects=True, timeout=10)
            return response.status_code == 200
        except:
            return False


class AzureBlobCVLoader(CVLoader):
    """Carica CV da Azure Blob Storage"""
    
    def __init__(self):
        # Import solo se necessario
        try:
            from azure.storage.blob import BlobServiceClient
            self.blob_service = BlobServiceClient.from_connection_string(
                settings.azure_storage_connection_string
            )
            self.container = self.blob_service.get_container_client(
                settings.azure_container_name
            )
        except ImportError:
            raise ImportError("azure-storage-blob not installed. Run: pip install azure-storage-blob")
    
    def load(self, reference: str) -> Tuple[bytes, str]:
        blob_client = self.container.get_blob_client(reference)
        content = blob_client.download_blob().readall()
        filename = reference.split('/')[-1]
        return content, filename
    
    def exists(self, reference: str) -> bool:
        blob_client = self.container.get_blob_client(reference)
        return blob_client.exists()


class S3CVLoader(CVLoader):
    """Carica CV da AWS S3"""
    
    def __init__(self):
        try:
            import boto3
            self.s3 = boto3.client('s3')
        except ImportError:
            raise ImportError("boto3 not installed. Run: pip install boto3")
    
    def load(self, reference: str) -> Tuple[bytes, str]:
        # reference format: "bucket-name/path/to/cv.pdf"
        parts = reference.split('/', 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else reference
        
        response = self.s3.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read()
        filename = key.split('/')[-1]
        
        return content, filename
    
    def exists(self, reference: str) -> bool:
        try:
            parts = reference.split('/', 1)
            bucket = parts[0]
            key = parts[1] if len(parts) > 1 else reference
            self.s3.head_object(Bucket=bucket, Key=key)
            return True
        except:
            return False


# ============================================================================
# FACTORY
# ============================================================================

_loaders = {
    "local": LocalCVLoader,
    "url": URLCVLoader,
    "azure_blob": AzureBlobCVLoader,
    "s3": S3CVLoader,
}


def get_cv_loader(loader_type: str = None) -> CVLoader:
    """
    Factory function per ottenere il CV loader appropriato.
    
    Args:
        loader_type: Tipo di loader (local, url, azure_blob, s3).
                    Se None, usa il valore da settings.
    
    Returns:
        CVLoader instance
    """
    loader_type = loader_type or settings.cv_loader_type
    
    if loader_type not in _loaders:
        raise ValueError(f"Unknown CV loader type: {loader_type}. Available: {list(_loaders.keys())}")
    
    return _loaders[loader_type]()


def register_cv_loader(name: str, loader_class: type):
    """Registra un nuovo tipo di CV loader"""
    _loaders[name] = loader_class
