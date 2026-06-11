"""
src/backend/xray_analysis.py

Chest X-ray pathology detection using a pre-trained DenseNet-121 model
via the torchxrayvision library (trained on NIH ChestX-ray14 + CheXpert +
PadChest + RSNA + MIMIC + PC — 400k+ images).

Detects 14 pathologies:
    Atelectasis, Consolidation, Infiltration, Pneumothorax, Edema,
    Emphysema, Fibrosis, Effusion, Pneumonia, Pleural_Thickening,
    Cardiomegaly, Nodule, Mass, Hernia

Usage:
    analyzer = XRayAnalyzer()
    result   = analyzer.analyze(image_path)
"""

import io
import logging
import os
from typing import Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn.functional as F

logger = logging.getLogger(__name__)

# ── Clinical severity tiers ────────────────────────────────────────────────────
# Probabilities are not calibrated — these tiers are directional only.
URGENT_PATHOLOGIES    = {'Pneumothorax', 'Edema', 'Pneumonia', 'Consolidation'}
MODERATE_PATHOLOGIES  = {'Atelectasis', 'Effusion', 'Cardiomegaly', 'Infiltration'}
MONITOR_PATHOLOGIES   = {'Emphysema', 'Fibrosis', 'Nodule', 'Mass',
                         'Pleural_Thickening', 'Hernia'}

# Threshold above which a finding is considered "detected"
DETECTION_THRESHOLD = 0.15


class XRayAnalyzer:
    """
    Lazy-loading wrapper around torchxrayvision DenseNet-121.
    The model is downloaded from HuggingFace on first use (~85 MB).
    """

    def __init__(self):
        self._model  = None
        self._device = None

    # ── Public API ─────────────────────────────────────────────────────────────
    def analyze(self, image_source) -> Dict:
        """
        Analyze a chest X-ray.

        Args:
            image_source: file path (str), bytes, or numpy array (H×W, uint8/float).

        Returns dict with keys:
            pathologies  — list of {name, probability, detected, severity}
            findings     — list of detected pathology names (prob > threshold)
            urgent       — True if any urgent pathology detected
            summary      — human-readable string
            model_info   — model name and dataset provenance
        """
        try:
            model, device = self._load_model()
            img_tensor    = self._preprocess(image_source)
            img_tensor    = img_tensor.to(device)

            with torch.no_grad():
                raw = model(img_tensor)               # shape (1, 14) logits-ish
                probs = torch.sigmoid(raw)[0].cpu().numpy()

            pathologies = model.pathologies           # list of 14 strings
            results     = []
            for name, prob in zip(pathologies, probs):
                prob_f = float(prob)
                results.append({
                    'name':        name,
                    'probability': round(prob_f, 4),
                    'detected':    prob_f >= DETECTION_THRESHOLD,
                    'severity':    self._severity(name, prob_f),
                })

            # Sort: highest probability first
            results.sort(key=lambda x: x['probability'], reverse=True)

            findings = [r['name'] for r in results if r['detected']]
            urgent   = any(f in URGENT_PATHOLOGIES for f in findings)

            return {
                'pathologies': results,
                'findings':    findings,
                'urgent':      urgent,
                'summary':     self._summary(findings, urgent),
                'model_info': {
                    'name':     'DenseNet-121',
                    'weights':  'densenet121-res224-all',
                    'datasets': 'NIH ChestX-ray14 + CheXpert + RSNA + MIMIC + PadChest',
                },
            }

        except ImportError:
            return {
                'error': 'torchxrayvision not installed. Run: pip install torchxrayvision',
                'pathologies': [], 'findings': [], 'urgent': False,
            }
        except Exception as e:
            logger.exception(f"XRayAnalyzer.analyze failed: {e}")
            return {'error': str(e), 'pathologies': [], 'findings': [], 'urgent': False}

    def generate_gradcam(self, image_source, target_class: str) -> Optional[np.ndarray]:
        """
        Generate a Grad-CAM heatmap for the given target pathology.

        Returns a (H, W) float32 numpy array in [0, 1], or None on failure.
        """
        try:
            from pytorch_grad_cam import GradCAM
            from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget

            model, device = self._load_model()
            img_tensor    = self._preprocess(image_source).to(device)

            pathologies = model.pathologies
            if target_class not in pathologies:
                logger.warning(f"GradCAM: unknown pathology '{target_class}'")
                return None

            target_idx = pathologies.index(target_class)

            # DenseNet-121 target layer: last dense block's norm
            target_layers = [model.features.denseblock4.denselayer16.norm1]

            cam = GradCAM(model=model, target_layers=target_layers)
            targets   = [ClassifierOutputTarget(target_idx)]
            grayscale = cam(input_tensor=img_tensor, targets=targets)
            return grayscale[0]   # (H, W) float32

        except ImportError:
            logger.warning("pytorch-grad-cam not installed: pip install grad-cam")
            return None
        except Exception as e:
            logger.warning(f"GradCAM failed: {e}")
            return None

    # ── Private helpers ────────────────────────────────────────────────────────
    def _load_model(self):
        if self._model is not None:
            return self._model, self._device

        import torchxrayvision as xrv

        if torch.backends.mps.is_available():
            device = torch.device('mps')
        elif torch.cuda.is_available():
            device = torch.device('cuda')
        else:
            device = torch.device('cpu')

        logger.info(f"Loading DenseNet-121 X-ray model on {device}…")
        model = xrv.models.DenseNet(weights="densenet121-res224-all")
        model.to(device).eval()

        self._model  = model
        self._device = device
        logger.info("X-ray model loaded.")
        return model, device

    def _preprocess(self, image_source) -> torch.Tensor:
        """Convert any input to a (1, 1, 224, 224) float32 tensor."""
        import torchxrayvision as xrv
        import torchvision.transforms as T
        from PIL import Image

        if isinstance(image_source, np.ndarray):
            arr = image_source.astype(np.float32)
        elif isinstance(image_source, (str, os.PathLike)):
            arr = np.array(Image.open(image_source).convert('L'), dtype=np.float32)
        elif isinstance(image_source, (bytes, bytearray)):
            arr = np.array(Image.open(io.BytesIO(image_source)).convert('L'), dtype=np.float32)
        else:
            raise ValueError(f"Unsupported image_source type: {type(image_source)}")

        # Normalize to [-1024, 1024] as expected by torchxrayvision
        arr = xrv.datasets.normalize(arr, maxval=255, reshape=True)

        transform = T.Compose([
            xrv.datasets.XRayCenterCrop(),
            xrv.datasets.XRayResizer(224),
        ])
        arr = transform(arr)                            # (1, 224, 224)
        return torch.from_numpy(arr).unsqueeze(0)      # (1, 1, 224, 224)

    @staticmethod
    def _severity(name: str, prob: float) -> str:
        if prob < DETECTION_THRESHOLD:
            return 'normal'
        if name in URGENT_PATHOLOGIES:
            return 'urgent' if prob >= 0.4 else 'moderate'
        if name in MODERATE_PATHOLOGIES:
            return 'moderate' if prob >= 0.3 else 'mild'
        return 'mild'

    @staticmethod
    def _summary(findings: List[str], urgent: bool) -> str:
        if not findings:
            return ("No significant pathologies detected above threshold. "
                    "This is a preliminary AI screening — always confirm with a radiologist.")
        prefix = "URGENT findings detected: " if urgent else "Findings detected: "
        return (prefix + ", ".join(findings) +
                ". Please consult a radiologist for formal interpretation.")
