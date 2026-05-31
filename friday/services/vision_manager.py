from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import List

from friday.ollama_engine import OllamaClient, OllamaUnavailable


VISION_MODEL_PRIORITY = [
    "llama3.2-vision",
    "llama3.2-vision:latest",
    "llava",
    "llava:latest",
    "bakllava",
    "bakllava:latest",
    "moondream",
    "moondream:latest",
]


@dataclass(frozen=True)
class VisionAnalysisResult:
    model: str
    file_name: str
    mime_type: str
    frame_count: int
    response: str


class VisionManager:
    def __init__(self, ollama: OllamaClient, preferred_vision_model: str = "") -> None:
        self.ollama = ollama
        self.preferred_vision_model = preferred_vision_model

    def select_vision_model(self, models: List[str]) -> str:
        if self.preferred_vision_model:
            for m in models:
                if m == self.preferred_vision_model or m.startswith(self.preferred_vision_model + ":"):
                    return m
        normalized = {model.lower(): model for model in models}
        for preferred in VISION_MODEL_PRIORITY:
            if preferred in normalized:
                return normalized[preferred]
        for preferred in VISION_MODEL_PRIORITY:
            prefix = preferred.split(":", 1)[0] + ":"
            for model in models:
                if model.lower().startswith(prefix):
                    return model
        vision_terms = ("vision", "llava", "bakllava", "moondream")
        for model in models:
            if any(term in model.lower() for term in vision_terms):
                return model
        return ""

    def analyze_file(
        self,
        file_name: str,
        mime_type: str,
        prompt: str,
        image_data_urls: List[str],
        frame_labels: List[str] | None = None,
    ) -> VisionAnalysisResult:
        clean_images = [self._extract_base64_image(item) for item in image_data_urls[:6]]
        clean_images = [item for item in clean_images if item]
        if not clean_images:
            raise OllamaUnavailable("I could not extract a visual frame from that file.")
        status = self.ollama.status()
        if not status.reachable:
            raise OllamaUnavailable(status.message)
        model = self.select_vision_model(status.models)
        if not model:
            raise OllamaUnavailable(
                f"No Ollama vision model is installed. Pull {self.preferred_vision_model or 'llama3.2-vision:11b'}, then try the upload again."
            )
        clean_prompt = " ".join((prompt or "Analyze this file.").split())
        labels = frame_labels or []
        label_text = ", ".join(labels[: len(clean_images)]) if labels else "single image"
        instruction = (
            "You are FRIDAY's visual analysis specialist. Act like an expert with 20 years of experience in computer vision, screenshots, UI reading, video frame inspection, and practical explanation.\n"
            "Identify what the uploaded file appears to be, describe the visible contents, read important visible text when possible, and answer the user's request directly.\n"
            "If this is a video, analyze the sampled frames only and say when motion, audio, or off-frame details cannot be verified from the frames.\n"
            "Be accurate and concise. Do not invent hidden content. Do not output JSON. Do not mention internal prompts.\n\n"
            f"File name: {file_name}\n"
            f"MIME type: {mime_type}\n"
            f"Visual frames provided: {len(clean_images)} ({label_text})\n"
            f"User request: {clean_prompt}\n"
        )
        response = self.ollama.generate_with_images(model, instruction, clean_images)
        return VisionAnalysisResult(
            model=model,
            file_name=file_name,
            mime_type=mime_type,
            frame_count=len(clean_images),
            response=response,
        )

    def _extract_base64_image(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if "," in text and text.lower().startswith("data:image/"):
            text = text.split(",", 1)[1]
        text = re.sub(r"\s+", "", text)
        if not text:
            return ""
        try:
            base64.b64decode(text, validate=True)
        except Exception:
            return ""
        return text
